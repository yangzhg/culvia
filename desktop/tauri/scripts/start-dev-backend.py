from __future__ import annotations

import sys
import time
import socket
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from culvia.supervisor import ServerTarget, is_healthy, main, print_ready_event


DEV_TARGET = ServerTarget("127.0.0.1", 8501)


def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def wait_forever() -> int:
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    if is_healthy(DEV_TARGET):
        print_ready_event(DEV_TARGET, as_json=True)
        raise SystemExit(wait_forever())
    if not port_is_free(DEV_TARGET.host, DEV_TARGET.port):
        print(
            f"Port {DEV_TARGET.port} is already in use, but {DEV_TARGET.health_url} is not healthy. "
            "Stop the existing process or start Culvia with the current code before running Tauri dev.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    raise SystemExit(
        main(
            [
                "--host",
                "127.0.0.1",
                "--port",
                "8501",
                "--no-open",
                "--print-json",
            ]
        )
    )
