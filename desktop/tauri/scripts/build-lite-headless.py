from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


TAURI_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = TAURI_DIR / "src-tauri" / "tauri.conf.json"
GENERATED_CONFIG_DIR = TAURI_DIR / "src-tauri"


def tauri_command() -> list[str]:
    executable = "tauri.cmd" if os.name == "nt" else "tauri"
    local = TAURI_DIR / "node_modules" / ".bin" / executable
    if local.exists():
        return [str(local)]
    resolved = shutil.which("tauri")
    return [resolved or executable]


def strip_backend_resource(resources: Any) -> Any:
    if isinstance(resources, dict):
        return {
            key: value for key, value in resources.items() if key != "runtime/backend" and value != "runtime/backend"
        }
    if isinstance(resources, list):
        return [item for item in resources if item != "runtime/backend"]
    return resources


def lite_config_payload() -> dict[str, Any]:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    bundle = payload.get("bundle")
    if isinstance(bundle, dict):
        resources = strip_backend_resource(bundle.get("resources"))
        if resources:
            bundle["resources"] = resources
        else:
            bundle.pop("resources", None)
    return payload


def main(argv: list[str]) -> int:
    env = os.environ.copy()
    env["CI"] = "true"
    env["CULVIA_DESKTOP_DEFAULT_RUNTIME_MODE"] = "lite"
    generated = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        prefix="tauri.lite.",
        suffix=".generated.conf.json",
        dir=GENERATED_CONFIG_DIR,
        delete=False,
    )
    generated_config_path = Path(generated.name)
    with generated:
        generated.write(json.dumps(lite_config_payload(), ensure_ascii=False, indent=2) + "\n")
    try:
        command = [*tauri_command(), "build", "--config", str(generated_config_path), *argv]
        return subprocess.run(command, cwd=TAURI_DIR, env=env, check=False).returncode
    finally:
        generated_config_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
