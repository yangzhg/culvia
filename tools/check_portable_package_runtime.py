from __future__ import annotations

import argparse
import json
import os
import platform
import queue
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from collections import deque
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import check_portable_package_preflight


WINDOWS_LABEL = "windows portable zip runtime"
LINUX_LABEL = "linux portable tgz runtime"
REQUIRED_LAUNCHER_EVENTS = ("backendReady", "windowCreated", "frontendReady")
DEFAULT_EXIT_AFTER_MS = 20000
DEFAULT_FIXTURE_COUNT = 4
TEMP_CLEANUP_ATTEMPTS = 90
TEMP_CLEANUP_DELAY_SECS = 0.5
BACKEND_SHUTDOWN_TIMEOUT_SECS = 30.0
BACKEND_SHUTDOWN_POLL_SECS = 0.5


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class RuntimeSpec:
    label: str
    native_platform: str
    preflight: Callable[[Path], list[check_portable_package_preflight.CheckResult]]
    extract: Callable[[Path, Path], tuple[Path | None, list[str]]]


def check(name: str, ok: bool, detail: str) -> CheckResult:
    return CheckResult(name=name, ok=bool(ok), detail=detail)


def result_payload(checks: Sequence[CheckResult]) -> dict[str, Any]:
    failed = [item.name for item in checks if not item.ok]
    return {
        "ok": not failed,
        "failed": failed,
        "checks": [{"name": item.name, "ok": item.ok, "detail": item.detail} for item in checks],
    }


def native_platform_key() -> str | None:
    system = platform.system().lower()
    if system.startswith("win"):
        return "windows"
    if system == "linux":
        return "linux"
    return None


def native_arch_key() -> str:
    machine = platform.machine().lower().strip()
    if machine in {"amd64", "x64"}:
        return "x86_64"
    if machine in {"arm64"}:
        return "aarch64"
    return machine


def target_matches_host_arch(target: str) -> bool:
    normalized = target.lower().strip()
    if not normalized:
        return False
    return normalized.startswith(native_arch_key())


def compact_output(stdout: str, stderr: str, *, max_chars: int = 1600) -> str:
    text = "\n".join(part.strip() for part in (stdout, stderr) if part.strip()).strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def compact_lines(lines: Sequence[str], *, max_chars: int = 1600) -> str:
    return compact_output("\n".join(lines), "", max_chars=max_chars)


def remove_tree_with_retries(
    path: Path,
    *,
    attempts: int = TEMP_CLEANUP_ATTEMPTS,
    delay: float = TEMP_CLEANUP_DELAY_SECS,
) -> str:
    last_error: OSError | None = None
    for attempt in range(max(1, attempts)):
        try:
            shutil.rmtree(path)
            return ""
        except FileNotFoundError:
            return ""
        except OSError as exc:
            last_error = exc
            if attempt < max(1, attempts) - 1:
                time.sleep(max(0.0, delay))
    return f"could not remove temporary directory {path}: {last_error}"


def safe_join(package_root: Path, relative: Any) -> Path | None:
    if not check_portable_package_preflight.relative_manifest_path(relative):
        return None
    path = package_root / PurePosixPath(str(relative))
    try:
        path.resolve().relative_to(package_root.resolve())
    except ValueError:
        return None
    return path


def extract_windows_zip(path: Path, destination: Path) -> tuple[Path | None, list[str]]:
    members, member_issues = check_portable_package_preflight.zip_members(path)
    names = [member.name for member in members]
    prefix, path_issues = check_portable_package_preflight.top_level_dir(names)
    link_issues = [member.name for member in members if member.link or member.special]
    issues = [*member_issues, *path_issues]
    if link_issues:
        issues.append("archive contains links or special entries")
    if issues or prefix is None:
        return None, issues
    try:
        with zipfile.ZipFile(path) as archive:
            archive.extractall(destination)
    except (OSError, zipfile.BadZipFile) as exc:
        return None, [f"cannot extract zip: {exc}"]
    return destination / prefix, []


