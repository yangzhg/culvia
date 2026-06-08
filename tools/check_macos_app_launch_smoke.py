from __future__ import annotations

import argparse
import json
import os
import plistlib
import queue
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import check_macos_artifact_preflight, check_backend_workflow_smoke, prepare_runtime_fixture


DEFAULT_BUNDLE_DIR = ROOT / "desktop" / "tauri" / "src-tauri" / "target" / "release" / "bundle"
REQUIRED_EVENTS = ("backendReady", "windowCreated", "frontendReady")
DEFAULT_EXIT_AFTER_MS = 8000

JsonRequester = Callable[[str, str, Any | None, float], Any]
BytesRequester = Callable[[str, float], bytes]


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def check(name: str, ok: bool, detail: str) -> CheckResult:
    return CheckResult(name=name, ok=bool(ok), detail=detail)


def result_payload(
    checks: Sequence[CheckResult],
    *,
    app: Path | None = None,
    executable: Path | None = None,
    command: Sequence[str] = (),
    events: Sequence[dict[str, Any]] = (),
    returncode: int | None = None,
    seconds: float | None = None,
    stdout_tail: Sequence[str] = (),
    stderr_tail: Sequence[str] = (),
) -> dict[str, Any]:
    failed = [item.name for item in checks if not item.ok]
    payload: dict[str, Any] = {
        "ok": not failed,
        "failed": failed,
        "checks": [{"name": item.name, "ok": item.ok, "detail": item.detail} for item in checks],
        "events": list(events),
    }
    if app is not None:
        payload["app"] = str(app)
    if executable is not None:
        payload["executable"] = str(executable)
    if command:
        payload["command"] = list(command)
    if returncode is not None:
        payload["returncode"] = returncode
    if seconds is not None:
        payload["seconds"] = round(seconds, 3)
    if stdout_tail:
        payload["stdoutTail"] = list(stdout_tail)
    if stderr_tail:
        payload["stderrTail"] = list(stderr_tail)
    return payload


def parse_smoke_event(line: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(line.strip())
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict) and payload.get("event") in REQUIRED_EVENTS:
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


def resolve_app_path(bundle_dir: Path, app: Path | None = None) -> tuple[Path | None, str]:
    discovery = check_macos_artifact_preflight.resolve_app_path(bundle_dir, app)
    if discovery.path is not None:
        return discovery.path, ""
    if discovery.issue is not None:
        return None, discovery.issue.detail
    return None, f"No .app found under {bundle_dir}"


def read_info_plist(app: Path) -> dict[str, Any]:
    with (app / "Contents" / "Info.plist").open("rb") as handle:
        payload = plistlib.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Info.plist must contain a dictionary")
    return payload


def app_executable(app: Path) -> tuple[Path | None, str]:
    try:
        info = read_info_plist(app)
    except Exception as exc:  # noqa: BLE001 - smoke tool returns the exact plist failure.
        return None, f"cannot read Info.plist: {exc}"
    executable_name = str(info.get("CFBundleExecutable") or "").strip()
    if not executable_name:
        return None, "Info.plist is missing CFBundleExecutable"
    executable = app / "Contents" / "MacOS" / executable_name
    if not executable.is_file():
        return None, f"missing app executable: {executable}"
    if not os.access(executable, os.X_OK):
        return None, f"app executable is not executable: {executable}"
    return executable, ""


def build_fixture(args: argparse.Namespace) -> tuple[dict[str, Any], tempfile.TemporaryDirectory[str] | None]:
    if args.fixture_root is not None:
        return prepare_runtime_fixture.write_fixture(
            args.fixture_root, count=max(1, args.count), force=args.force_fixture
        ), None
    temp = tempfile.TemporaryDirectory(prefix="culvia-macos-app-smoke-")
    return prepare_runtime_fixture.write_fixture(Path(temp.name), count=max(1, args.count), force=False), temp


def launch_environment(
    fixture: dict[str, Any],
    *,
    exit_after_ms: int,
    ready_timeout_secs: int | None = None,
) -> dict[str, str]:
    env = check_backend_workflow_smoke.workflow_environment(fixture)
    env["CULVIA_DESKTOP_FORCE_BACKEND"] = "1"
    env["CULVIA_DESKTOP_SMOKE"] = "1"
    env["CULVIA_DESKTOP_SMOKE_EXIT_AFTER_MS"] = str(max(1, exit_after_ms))
    if ready_timeout_secs is not None:
        env["CULVIA_DESKTOP_READY_TIMEOUT_SECS"] = str(max(1, ready_timeout_secs))
        env["CULVIA_DESKTOP_BACKEND_HEALTH_TIMEOUT_SECS"] = str(max(1, ready_timeout_secs))
        env["CULVIA_DESKTOP_FRONTEND_READY_TIMEOUT_SECS"] = str(max(1, ready_timeout_secs))
    return env


