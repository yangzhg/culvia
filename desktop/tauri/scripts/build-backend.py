from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[3]
DESKTOP_SHELL_DIR = ROOT / "desktop" / "tauri"
ENTRY_PATH = DESKTOP_SHELL_DIR / "backend" / "server_entry.py"
RUNTIME_DIR = DESKTOP_SHELL_DIR / "src-tauri" / "runtime"
BACKEND_RUNTIME_ROOT = RUNTIME_DIR / "backend"
MACOS_ENTITLEMENTS_PATH = DESKTOP_SHELL_DIR / "src-tauri" / "entitlements.mac.plist"
BACKEND_NAME = "culvia-server"
BACKEND_RESOURCE_ROOT = "runtime/backend"
MACOS_CODESIGN_IDENTITY_ENV = "CULVIA_MACOS_BACKEND_CODESIGN_IDENTITY"


def rust_host_triple() -> str:
    try:
        result = subprocess.run(["rustc", "-vV"], text=True, capture_output=True, check=False)
    except FileNotFoundError:
        result = None
    if result is not None and result.returncode == 0:
        for line in result.stdout.splitlines():
            if line.startswith("host:"):
                return line.split(":", 1)[1].strip()
    machine = platform.machine().lower()
    system = platform.system().lower()
    if system == "darwin":
        return "aarch64-apple-darwin" if machine in {"arm64", "aarch64"} else "x86_64-apple-darwin"
    if system == "windows":
        return "x86_64-pc-windows-msvc"
    if system == "linux":
        return "aarch64-unknown-linux-gnu" if machine in {"arm64", "aarch64"} else "x86_64-unknown-linux-gnu"
    raise RuntimeError(f"Unsupported backend build platform: {platform.system()} {platform.machine()}")


def backend_binary_name(target: str, *, os_name: str | None = None) -> str:
    system = (os_name or platform.system()).lower()
    suffix = ".exe" if system.startswith("win") or "windows" in target else ""
    return f"{BACKEND_NAME}{suffix}"


def pyinstaller_name(target: str) -> str:
    return BACKEND_NAME


def backend_target_root(target: str) -> Path:
    return BACKEND_RUNTIME_ROOT / target


def backend_runtime_dir(target: str) -> Path:
    return backend_target_root(target) / BACKEND_NAME


def backend_binary_path(target: str) -> Path:
    return backend_runtime_dir(target) / backend_binary_name(target)


def backend_resource_path(target: str) -> str:
    return f"{BACKEND_RESOURCE_ROOT}/{target}/{BACKEND_NAME}"


def target_is_macos(target: str) -> bool:
    return "apple-darwin" in target


def resolve_macos_codesign_identity(
    *,
    target: str,
    explicit: str | None = None,
    env: dict[str, str] | None = None,
) -> str | None:
    if not target_is_macos(target):
        return None
    if explicit is not None:
        return explicit.strip() or None
    env_value = (env or os.environ).get(MACOS_CODESIGN_IDENTITY_ENV, "").strip()
    return env_value or "-"


def add_data_separator() -> str:
    return ";" if platform.system().lower().startswith("win") else ":"


def pyinstaller_command(
    *,
    python: Path,
    target: str,
    workpath: Path,
    specpath: Path,
    codesign_identity: str | None = None,
    entitlements_path: Path | None = None,
) -> list[str]:
    data_arg = f"{ROOT / 'web'}{add_data_separator()}share/culvia/web"
    command = [
        str(python),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        pyinstaller_name(target),
        "--distpath",
        str(backend_target_root(target)),
        "--workpath",
        str(workpath),
        "--specpath",
        str(specpath),
        "--add-data",
        data_arg,
        "--hidden-import",
        "culvia_app",
        "--collect-submodules",
        "culvia",
    ]
    if codesign_identity:
        command.extend(["--codesign-identity", codesign_identity])
    if entitlements_path is not None:
        command.extend(["--osx-entitlements-file", str(entitlements_path)])
    command.append(str(ENTRY_PATH))
    return command


def plan_payload(
    *,
    python: Path,
    target: str,
    workpath: Path,
    specpath: Path,
    codesign_identity: str | None = None,
) -> dict:
    entitlements_path = MACOS_ENTITLEMENTS_PATH if target_is_macos(target) else None
    return {
        "backendName": BACKEND_NAME,
        "desktopResourceRoot": BACKEND_RESOURCE_ROOT,
        "desktopResourcePath": backend_resource_path(target),
        "target": target,
        "binaryName": backend_binary_name(target),
        "binaryPath": str(backend_binary_path(target)),
        "runtimeDir": str(backend_runtime_dir(target)),
        "entry": str(ENTRY_PATH),
        "webDataSource": str(ROOT / "web"),
        "webDataDestination": "share/culvia/web",
        "macosCodesignIdentity": codesign_identity,
        "macosEntitlements": str(entitlements_path) if entitlements_path else None,
        "command": pyinstaller_command(
            python=python,
            target=target,
            workpath=workpath,
            specpath=specpath,
            codesign_identity=codesign_identity,
            entitlements_path=entitlements_path,
        ),
    }


def ensure_placeholder(payload: dict) -> str:
    binary_path = Path(str(payload["binaryPath"]))
    if binary_path.exists():
        return "existing"
    binary_path.parent.mkdir(parents=True, exist_ok=True)
    binary_path.write_text(
        "\n".join(
            (
                "#!/bin/sh",
                'echo "Culvia backend placeholder. Run python3 desktop/tauri/scripts/build-backend.py --build before packaging." >&2',
                "exit 1",
                "",
            )
        ),
        encoding="utf-8",
    )
    binary_path.chmod(0o755)
    return "created"