def extract_linux_tgz(path: Path, destination: Path) -> tuple[Path | None, list[str]]:
    members, member_issues = check_portable_package_preflight.tar_members(path)
    names = [member.name for member in members]
    prefix, path_issues = check_portable_package_preflight.top_level_dir(names)
    special_issues = [member.name for member in members if member.link or member.special]
    issues = [*member_issues, *path_issues]
    if special_issues:
        issues.append("archive contains links, devices, or special entries")
    if issues or prefix is None:
        return None, issues
    try:
        with tarfile.open(path, "r:gz") as archive:
            archive.extractall(destination)
    except (OSError, tarfile.TarError) as exc:
        return None, [f"cannot extract tar.gz: {exc}"]
    return destination / prefix, []


WINDOWS_SPEC = RuntimeSpec(
    label=WINDOWS_LABEL,
    native_platform="windows",
    preflight=check_portable_package_preflight.collect_windows_zip_checks,
    extract=extract_windows_zip,
)
LINUX_SPEC = RuntimeSpec(
    label=LINUX_LABEL,
    native_platform="linux",
    preflight=check_portable_package_preflight.collect_linux_tgz_checks,
    extract=extract_linux_tgz,
)


def read_manifest(package_root: Path) -> tuple[dict[str, Any] | None, str]:
    manifest_path = package_root / "share" / "culvia" / "manifest.json"
    if not manifest_path.is_file():
        return None, f"missing manifest: {manifest_path}"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"invalid manifest JSON: {exc}"
    if not isinstance(payload, dict):
        return None, "manifest must contain a JSON object"
    return payload, ""


def runtime_paths(package_root: Path, manifest: dict[str, Any]) -> tuple[dict[str, Path], list[str]]:
    backend = manifest.get("backend") if isinstance(manifest.get("backend"), dict) else {}
    web = manifest.get("web") if isinstance(manifest.get("web"), dict) else {}
    requested = {
        "launcher": manifest.get("launcher"),
        "backend": backend.get("path") if isinstance(backend, dict) else None,
        "web entry": web.get("entry") if isinstance(web, dict) else None,
    }
    paths: dict[str, Path] = {}
    issues: list[str] = []
    for label, relative in requested.items():
        resolved = safe_join(package_root, relative)
        if resolved is None:
            issues.append(f"{label} must be a safe relative manifest path")
            continue
        paths[label] = resolved
        if not resolved.exists():
            issues.append(f"missing {label}: {resolved}")
    return paths, issues


def parse_launcher_event(line: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(line.strip())
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict) and payload.get("event") in REQUIRED_LAUNCHER_EVENTS:
        return payload
    return None


def drain_lines(stream, output: queue.Queue[str] | None = None, tail: deque[str] | None = None) -> None:
    try:
        for line in iter(stream.readline, ""):
            text = line.rstrip("\n")
            if output is not None:
                output.put(text)
            if tail is not None:
                tail.append(text)
    finally:
        stream.close()


def wait_for_launcher_events(
    process: subprocess.Popen[str],
    *,
    timeout: float,
    stdout_tail: deque[str],
    stderr_tail: deque[str],
) -> list[dict[str, Any]]:
    assert process.stdout is not None
    assert process.stderr is not None
    stdout_lines: queue.Queue[str] = queue.Queue()
    threading.Thread(target=drain_lines, args=(process.stdout, stdout_lines, stdout_tail), daemon=True).start()
    threading.Thread(target=drain_lines, args=(process.stderr, None, stderr_tail), daemon=True).start()

    seen: dict[str, dict[str, Any]] = {}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None and stdout_lines.empty():
            break
        try:
            line = stdout_lines.get(timeout=0.25)
        except queue.Empty:
            continue
        event = parse_launcher_event(line)
        if event is None:
            continue
        seen[str(event["event"])] = event
        if all(name in seen for name in REQUIRED_LAUNCHER_EVENTS):
            return [seen[name] for name in REQUIRED_LAUNCHER_EVENTS]
    return [seen[name] for name in REQUIRED_LAUNCHER_EVENTS if name in seen]


def base_url_from_events(events: Sequence[dict[str, Any]]) -> str:
    for event in events:
        if event.get("event") == "backendReady":
            base_url = str(event.get("baseUrl") or "").strip()
            if base_url:
                return base_url
    return ""


def backend_health_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/health"


