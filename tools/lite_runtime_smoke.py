from __future__ import annotations

import hashlib
import json
import math
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from tools import check_backend_workflow_smoke as workflow
from tools import check_portable_package_runtime as desktop_smoke
from tools import prepare_runtime_fixture


WINDOWS = sys.platform == "win32"
ROOT = Path(__file__).resolve().parents[1]
REQUIRED_EVENTS = desktop_smoke.REQUIRED_LAUNCHER_EVENTS
TERMINAL_EVENTS = frozenset({"backendError", "windowCreateError", "splashCreateError", "frontendReadyTimeout"})
SECRET_KEY = re.compile(r"(?:SECRET|PASSWORD|CREDENTIAL|API_KEY|ACCESS_KEY|TOKEN)", re.IGNORECASE)
PROBE = """
import hashlib
import importlib.metadata
import json
import platform
import site
import sys
from pathlib import Path
import culvia

distribution = importlib.metadata.distribution("culvia")
origin = json.loads(distribution.read_text("direct_url.json") or "null")
config = Path(sys.prefix) / "pyvenv.cfg"
print(json.dumps({
    "module": str(Path(culvia.__file__).resolve()),
    "moduleVersion": str(culvia.__version__),
    "version": distribution.version,
    "distributionRoot": str(Path(distribution.locate_file("")).resolve()),
    "prefix": sys.prefix,
    "basePrefix": sys.base_prefix,
    "executable": sys.executable,
    "baseExecutable": getattr(sys, "_base_executable", ""),
    "architecture": platform.machine(),
    "userSiteEnabled": site.ENABLE_USER_SITE,
    "isolated": bool(sys.flags.isolated),
    "origin": origin,
    "venvConfigSha256": hashlib.sha256(config.read_bytes()).hexdigest(),
    "venvConfigMtimeNs": config.stat().st_mtime_ns,
}))
"""


def check(name: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail}


def result(checks: Sequence[dict[str, Any]], **evidence: Any) -> dict[str, Any]:
    failed = [item["name"] for item in checks if not item["ok"]]
    return {"ok": not failed, "failed": failed, "checks": list(checks), **evidence}