def validate_plan() -> list[str]:
    issues: list[str] = []
    for path, label in (
        (ENTRY_PATH, "backend entry"),
        (ROOT / "culvia" / "server.py", "Python backend module"),
        (ROOT / "web" / "index.html", "web index"),
        (DESKTOP_SHELL_DIR / "src-tauri" / "tauri.conf.json", "desktop shell config"),
        (MACOS_ENTITLEMENTS_PATH, "macOS entitlements"),
        (DESKTOP_SHELL_DIR / "desktop-shell.contract.json", "desktop shell contract"),
    ):
        if not path.exists():
            issues.append(f"missing {label}: {path}")

    tauri_config_path = DESKTOP_SHELL_DIR / "src-tauri" / "tauri.conf.json"
    if tauri_config_path.exists():
        tauri_config = tauri_config_path.read_text(encoding="utf-8")
        if BACKEND_RESOURCE_ROOT not in tauri_config:
            issues.append(f"desktop shell config must include bundle.resources {BACKEND_RESOURCE_ROOT!r}")
    contract_path = DESKTOP_SHELL_DIR / "desktop-shell.contract.json"
    if contract_path.exists():
        contract = contract_path.read_text(encoding="utf-8")
        for text in (BACKEND_NAME, "build-backend.py", BACKEND_RESOURCE_ROOT):
            if text not in contract:
                issues.append(f"desktop shell contract missing {text!r}")
    return issues


def progress(message: str) -> None:
    print(f"[backend-build] {message}", file=sys.stderr, flush=True)


def command_preview(command: Sequence[str]) -> str:
    return " ".join(str(part) for part in command)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or validate the Culvia desktop backend.")
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--target", default=None, help="Rust target triple. Defaults to rustc -vV host.")
    parser.add_argument("--workpath", type=Path, default=Path(tempfile.gettempdir()) / "culvia-server-build")
    parser.add_argument("--specpath", type=Path, default=Path(tempfile.gettempdir()) / "culvia-server-spec")
    parser.add_argument(
        "--codesign-identity",
        default=None,
        help=f"macOS PyInstaller signing identity for collected binaries. Defaults to ${MACOS_CODESIGN_IDENTITY_ENV} or '-' on macOS targets.",
    )
    parser.add_argument("--check-plan", action="store_true", help="Validate static backend build plan and exit.")
    parser.add_argument(
        "--ensure-placeholder",
        action="store_true",
        help="Create an ignored backend placeholder so desktop cargo checks can validate config before PyInstaller build.",
    )
    parser.add_argument(
        "--build", action="store_true", help="Run PyInstaller and create the current-platform backend binary."
    )
    parser.add_argument("--json", action="store_true", help="Print JSON plan or result.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target = args.target or rust_host_triple()
    codesign_identity = resolve_macos_codesign_identity(target=target, explicit=args.codesign_identity)
    payload = plan_payload(
        python=args.python,
        target=target,
        workpath=args.workpath,
        specpath=args.specpath,
        codesign_identity=codesign_identity,
    )
    issues = validate_plan()

    if args.ensure_placeholder:
        payload["ok"] = not issues
        payload["issues"] = issues
        if issues:
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                for issue in issues:
                    print(f"FAIL {issue}")
            return 1
        payload["placeholder"] = ensure_placeholder(payload)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"OK backend placeholder {payload['placeholder']}: {payload['binaryPath']}")
        return 0

    if args.check_plan or not args.build:
        payload["ok"] = not issues
        payload["issues"] = issues
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(("OK" if not issues else "FAIL") + f" backend plan: {payload['binaryPath']}")
            for issue in issues:
                print(f"FAIL {issue}")
        return 0 if not issues else 1

    progress("1/4 validate build plan")
    if issues:
        for issue in issues:
            print(f"FAIL {issue}")
        return 1
    runtime_dir = Path(str(payload["runtimeDir"]))
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir)
    progress(f"2/4 prepare PyInstaller backend for {payload['target']}")
    progress(f"binary: {payload['binaryPath']}")
    progress(f"runtime dir: {payload['runtimeDir']}")
    progress(f"web data: {payload['webDataSource']} -> {payload['webDataDestination']}")
    if payload.get("macosCodesignIdentity"):
        progress(f"macOS codesign identity: {payload['macosCodesignIdentity']}")
    progress(f"workpath: {args.workpath}")
    progress(f"specpath: {args.specpath}")
    progress("3/4 run PyInstaller; live output follows")
    progress(f"command: {command_preview(payload['command'])}")
    started = time.monotonic()
    result = subprocess.run(payload["command"], cwd=ROOT, text=True, check=False)
    binary_path = Path(payload["binaryPath"])
    if result.returncode != 0 or not binary_path.exists():
        progress(f"FAIL PyInstaller backend build after {round(time.monotonic() - started, 1)}s")
        print(f"FAIL backend build did not produce {binary_path}")
        return result.returncode or 1
    progress(f"4/4 verify output binary ({round(time.monotonic() - started, 1)}s)")
    progress(f"OK build {payload['binaryName']} in {payload['runtimeDir']} ({binary_path.stat().st_size} bytes)")
    if args.json:
        payload["ok"] = True
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"OK backend build: {binary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
