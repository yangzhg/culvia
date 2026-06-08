from __future__ import annotations

import argparse
import importlib.util
import json
import queue
import subprocess
import sys
import threading
import time
import urllib.request
from collections import deque
from pathlib import Path
from typing import Sequence
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
BACKEND_BUILD_SCRIPT = ROOT / "desktop" / "tauri" / "scripts" / "build-backend.py"
HEALTH_PATH = "/health"


def load_backend_build_tool():
    spec = importlib.util.spec_from_file_location("culvia_backend_build", BACKEND_BUILD_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {BACKEND_BUILD_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def default_binary_path() -> Path:
    tool = load_backend_build_tool()
    target = tool.rust_host_triple()
    return tool.backend_binary_path(target)


def parse_ready_event(line: str) -> dict | None:
    try:
        payload = json.loads(line.strip())
    except json.JSONDecodeError:
        return None
    if (
        isinstance(payload, dict)
        and payload.get("event") == "ready"
        and isinstance(payload.get("baseUrl"), str)
        and isinstance(payload.get("healthUrl"), str)
        and ready_urls_are_local(payload["baseUrl"], payload["healthUrl"])
    ):
        return payload
    return None


def local_http_socket(url: str) -> tuple[str, int, str] | None:
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        return None
    if parsed.port is None:
        return None
    return parsed.hostname, int(parsed.port), parsed.path


def ready_urls_are_local(base_url: str, health_url: str) -> bool:
    base = local_http_socket(base_url)
    health = local_http_socket(health_url)
    return base is not None and health is not None and base[:2] == health[:2] and health[2] == HEALTH_PATH


def command_for_args(args: argparse.Namespace) -> tuple[str, list[str]]:
    if args.source:
        return "source", [
            str(args.python),
            "-m",
            "culvia.server",
            "--host",
            "127.0.0.1",
            "--port",
            "auto",
            "--no-open",
            "--print-json",
            "--health-timeout",
            str(max(1.0, args.timeout)),
        ]
    binary = args.binary or default_binary_path()
    return "binary", [
        str(binary),
        "--host",
        "127.0.0.1",
        "--port",
        "auto",
        "--no-open",
        "--print-json",
        "--health-timeout",
        str(max(1.0, args.timeout)),
    ]


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


def wait_for_ready(
    process: subprocess.Popen[str],
    timeout: float,
    *,
    stdout_tail: deque[str],
    stderr_tail: deque[str],
) -> dict:
    stdout_lines: queue.Queue[str] = queue.Queue()
    assert process.stdout is not None
    assert process.stderr is not None
    stdout_thread = threading.Thread(target=drain_lines, args=(process.stdout, stdout_lines, stdout_tail), daemon=True)
    stderr_thread = threading.Thread(target=drain_lines, args=(process.stderr, None, stderr_tail), daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"backend exited before ready event with code {process.returncode}")
        try:
            line = stdout_lines.get(timeout=0.25)
        except queue.Empty:
            continue
        ready = parse_ready_event(line)
        if ready is not None:
            return ready
    raise TimeoutError("timed out waiting for backend ready event")


def wait_for_health(health_url: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=1.5) as response:
                if response.status == 200:
                    return
                last_error = f"HTTP {response.status}"
        except Exception as exc:  # noqa: BLE001 - smoke tool reports the last failure verbatim.
            last_error = str(exc)
        time.sleep(0.25)
    raise TimeoutError(f"timed out waiting for backend health at {health_url}: {last_error}")


def terminate_process(process: subprocess.Popen[str]) -> int | None:
    if process.poll() is not None:
        return process.returncode
    process.terminate()
    try:
        return process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.wait(timeout=5)


def smoke(command: Sequence[str], *, timeout: float) -> dict:
    started = time.monotonic()
    stderr_tail: deque[str] = deque(maxlen=40)
    stdout_tail: deque[str] = deque(maxlen=40)
    try:
        process = subprocess.Popen(
            list(command),
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        return {
            "ok": False,
            "command": list(command),
            "ready": None,
            "returncode": None,
            "seconds": round(time.monotonic() - started, 3),
            "error": str(exc),
            "stdoutTail": [],
            "stderrTail": [],
        }
    ready: dict | None = None
    error = ""
    try:
        ready = wait_for_ready(process, timeout, stdout_tail=stdout_tail, stderr_tail=stderr_tail)
        wait_for_health(str(ready["healthUrl"]), timeout)
        ok = True
    except Exception as exc:  # noqa: BLE001 - smoke tool converts any failure to JSON.
        ok = False
        error = str(exc)
    finally:
        returncode = terminate_process(process)
    return {
        "ok": ok,
        "command": list(command),
        "ready": ready,
        "returncode": returncode,
        "seconds": round(time.monotonic() - started, 3),
        "error": error,
        "stdoutTail": list(stdout_tail),
        "stderrTail": list(stderr_tail),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke test the Culvia desktop backend.")
    parser.add_argument("--binary", type=Path, default=None, help="Backend binary to test. Defaults to current target.")
    parser.add_argument("--source", action="store_true", help="Run the source backend module instead of a binary.")
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    mode, command = command_for_args(args)
    payload = {"mode": mode, **smoke(command, timeout=max(1.0, args.timeout))}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        status = "OK" if payload["ok"] else "FAIL"
        print(f"{status} backend smoke ({mode})")
        if not payload["ok"]:
            print(payload["error"])
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