def sha256_file(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _secret_values(environ: Mapping[str, str]) -> set[str]:
    return {value for key, value in environ.items() if SECRET_KEY.search(key) and len(value) >= 4}


def sanitize(value: Any, secrets: set[str]) -> Any:
    if isinstance(value, str):
        for secret in sorted(secrets, key=len, reverse=True):
            value = value.replace(secret, "[redacted]")
        value = re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1[redacted]@", value)
        value = re.sub(r"(?i)((?:api[_-]?key|token|password|secret)=)[^&\s]+", r"\1[redacted]", value)
        return value
    if isinstance(value, dict):
        return {key: sanitize(item, secrets) for key, item in value.items()}
    if isinstance(value, (list, tuple, deque)):
        return [sanitize(item, secrets) for item in value]
    return value


def launch_environment(
    fixture: dict[str, Any],
    *,
    work_dir: Path,
    wheel: Path,
    python: Path,
    timeout: float,
    exit_after_ms: int,
    reuse: bool,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    source = os.environ if environ is None else environ
    prefixes = ("CULVIA_", "PYTHON", "PIP_", "UV_", "OPENAI_", "ANTHROPIC_", "AZURE_OPENAI_", "GEMINI_")
    env = {
        key: value
        for key, value in source.items()
        if not key.upper().startswith(prefixes)
        and not SECRET_KEY.search(key)
        and key.upper() not in {"VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV"}
    }
    env.update({str(key): str(value) for key, value in fixture["env"].items()})
    runtime = work_dir / "runtime"
    temp = work_dir / "process-tmp"
    temp.mkdir(exist_ok=True)
    env.update(
        {
            "CULVIA_DISABLE_KEYCHAIN": "1",
            "CULVIA_RUNTIME_HOME": str(runtime),
            "CULVIA_RUNTIME_CONFIG": str(runtime / "runtime.json"),
            "CULVIA_RUNTIME_VENV": str(runtime / "venv"),
            "CULVIA_RUNTIME_PYTHON": str(python),
            "CULVIA_RUNTIME_PACKAGE": "culvia[desktop-runtime]@" + wheel.as_uri(),
            "CULVIA_DESKTOP_FORCE_BACKEND": "1",
            "CULVIA_DESKTOP_SMOKE": "1",
            "CULVIA_DESKTOP_SMOKE_EXIT_AFTER_MS": str(exit_after_ms),
            "CULVIA_DESKTOP_READY_TIMEOUT_SECS": str(math.ceil(timeout)),
            "CULVIA_DESKTOP_BACKEND_HEALTH_TIMEOUT_SECS": str(math.ceil(timeout)),
            "CULVIA_DESKTOP_FRONTEND_READY_TIMEOUT_SECS": str(math.ceil(timeout)),
            "PYTHONNOUSERSITE": "1",
            "PYTHONSAFEPATH": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INPUT": "1",
            "PIP_NO_CACHE_DIR": "1",
            "HF_HOME": str(work_dir / "model-cache"),
            "TORCH_HOME": str(work_dir / "model-cache"),
            "TMPDIR": str(temp),
            "TEMP": str(temp),
            "TMP": str(temp),
        }
    )
    if reuse:
        env["CULVIA_RUNTIME_SKIP_INSTALL"] = "1"
    return env


class _WindowsJob:
    """Own every descendant, including children of an already-exited shell."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_uint64)
                for name in (
                    "ReadOperationCount",
                    "WriteOperationCount",
                    "OtherOperationCount",
                    "ReadTransferCount",
                    "WriteTransferCount",
                    "OtherTransferCount",
                )
            ]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimits),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        self.ctypes = ctypes
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.SetInformationJobObject.restype = wintypes.BOOL
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        self.kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.kernel.TerminateJobObject.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign_and_resume(self, process: subprocess.Popen[str]) -> None:
        handle = int(process._handle)  # Windows Popen retains the owning process handle.
        if not self.kernel.AssignProcessToJobObject(self.handle, handle):
            raise self.ctypes.WinError(self.ctypes.get_last_error())
        self.resume_initial_thread(process.pid)

    def resume_initial_thread(self, pid: int) -> None:
        from ctypes import wintypes

        ctypes = self.ctypes

        class ThreadEntry(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ThreadID", wintypes.DWORD),
                ("th32OwnerProcessID", wintypes.DWORD),
                ("tpBasePri", wintypes.LONG),
                ("tpDeltaPri", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
            ]

        self.kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self.kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        for name in ("Thread32First", "Thread32Next"):
            function = getattr(self.kernel, name)
            function.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
            function.restype = wintypes.BOOL
        self.kernel.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenThread.restype = wintypes.HANDLE
        self.kernel.ResumeThread.argtypes = [wintypes.HANDLE]
        self.kernel.ResumeThread.restype = wintypes.DWORD
        snapshot = self.kernel.CreateToolhelp32Snapshot(0x00000004, 0)  # TH32CS_SNAPTHREAD
        if snapshot == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = ThreadEntry()
            entry.dwSize = ctypes.sizeof(entry)
            found = self.kernel.Thread32First(snapshot, ctypes.byref(entry))
            while found:
                if entry.th32OwnerProcessID == pid:
                    thread = self.kernel.OpenThread(0x0002, False, entry.th32ThreadID)  # THREAD_SUSPEND_RESUME
                    if not thread:
                        raise ctypes.WinError(ctypes.get_last_error())
                    try:
                        previous = self.kernel.ResumeThread(thread)
                        if previous == 0xFFFFFFFF:
                            raise ctypes.WinError(ctypes.get_last_error())
                        if previous == 1:
                            return
                    finally:
                        self.kernel.CloseHandle(thread)
                found = self.kernel.Thread32Next(snapshot, ctypes.byref(entry))
            raise OSError("Could not find the suspended launcher thread")
        finally:
            self.kernel.CloseHandle(snapshot)

    def terminate(self) -> None:
        if self.handle and not self.kernel.TerminateJobObject(self.handle, 1):
            raise self.ctypes.WinError(self.ctypes.get_last_error())

    def close(self) -> None:
        if self.handle:
            if not self.kernel.CloseHandle(self.handle):
                raise self.ctypes.WinError(self.ctypes.get_last_error())
            self.handle = None


class ProcessTree:
    def __init__(self) -> None:
        self.process: subprocess.Popen[str] | None = None
        self.job: _WindowsJob | None = None
        self.closed = False

    def start(self, command: Sequence[str], *, cwd: Path, env: dict[str, str]) -> subprocess.Popen[str]:
        options: dict[str, Any] = {}
        if WINDOWS:
            self.job = _WindowsJob()
            # Assign while suspended: no installer may escape before job ownership.
            options["creationflags"] = 0x00000004 | 0x00000200
        else:
            options["start_new_session"] = True
        try:
            self.process = subprocess.Popen(
                list(command),
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **options,
            )
            if self.job is not None:
                self.job.assign_and_resume(self.process)
            return self.process
        except BaseException:
            self.close()
            raise

    def close(self) -> str:
        if self.closed:
            return ""
        self.closed = True
        errors: list[str] = []
        process = self.process
        try:
            if self.job is not None:
                self.job.terminate()
            elif process is not None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            if process is not None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(str(exc))
        finally:
            if self.job is not None:
                try:
                    self.job.close()
                except OSError as exc:
                    errors.append(str(exc))
                self.job = None
            elif process is not None:
                # The leader can exit before pip or the backend; still kill its group.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except OSError as exc:
                    errors.append(str(exc))
        return "; ".join(errors)


def launcher_command(launcher: Path, expected_target: str, env: Mapping[str, str]) -> list[str]:
    if "-linux-" in expected_target and not env.get("DISPLAY"):
        xvfb = shutil.which("xvfb-run", path=env.get("PATH"))
        if not xvfb:
            raise ValueError("Linux launcher smoke requires DISPLAY or xvfb-run")
        return [xvfb, "-a", str(launcher)]
    return [str(launcher)]


def loopback_url(events: Sequence[dict[str, Any]]) -> str:
    base_url = desktop_smoke.base_url_from_events(events)
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("Desktop readiness must identify a loopback HTTP backend")
    return base_url


def wait_for_lite_events(
    process: subprocess.Popen[str],
    *,
    timeout: float,
    stdout_tail: deque[str],
    stderr_tail: deque[str],
) -> list[dict[str, Any]]:
    assert process.stdout is not None
    assert process.stderr is not None
    lines: queue.Queue[str | None] = queue.Queue()

    def drain(stream, tail: deque[str]) -> None:
        try:
            desktop_smoke.drain_lines(stream, lines, tail)
        finally:
            lines.put(None)

    threading.Thread(target=drain, args=(process.stdout, stdout_tail), daemon=True).start()
    threading.Thread(target=drain, args=(process.stderr, stderr_tail), daemon=True).start()
    seen: dict[str, dict[str, Any]] = {}
    finished_streams = 0
    deadline = time.monotonic() + timeout
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            line = lines.get(timeout=min(0.25, remaining))
        except queue.Empty:
            continue
        if line is None:
            finished_streams += 1
            if finished_streams == 2:
                break
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        name = event.get("event")
        if not isinstance(name, str) or name not in (*REQUIRED_EVENTS, *TERMINAL_EVENTS):
            continue
        seen[name] = event
        if name in TERMINAL_EVENTS or all(required in seen for required in REQUIRED_EVENTS):
            break
    return list(seen.values())


def identity_checks(state: Any, *, version: str, target: str) -> list[dict[str, Any]]:
    app = state.get("app") if isinstance(state, dict) else None
    app = app if isinstance(app, dict) else {}
    expected = {
        "shellVersion": version,
        "serviceVersion": version,
        "runtimeProfile": "lite",
        "desktopTarget": target,
        "distribution": "desktop",
    }
    return [
        check(f"app {key} matches candidate", app.get(key) == value, f"expected={value}, actual={app.get(key)}")
        for key, value in expected.items()
    ]


def _within(path: Any, parent: Path) -> bool:
    try:
        return bool(path) and Path(str(path)).resolve().is_relative_to(parent.resolve())
    except (OSError, ValueError):
        return False


def _architecture(value: Any) -> str:
    return {"amd64": "x86_64", "x64": "x86_64", "arm64": "aarch64"}.get(str(value).lower(), str(value).lower())


def probe_checks(
    probe: dict[str, Any],
    *,
    venv: Path,
    python: Path,
    wheel: Path,
    wheel_sha256: str,
    expected_version: str,
    expected_target: str,
) -> list[dict[str, Any]]:
    origin = probe.get("origin")
    origin = origin if isinstance(origin, dict) else {}
    archive = origin.get("archive_info")
    archive = archive if isinstance(archive, dict) else {}
    hashes = archive.get("hashes")
    hashes = hashes if isinstance(hashes, dict) else {}
    digest = hashes.get("sha256") or str(archive.get("hash") or "").removeprefix("sha256=")
    prefix = Path(str(probe.get("prefix") or ""))
    base = Path(str(probe.get("baseExecutable") or ""))
    return [
        check(
            "runtime is isolated candidate venv",
            prefix.resolve() == venv.resolve()
            and str(probe.get("basePrefix")) != str(probe.get("prefix"))
            and probe.get("isolated") is True
            and probe.get("userSiteEnabled") is False,
            f"prefix={probe.get('prefix')}, isolated={probe.get('isolated')}, userSite={probe.get('userSiteEnabled')}",
        ),
        check("runtime uses selected base Python", base.resolve() == python.resolve(), str(base)),
        check(
            "runtime imports installed candidate only",
            _within(probe.get("module"), venv) and _within(probe.get("distributionRoot"), venv),
            f"module={probe.get('module')}",
        ),
        check(
            "runtime version matches candidate",
            probe.get("version") == expected_version and probe.get("moduleVersion") == expected_version,
            f"distribution={probe.get('version')}, module={probe.get('moduleVersion')}, expected={expected_version}",
        ),
        check(
            "runtime architecture matches package",
            _architecture(probe.get("architecture")) == expected_target.split("-", 1)[0],
            f"architecture={probe.get('architecture')}, target={expected_target}",
        ),
        check(
            "runtime installed exact candidate wheel",
            origin.get("url") == wheel.as_uri() and digest == wheel_sha256 and "dir_info" not in origin,
            f"origin={origin.get('url')}, sha256={digest}",
        ),
        check(
            "runtime venv configuration exists",
            bool(probe.get("venvConfigSha256")) and isinstance(probe.get("venvConfigMtimeNs"), int),
            "pyvenv.cfg fingerprint recorded",
        ),
    ]


def probe_runtime(
    *,
    venv: Path,
    python: Path,
    wheel: Path,
    wheel_sha256: str,
    expected_version: str,
    expected_target: str,
    work_dir: Path,
    env: dict[str, str],
) -> dict[str, Any]:
    executable = venv / ("Scripts/python.exe" if WINDOWS else "bin/python")
    checks = [check("shell created runtime Python", executable.is_file(), str(executable))]
    if not checks[-1]["ok"]:
        return result(checks)
    tree = ProcessTree()
    payload: dict[str, Any] = {}
    try:
        process = tree.start([str(executable), "-I", "-c", PROBE], cwd=work_dir, env=env)
        stdout, stderr = process.communicate(timeout=30)
        if process.returncode != 0:
            raise RuntimeError(f"runtime probe exited {process.returncode}: {stderr[-1600:]}")
        payload = json.loads(stdout)
        if not isinstance(payload, dict):
            raise ValueError("Runtime probe must return a JSON object")
        checks.extend(
            probe_checks(
                payload,
                venv=venv,
                python=python,
                wheel=wheel,
                wheel_sha256=wheel_sha256,
                expected_version=expected_version,
                expected_target=expected_target,
            )
        )
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        checks.append(check("runtime probe succeeds", False, str(exc)))
    finally:
        cleanup_error = tree.close()
        checks.append(check("runtime probe process tree closes", not cleanup_error, cleanup_error or "closed"))
    return result(checks, runtime=payload)


def run_launch(
    *,
    launcher: Path,
    expected_version: str,
    expected_target: str,
    wheel: Path,
    python: Path,
    work_dir: Path,
    timeout: float,
    exit_after_ms: int,
    reuse: bool,
) -> dict[str, Any]:
    started = time.monotonic()
    fixture = prepare_runtime_fixture.write_fixture(work_dir / ("reuse-fixture" if reuse else "first-fixture"), count=4)
    env = launch_environment(
        fixture,
        work_dir=work_dir,
        wheel=wheel,
        python=python,
        timeout=timeout,
        exit_after_ms=exit_after_ms,
        reuse=reuse,
    )
    tree = ProcessTree()
    checks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    terminal_events: list[dict[str, Any]] = []
    stdout_tail: deque[str] = deque(maxlen=60)
    stderr_tail: deque[str] = deque(maxlen=60)
    base_url = ""
    returncode: int | None = None
    try:
        process = tree.start(launcher_command(launcher, expected_target, env), cwd=work_dir, env=env)
        events = wait_for_lite_events(process, timeout=timeout, stdout_tail=stdout_tail, stderr_tail=stderr_tail)
        event_names = [event.get("event") for event in events]
        terminal_events = [event for event in events if event.get("event") in TERMINAL_EVENTS]
        ready = not terminal_events and all(name in event_names for name in REQUIRED_EVENTS)
        checks.append(
            check(
                "desktop reports no startup failure",
                not terminal_events,
                json.dumps(terminal_events, ensure_ascii=False) if terminal_events else "no terminal failure event",
            )
        )
        checks.append(check("desktop emits all ready events", ready, f"events={event_names}"))
        if "backendReady" in event_names:
            base_url = loopback_url(events)
        if ready:
            request_timeout = min(15.0, max(3.0, timeout / 6))
            state = workflow.request_json(base_url, "/api/state", timeout=request_timeout)
            identity = identity_checks(state, version=expected_version, target=expected_target)
            checks.extend(identity)
            if all(item["ok"] for item in identity):
                workflow_checks = workflow.collect_workflow_checks(
                    base_url=base_url,
                    fixture=fixture,
                    export_dir=Path(str(fixture["root"])) / "exported",
                    timeout=request_timeout,
                )
                checks.extend(check(item.name, item.ok, item.detail) for item in workflow_checks)
            try:
                returncode = process.wait(timeout=max(2.0, exit_after_ms / 1000 + 5))
                checks.append(check("desktop exits automatically", returncode == 0, f"returncode={returncode}"))
            except subprocess.TimeoutExpired:
                checks.append(
                    check("desktop exits automatically", False, "launcher did not exit after frontend readiness")
                )
        else:
            returncode = process.poll()
            checks.append(check("desktop exits automatically", False, f"readiness incomplete, returncode={returncode}"))
        if ready and base_url and returncode == 0:
            shutdown_error = desktop_smoke.wait_for_backend_shutdown(base_url)
            checks.append(
                check("desktop stops backend after exit", not shutdown_error, shutdown_error or "backend stopped")
            )
        else:
            checks.append(check("desktop stops backend after exit", False, "normal desktop exit was not observed"))
    except Exception as exc:  # noqa: BLE001 - smoke evidence must retain launch and API failures.
        checks.append(check("desktop launch and workflow complete", False, str(exc)))
    finally:
        cleanup_error = tree.close()
        checks.append(check("desktop process tree closes", not cleanup_error, cleanup_error or "closed"))
        if tree.process is not None:
            returncode = tree.process.poll()
        if base_url:
            remaining = desktop_smoke.wait_for_backend_shutdown(base_url, timeout=5)
            checks.append(check("backend is stopped after cleanup", not remaining, remaining or "backend stopped"))
    return result(
        checks,
        events=events,
        terminalEvents=terminal_events,
        returncode=returncode,
        seconds=round(time.monotonic() - started, 3),
        stdoutTail=list(stdout_tail),
        stderrTail=list(stderr_tail),
        skipInstall=reuse,
    )


def run_lite_smoke(
    *,
    launcher: Path,
    expected_version: str,
    expected_target: str,
    wheel: Path,
    python: Path,
    work_dir: Path,
    timeout: float = 900,
    exit_after_ms: int = 20000,
) -> dict[str, Any]:
    secrets = _secret_values(os.environ) | {workflow.SENTINEL_LLM_API_KEY}
    checks: list[dict[str, Any]] = []
    first: dict[str, Any] | None = None
    reuse: dict[str, Any] | None = None
    evidence: dict[str, Any] = {}
    try:
        inputs_ok = all(path.is_absolute() for path in (launcher, wheel, python, work_dir))
        inputs_ok = inputs_ok and all(path.is_file() for path in (launcher, wheel, python))
        checks.append(check("smoke inputs are absolute files", inputs_ok, "launcher, wheel, and base Python"))
        isolated = work_dir.is_dir() and not any(work_dir.iterdir()) and not work_dir.resolve().is_relative_to(ROOT)
        checks.append(check("smoke work directory is empty and outside checkout", isolated, str(work_dir)))
        checks.append(
            check(
                "smoke timing is positive",
                math.isfinite(timeout) and timeout > 0 and exit_after_ms > 0,
                f"timeout={timeout}, exitAfterMs={exit_after_ms}",
            )
        )
        if not all(item["ok"] for item in checks):
            return sanitize(result(checks, firstLaunch=None, reuseLaunch=None), secrets)
        wheel = wheel.resolve()
        work_dir = work_dir.resolve()
        digest = sha256_file(wheel)
        venv = work_dir / "runtime" / "venv"
        evidence = {"wheel": str(wheel), "wheelSha256": digest, "runtimeVenv": str(venv), "workDir": str(work_dir)}
        checks.append(check("runtime absent before first launch", not venv.exists(), str(venv)))
        for is_reuse in (False, True):
            launched = run_launch(
                launcher=launcher,
                expected_version=expected_version,
                expected_target=expected_target,
                wheel=wheel,
                python=python,
                work_dir=work_dir,
                timeout=timeout,
                exit_after_ms=exit_after_ms,
                reuse=is_reuse,
            )
            if is_reuse:
                reuse = launched
            else:
                first = launched
            label = "reuse launch" if is_reuse else "first launch"
            checks.extend({**item, "name": f"{label}: {item['name']}"} for item in launched["checks"])
            if not launched["ok"]:
                break
            env = launch_environment(
                {"env": {}},
                work_dir=work_dir,
                wheel=wheel,
                python=python,
                timeout=timeout,
                exit_after_ms=exit_after_ms,
                reuse=is_reuse,
            )
            probe = probe_runtime(
                venv=venv,
                python=python,
                wheel=wheel,
                wheel_sha256=digest,
                expected_version=expected_version,
                expected_target=expected_target,
                work_dir=work_dir,
                env=env,
            )
            launched["runtimeProbe"] = probe
            checks.extend({**item, "name": f"{label}: {item['name']}"} for item in probe["checks"])
            launched["ok"] = launched["ok"] and probe["ok"]
            launched["failed"].extend(probe["failed"])
            if not probe["ok"]:
                break
        if reuse is not None and reuse["ok"] and first is not None:
            first_runtime = first["runtimeProbe"]["runtime"]
            reuse_runtime = reuse["runtimeProbe"]["runtime"]
            keys = ("prefix", "module", "origin", "venvConfigSha256", "venvConfigMtimeNs")
            checks.append(
                check(
                    "second launch reuses unchanged installed runtime",
                    all(first_runtime.get(key) == reuse_runtime.get(key) for key in keys),
                    "same venv, import path, wheel origin, and venv configuration; installation disabled",
                )
            )
        checks.append(check("candidate wheel remains unchanged", sha256_file(wheel) == digest, digest))
    except Exception as exc:  # noqa: BLE001 - setup failures must not be reported as successful smoke.
        checks.append(check("lite smoke setup and verification complete", False, str(exc)))
    return sanitize(result(checks, firstLaunch=first, reuseLaunch=reuse, **evidence), secrets)
