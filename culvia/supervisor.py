from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from culvia.settings import user_cache_dir, user_data_dir


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8501
HEALTH_PATH = "/health"
STATE_DIR_ENV = "CULVIA_STATE_DIR"


@dataclass(frozen=True)
class ServerTarget:
    host: str
    port: int

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def health_url(self) -> str:
        return f"{self.base_url}{HEALTH_PATH}"


@dataclass(frozen=True)
class SupervisorConfig:
    target: ServerTarget
    open_browser: bool = True
    print_json: bool = False
    max_restarts: int = 3
    restart_delay: float = 1.5
    health_timeout: float = 20.0
    reload: bool = False


def find_available_port(host: str, preferred_port: int = DEFAULT_PORT) -> int:
    if preferred_port > 0 and _port_is_free(host, preferred_port):
        return preferred_port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def build_server_command(target: ServerTarget, reload: bool = False) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "culvia_app:app",
        "--host",
        target.host,
        "--port",
        str(target.port),
    ]
    if reload:
        command.append("--reload")
    return command


def ready_event_payload(target: ServerTarget) -> dict[str, str | int]:
    return {
        "event": "ready",
        "baseUrl": target.base_url,
        "healthUrl": target.health_url,
        "host": target.host,
        "port": target.port,
    }


def print_ready_event(target: ServerTarget, *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(ready_event_payload(target), ensure_ascii=False), flush=True)
    else:
        print(f"Culvia 已启动：{target.base_url}", flush=True)


def runtime_state_dir(base_env: Mapping[str, str] | None = None) -> Path:
    env = base_env or os.environ
    if env.get(STATE_DIR_ENV):
        return Path(env[STATE_DIR_ENV]).expanduser()
    if env.get("CULVIA_DATA_DIR"):
        return Path(env["CULVIA_DATA_DIR"]).expanduser()
    return user_data_dir()


def build_runtime_env(base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(base_env or os.environ)
    cache_dir = Path(env["CULVIA_CACHE_DIR"]).expanduser() if env.get("CULVIA_CACHE_DIR") else user_cache_dir()
    data_dir = runtime_state_dir(env)
    env.setdefault("CULVIA_DATA_DIR", str(cache_dir))
    env.setdefault("CULVIA_CACHE_PATH", str(data_dir / "culvia_scores.sqlite"))
    env.setdefault("CULVIA_THUMBNAIL_CACHE_DIR", str(cache_dir / "thumbnails"))
    env.setdefault("CULVIA_UPLOAD_DIR", str(cache_dir / "uploads"))
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def runtime_log_path(base_env: Mapping[str, str] | None = None) -> Path:
    return runtime_state_dir(base_env) / "logs" / "supervisor.log"


def append_log(message: str, log_path: Path | None = None) -> None:
    path = log_path or runtime_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] {message}\n")


def is_healthy(target: ServerTarget, timeout: float = 1.5) -> bool:
    try:
        request = urllib.request.Request(target.health_url, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= int(response.status) < 300
    except (OSError, urllib.error.URLError, urllib.error.HTTPError):
        return False


def wait_until_healthy(target: ServerTarget, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_healthy(target):
            return True
        time.sleep(0.25)
    return is_healthy(target)


def run_supervisor(config: SupervisorConfig) -> int:
    restarts = 0
    opened = False
    command = build_server_command(config.target, reload=config.reload)
    env = build_runtime_env()
    log_path = runtime_log_path(env)

    append_log(f"启动服务：{config.target.base_url}", log_path)
    append_log(f"运行数据：{env.get('CULVIA_CACHE_PATH', '')}", log_path)

    while True:
        process = subprocess.Popen(command, env=env)
        append_log(f"服务进程已启动 pid={process.pid}", log_path)

        if wait_until_healthy(config.target, config.health_timeout):
            append_log(f"健康检查通过：{config.target.health_url}", log_path)
            print_ready_event(config.target, as_json=config.print_json)
            if config.open_browser and not opened:
                webbrowser.open(config.target.base_url)
                opened = True
        else:
            append_log(f"健康检查超时：{config.target.health_url}", log_path)

        return_code = process.wait()
        append_log(f"服务进程退出 pid={process.pid} code={return_code}", log_path)

        if return_code == 0:
            return 0
        restarts += 1
        if restarts > config.max_restarts:
            append_log("达到最大重启次数，停止 supervisor", log_path)
            return return_code
        append_log(f"{config.restart_delay:.1f}s 后自动重启（第 {restarts} 次）", log_path)
        time.sleep(config.restart_delay)


def parse_args(argv: Sequence[str] | None = None) -> SupervisorConfig:
    parser = argparse.ArgumentParser(description="启动并监督Culvia 本地服务")
    parser.add_argument("--host", default=os.environ.get("CULVIA_HOST", DEFAULT_HOST))
    parser.add_argument(
        "--port",
        default=os.environ.get("CULVIA_PORT", str(DEFAULT_PORT)),
        help="端口号；auto 优先默认端口，random 选择任意可用端口",
    )
    parser.add_argument("--no-open", action="store_true", help="启动后不自动打开浏览器")
    parser.add_argument("--print-json", action="store_true", help="健康检查通过后输出机器可读的 ready JSON")
    parser.add_argument("--reload", action="store_true", help="开发模式：文件变化时自动重载服务")
    parser.add_argument("--max-restarts", type=int, default=3)
    parser.add_argument("--restart-delay", type=float, default=1.5)
    parser.add_argument("--health-timeout", type=float, default=20.0)
    args = parser.parse_args(argv)

    port_text = str(args.port).lower()
    if port_text == "auto":
        port = find_available_port(args.host, DEFAULT_PORT)
    elif port_text == "random":
        port = find_available_port(args.host, 0)
    else:
        port = int(args.port)
    return SupervisorConfig(
        target=ServerTarget(args.host, port),
        open_browser=not args.no_open,
        print_json=bool(args.print_json),
        max_restarts=max(0, args.max_restarts),
        restart_delay=max(0.1, args.restart_delay),
        health_timeout=max(1.0, args.health_timeout),
        reload=bool(args.reload),
    )


def main(argv: Sequence[str] | None = None) -> int:
    config = parse_args(argv)
    return run_supervisor(config)


if __name__ == "__main__":
    raise SystemExit(main())