def backend_responds(url: str, *, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=max(0.1, timeout)):
            return True
    except urllib.error.HTTPError:
        return True
    except (OSError, urllib.error.URLError, ValueError):
        return False


def wait_for_backend_shutdown(
    base_url: str,
    *,
    timeout: float = BACKEND_SHUTDOWN_TIMEOUT_SECS,
    delay: float = BACKEND_SHUTDOWN_POLL_SECS,
) -> str:
    if not base_url:
        return ""
    health_url = backend_health_url(base_url)
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() <= deadline:
        if not backend_responds(health_url, timeout=min(1.0, max(0.1, delay))):
            return ""
        time.sleep(max(0.0, delay))
    return f"backend still answered {health_url} after {timeout:.1f}s"


def cleanup_error_is_nonblocking(
    *,
    spec: RuntimeSpec,
    cleanup_error: str,
    backend_shutdown_error: str,
    returncode: int | None,
) -> bool:
    if not cleanup_error:
        return False
    if spec.native_platform != "windows":
        return False
    if backend_shutdown_error or returncode != 0:
        return False
    normalized = cleanup_error.lower()
    return "winerror 32" in normalized and "culvia_scores.sqlite" in normalized


def launcher_environment(fixture: dict[str, Any], *, timeout: int, exit_after_ms: int) -> dict[str, str]:
    from tools import check_backend_workflow_smoke

    env = check_backend_workflow_smoke.workflow_environment(fixture)
    env["CULVIA_DESKTOP_FORCE_BACKEND"] = "1"
    env["CULVIA_DESKTOP_SMOKE"] = "1"
    env["CULVIA_DESKTOP_SMOKE_EXIT_AFTER_MS"] = str(max(1, exit_after_ms))
    env["CULVIA_DESKTOP_READY_TIMEOUT_SECS"] = str(max(1, timeout))
    env["CULVIA_DESKTOP_BACKEND_HEALTH_TIMEOUT_SECS"] = str(max(1, timeout))
    env["CULVIA_DESKTOP_HEALTH_TIMEOUT_SECS"] = str(max(1, timeout))
    env["CULVIA_DESKTOP_FRONTEND_READY_TIMEOUT_SECS"] = str(max(1, timeout))
    return env


def launcher_command(launcher: Path, *, spec: RuntimeSpec) -> tuple[list[str], list[str]]:
    if spec.native_platform == "linux" and not os.environ.get("DISPLAY"):
        xvfb = shutil.which("xvfb-run")
        if not xvfb:
            return [], ["linux launcher smoke requires DISPLAY or xvfb-run"]
        return [xvfb, "-a", str(launcher)], []
    return [str(launcher)], []


def terminate_process(process: subprocess.Popen[str]) -> int | None:
    if process.poll() is not None:
        return process.returncode
    process.terminate()
    try:
        return process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.wait(timeout=5)


def collect_launcher_workflow_checks(
    *,
    base_url: str,
    fixture: dict[str, Any],
    spec: RuntimeSpec,
    timeout: float,
) -> list[CheckResult]:
    from tools import check_backend_workflow_smoke

    export_dir = Path(str(fixture["root"])) / "launcher-exported"
    checks = check_backend_workflow_smoke.collect_workflow_checks(
        base_url=base_url,
        fixture=fixture,
        export_dir=export_dir,
        timeout=timeout,
    )
    return [
        check(item.name.replace("backend workflow", f"{spec.label} launcher workflow"), item.ok, item.detail)
        for item in checks
    ]