def wait_for_required_events(
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
        event = parse_smoke_event(line)
        if event is None:
            continue
        seen[str(event["event"])] = event
        if all(name in seen for name in REQUIRED_EVENTS):
            return [seen[name] for name in REQUIRED_EVENTS]
    return [seen[name] for name in REQUIRED_EVENTS if name in seen]


def base_url_from_events(events: Sequence[dict[str, Any]]) -> str:
    for event in events:
        if event.get("event") == "backendReady":
            base_url = str(event.get("baseUrl") or "").strip()
            if base_url:
                return base_url
    return ""


def collect_app_runtime_checks(
    *,
    base_url: str,
    fixture: dict[str, Any],
    timeout: float,
    json_requester: JsonRequester | None = None,
    bytes_requester: BytesRequester | None = None,
) -> list[CheckResult]:
    export_dir = Path(str(fixture["root"])) / "app-exported"
    checks = check_backend_workflow_smoke.collect_workflow_checks(
        base_url=base_url,
        fixture=fixture,
        export_dir=export_dir,
        timeout=timeout,
        json_requester=json_requester,
        bytes_requester=bytes_requester,
    )
    return [check(item.name.replace("backend workflow", "macos app runtime"), item.ok, item.detail) for item in checks]


def terminate_process(process: subprocess.Popen[str]) -> int | None:
    if process.poll() is not None:
        return process.returncode
    process.terminate()
    try:
        return process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.wait(timeout=5)


def run_app_smoke(
    *,
    app: Path,
    executable: Path,
    fixture: dict[str, Any],
    timeout: float,
    exit_after_ms: int,
) -> dict[str, Any]:
    started = time.monotonic()
    command = [str(executable)]
    stdout_tail: deque[str] = deque(maxlen=80)
    stderr_tail: deque[str] = deque(maxlen=80)
    checks: list[CheckResult] = []
    events: list[dict[str, Any]] = []
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=launch_environment(
                fixture,
                exit_after_ms=exit_after_ms,
                ready_timeout_secs=int(timeout),
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        events = wait_for_required_events(process, timeout=timeout, stdout_tail=stdout_tail, stderr_tail=stderr_tail)
        event_names = [str(event.get("event")) for event in events]
        events_ok = event_names == list(REQUIRED_EVENTS)
        checks.append(
            check(
                "macos app emits backend, window, and frontend ready smoke events",
                events_ok,
                f"events={event_names}",
            )
        )
        if events_ok:
            base_url = base_url_from_events(events)
            if base_url:
                checks.extend(
                    collect_app_runtime_checks(
                        base_url=base_url,
                        fixture=fixture,
                        timeout=min(15.0, max(3.0, timeout / 6.0)),
                    )
                )
            else:
                checks.append(check("macos app runtime exposes backend base url", False, f"events={event_names}"))
        try:
            returncode = process.wait(timeout=max(2.0, exit_after_ms / 1000.0 + 5.0))
        except subprocess.TimeoutExpired:
            returncode = terminate_process(process)
            checks.append(
                check(
                    "macos app exits after smoke frontend readiness",
                    False,
                    f"terminated app after timeout, returncode={returncode}",
                )
            )
        else:
            checks.append(
                check(
                    "macos app exits after smoke frontend readiness",
                    returncode == 0,
                    f"returncode={returncode}",
                )
            )
    except Exception as exc:  # noqa: BLE001 - release smoke reports exact launch failure.
        checks.append(check("macos app launch command starts", False, repr(exc)))
        returncode = terminate_process(process) if process is not None else None
    return result_payload(
        checks,
        app=app,
        executable=executable,
        command=command,
        events=events,
        returncode=returncode,
        seconds=time.monotonic() - started,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch a built macOS desktop .app and verify backend/window smoke events."
    )
    parser.add_argument("--bundle-dir", type=Path, default=DEFAULT_BUNDLE_DIR)
    parser.add_argument("--app", type=Path, default=None, help="Path to a built .app bundle.")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--exit-after-ms", type=int, default=DEFAULT_EXIT_AFTER_MS)
    parser.add_argument("--fixture-root", type=Path, default=None)
    parser.add_argument(
        "--force-fixture", action="store_true", help="Replace --fixture-root when it contains a fixture marker."
    )
    parser.add_argument("--count", type=int, default=4)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    app, app_error = resolve_app_path(args.bundle_dir, args.app)
    checks: list[CheckResult] = []
    if app is None:
        checks.append(check("macos app bundle exists", False, app_error))
        payload = result_payload(checks)
    else:
        executable, executable_error = app_executable(app)
        if executable is None:
            checks.append(check("macos app executable exists", False, executable_error))
            payload = result_payload(checks, app=app)
        else:
            fixture, cleanup = build_fixture(args)
            try:
                payload = run_app_smoke(
                    app=app,
                    executable=executable,
                    fixture=fixture,
                    timeout=max(1.0, args.timeout),
                    exit_after_ms=max(1, args.exit_after_ms),
                )
            finally:
                if cleanup is not None:
                    cleanup.cleanup()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("OK macOS app launch smoke" if payload["ok"] else "FAIL macOS app launch smoke")
        for item in payload["checks"]:
            print(("OK" if item["ok"] else "FAIL") + f" {item['name']}: {item['detail']}")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
