from __future__ import annotations

import argparse
import os
import threading
from dataclasses import dataclass
from typing import Sequence

from culvia.supervisor import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    ServerTarget,
    build_runtime_env,
    find_available_port,
    print_ready_event,
    wait_until_healthy,
)


@dataclass(frozen=True)
class ServerConfig:
    target: ServerTarget
    print_json: bool = False
    health_timeout: float = 20.0
    log_level: str = "info"
    reload: bool = False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Culvia local backend server.")
    parser.add_argument("--host", default=os.environ.get("CULVIA_HOST", DEFAULT_HOST))
    parser.add_argument(
        "--port",
        default=os.environ.get("CULVIA_PORT", str(DEFAULT_PORT)),
        help="Port number, or auto to choose an available port.",
    )
    parser.add_argument(
        "--no-open", action="store_true", help="Accepted for packaged desktop startup; no browser is opened."
    )
    parser.add_argument("--print-json", action="store_true", help="Print ready event as JSON after health check.")
    parser.add_argument("--health-timeout", type=float, default=20.0)
    parser.add_argument("--log-level", default=os.environ.get("CULVIA_LOG_LEVEL", "info"))
    parser.add_argument("--reload", action="store_true")
    return parser


def parse_args(argv: Sequence[str] | None = None) -> ServerConfig:
    args = build_parser().parse_args(argv)
    port = find_available_port(args.host, DEFAULT_PORT) if str(args.port).lower() == "auto" else int(args.port)
    return ServerConfig(
        target=ServerTarget(args.host, port),
        print_json=bool(args.print_json),
        health_timeout=max(1.0, args.health_timeout),
        log_level=str(args.log_level or "info"),
        reload=bool(args.reload),
    )


def apply_runtime_env() -> None:
    os.environ.update(build_runtime_env())


def run_server(config: ServerConfig) -> int:
    apply_runtime_env()

    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(
            "culvia_app:app",
            host=config.target.host,
            port=config.target.port,
            log_level=config.log_level,
            reload=config.reload,
        )
    )
    thread = threading.Thread(target=server.run, name="culvia-server", daemon=True)
    thread.start()

    if not wait_until_healthy(config.target, config.health_timeout):
        server.should_exit = True
        thread.join(timeout=5)
        return 1

    print_ready_event(config.target, as_json=config.print_json)
    try:
        while thread.is_alive():
            thread.join(timeout=0.5)
    except KeyboardInterrupt:
        server.should_exit = True
        while thread.is_alive():
            thread.join(timeout=0.5)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return run_server(parse_args(argv))
