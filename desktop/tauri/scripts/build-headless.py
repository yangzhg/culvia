from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


TAURI_DIR = Path(__file__).resolve().parents[1]


def tauri_command() -> list[str]:
    executable = "tauri.cmd" if os.name == "nt" else "tauri"
    local = TAURI_DIR / "node_modules" / ".bin" / executable
    if local.exists():
        return [str(local)]
    resolved = shutil.which("tauri")
    return [resolved or executable]


def main(argv: list[str]) -> int:
    env = os.environ.copy()
    env["CI"] = "true"
    return subprocess.run([*tauri_command(), "build", *argv], env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