def run_launcher_workflow_smoke(
    *,
    package_root: Path,
    launcher: Path,
    spec: RuntimeSpec,
    timeout: int,
    exit_after_ms: int = DEFAULT_EXIT_AFTER_MS,
) -> tuple[bool, str]:
    command, command_issues = launcher_command(launcher, spec=spec)
    if command_issues:
        return False, "; ".join(command_issues)

    from tools import prepare_runtime_fixture

    tmp_path = Path(tempfile.mkdtemp(prefix="culvia-portable-launcher-fixture-"))
    fixture = prepare_runtime_fixture.write_fixture(tmp_path, count=DEFAULT_FIXTURE_COUNT, force=False)
    stdout_tail: deque[str] = deque(maxlen=80)
    stderr_tail: deque[str] = deque(maxlen=80)
    process: subprocess.Popen[str] | None = None
    checks: list[CheckResult] = []
    events: list[dict[str, Any]] = []
    returncode: int | None = None
    base_url = ""
    backend_shutdown_error = ""
    cleanup_error = ""
    try:
        try:
            process = subprocess.Popen(
                command,
                cwd=package_root,
                env=launcher_environment(fixture, timeout=timeout, exit_after_ms=exit_after_ms),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            events = wait_for_launcher_events(
                process,
                timeout=timeout,
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
            )
            event_names = [str(event.get("event")) for event in events]
            events_ok = event_names == list(REQUIRED_LAUNCHER_EVENTS)
            checks.append(
                check(
                    f"{spec.label} launcher emits backend, window, and frontend ready events",
                    events_ok,
                    f"events={event_names}",
                )
            )
            if events_ok:
                base_url = base_url_from_events(events)
                if base_url:
                    checks.extend(
                        collect_launcher_workflow_checks(
                            base_url=base_url,
                            fixture=fixture,
                            spec=spec,
                            timeout=min(15.0, max(3.0, timeout / 6.0)),
                        )
                    )
                else:
                    checks.append(
                        check(f"{spec.label} launcher exposes backend base url", False, f"events={event_names}")
                    )
            try:
                returncode = process.wait(timeout=max(2.0, exit_after_ms / 1000.0 + 5.0))
            except subprocess.TimeoutExpired:
                returncode = terminate_process(process)
                checks.append(
                    check(
                        f"{spec.label} launcher exits after smoke frontend readiness",
                        False,
                        f"terminated launcher after timeout, returncode={returncode}",
                    )
                )
            else:
                checks.append(
                    check(
                        f"{spec.label} launcher exits after smoke frontend readiness",
                        returncode == 0,
                        f"returncode={returncode}",
                    )
                )
        except Exception as exc:  # noqa: BLE001 - release smoke reports the exact launch failure.
            checks.append(check(f"{spec.label} launcher starts", False, repr(exc)))
            returncode = terminate_process(process) if process is not None else None
    finally:
        if process is not None and process.poll() is None:
            returncode = terminate_process(process)
        if base_url:
            backend_shutdown_error = wait_for_backend_shutdown(base_url)
        cleanup_error = remove_tree_with_retries(tmp_path)

    if backend_shutdown_error:
        checks.append(check(f"{spec.label} launcher stops bundled backend after exit", False, backend_shutdown_error))
    cleanup_warning = ""
    if cleanup_error and cleanup_error_is_nonblocking(
        spec=spec,
        cleanup_error=cleanup_error,
        backend_shutdown_error=backend_shutdown_error,
        returncode=returncode,
    ):
        cleanup_warning = cleanup_error
    elif cleanup_error:
        checks.append(check(f"{spec.label} launcher fixture cleanup releases temporary files", False, cleanup_error))

    payload = result_payload(checks)
    detail = {
        "command": command,
        "events": events,
        "failed": payload["failed"],
        "returncode": returncode,
        "backendShutdownError": backend_shutdown_error,
        "cleanupError": cleanup_error,
        "cleanupWarning": cleanup_warning,
        "stdoutTail": list(stdout_tail),
        "stderrTail": list(stderr_tail),
    }
    if payload["ok"]:
        warning = f"; cleanup warning: {cleanup_warning}" if cleanup_warning else ""
        return True, f"launcher smoke passed: events={[event.get('event') for event in events]}{warning}"
    return False, json.dumps(detail, ensure_ascii=False)


def collect_runtime_checks(
    *,
    artifact: Path,
    spec: RuntimeSpec,
    launch: bool = True,
    timeout: int = 90,
    exit_after_ms: int = DEFAULT_EXIT_AFTER_MS,
    root: Path = ROOT,
) -> list[CheckResult]:
    checks: list[CheckResult] = []
    preflight_payload = check_portable_package_preflight.result_payload(spec.preflight(artifact))
    checks.append(
        check(
            f"{spec.label} artifact preflight passes",
            preflight_payload["ok"],
            ", ".join(preflight_payload["failed"]) or "portable package preflight passed",
        )
    )
    if not preflight_payload["ok"]:
        return checks

    with tempfile.TemporaryDirectory(prefix="culvia-portable-runtime-") as tmp:
        package_root, extract_issues = spec.extract(artifact, Path(tmp))
        checks.append(
            check(
                f"{spec.label} archive extracts safely",
                package_root is not None and not extract_issues,
                "; ".join(extract_issues) or f"extracted to {package_root}",
            )
        )
        if package_root is None or extract_issues:
            return checks

        manifest, manifest_error = read_manifest(package_root)
        checks.append(
            check(
                f"{spec.label} manifest loads after extraction",
                manifest is not None,
                manifest_error or "manifest JSON object",
            )
        )
        if manifest is None:
            return checks

        paths, path_issues = runtime_paths(package_root, manifest)
        checks.append(
            check(
                f"{spec.label} manifest runtime paths resolve",
                not path_issues,
                "; ".join(path_issues) or "launcher, backend, and web entry exist in extracted package",
            )
        )
        if path_issues:
            return checks

        if not launch:
            return checks

        current = native_platform_key()
        checks.append(
            check(
                f"{spec.label} runs on native target platform",
                current == spec.native_platform,
                f"requires {spec.native_platform}, current platform is {platform.system() or 'unknown'}",
            )
        )
        if current != spec.native_platform:
            return checks

        target = str(manifest.get("target") or "")
        arch_ok = target_matches_host_arch(target)
        checks.append(
            check(
                f"{spec.label} package target matches host architecture",
                arch_ok,
                f"target={target or 'missing'}, host={native_arch_key()}",
            )
        )
        if not arch_ok:
            return checks

        ok, detail = run_launcher_workflow_smoke(
            package_root=package_root,
            launcher=paths["launcher"],
            spec=spec,
            timeout=timeout,
            exit_after_ms=exit_after_ms,
        )
        checks.append(check(f"{spec.label} launcher runs desktop fixture workflow", ok, detail))
    return checks


def collect_checks(
    *,
    windows_zip: Path | None = None,
    linux_tgz: Path | None = None,
    launch: bool = True,
    timeout: int = 90,
    exit_after_ms: int = DEFAULT_EXIT_AFTER_MS,
    root: Path = ROOT,
) -> list[CheckResult]:
    checks: list[CheckResult] = []
    if windows_zip is not None:
        checks.extend(
            collect_runtime_checks(
                artifact=windows_zip,
                spec=WINDOWS_SPEC,
                launch=launch,
                timeout=timeout,
                exit_after_ms=exit_after_ms,
                root=root,
            )
        )
    if linux_tgz is not None:
        checks.extend(
            collect_runtime_checks(
                artifact=linux_tgz,
                spec=LINUX_SPEC,
                launch=launch,
                timeout=timeout,
                exit_after_ms=exit_after_ms,
                root=root,
            )
        )
    if windows_zip is None and linux_tgz is None:
        checks.append(check("portable package runtime artifact selected", False, "pass --windows-zip or --linux-tgz"))
    return checks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract built portable desktop packages and verify the bundled runtime."
    )
    parser.add_argument("--windows-zip", type=Path, default=None, help="Path to a built Windows portable zip artifact.")
    parser.add_argument("--linux-tgz", type=Path, default=None, help="Path to a built Linux tar.gz artifact.")
    parser.add_argument("--timeout", type=int, default=90, help="Packaged launcher smoke timeout in seconds.")
    parser.add_argument(
        "--exit-after-ms",
        type=int,
        default=DEFAULT_EXIT_AFTER_MS,
        help="Milliseconds the desktop smoke app should remain alive after frontendReady.",
    )
    parser.add_argument(
        "--skip-launch",
        action="store_true",
        help="Only extract and validate manifest runtime paths; do not run the packaged launcher.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable results.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    checks = collect_checks(
        windows_zip=args.windows_zip,
        linux_tgz=args.linux_tgz,
        launch=not args.skip_launch,
        timeout=max(1, args.timeout),
        exit_after_ms=max(1, args.exit_after_ms),
    )
    payload = result_payload(checks)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for item in checks:
            print(("OK" if item.ok else "FAIL") + f" {item.name}: {item.detail}")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
