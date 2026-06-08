from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
DESKTOP_CONFIG_PATH = ROOT / "desktop" / "tauri" / "src-tauri" / "tauri.conf.json"
BACKEND_BUILD_SCRIPT = ROOT / "desktop" / "tauri" / "scripts" / "build-backend.py"
DEFAULT_TARGET = "x86_64-pc-windows-msvc"
PACKAGE_SLUG = "culvia"
WINDOWS_PACKAGE_KIND = "culvia-windows-zip"
WINDOWS_LITE_PACKAGE_KIND = "culvia-windows-lite-zip"
PACKAGE_DESKTOP_NAME = "culvia-desktop.exe"
PACKAGE_BACKEND_NAME = "culvia-server.exe"
PACKAGE_BACKEND_RUNTIME_ROOT = "runtime/backend"
PE_MACHINE_BY_TARGET = {
    "x86_64-pc-windows-msvc": 0x8664,
    "aarch64-pc-windows-msvc": 0xAA64,
}


def load_backend_build_tool() -> Any:
    spec = importlib.util.spec_from_file_location("culvia_build_backend", BACKEND_BUILD_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {BACKEND_BUILD_SCRIPT}.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_desktop_config(config_path: Path = DESKTOP_CONFIG_PATH) -> dict[str, Any]:
    return json.loads(config_path.read_text(encoding="utf-8"))


def product_version(config: dict[str, Any]) -> str:
    return str(config.get("version") or "0.1.0").strip() or "0.1.0"


def product_name(config: dict[str, Any]) -> str:
    return str(config.get("productName") or "Culvia").strip() or "Culvia"


def is_lite_profile(runtime_profile: str) -> bool:
    return runtime_profile.strip().lower() == "lite"


def package_dir_name(version: str, target: str, *, runtime_profile: str = "full") -> str:
    if is_lite_profile(runtime_profile):
        return f"{PACKAGE_SLUG}-{version}-windows-lite-{target}"
    return f"{PACKAGE_SLUG}-{version}-windows-{target}"


def archive_name(version: str, target: str, *, runtime_profile: str = "full") -> str:
    return f"{package_dir_name(version, target, runtime_profile=runtime_profile)}.zip"


def backend_binary_name(target: str) -> str:
    return str(load_backend_build_tool().backend_binary_name(target, os_name="Windows"))


def default_backend_binary(target: str, *, root: Path = ROOT) -> Path:
    tool = load_backend_build_tool()
    return tool.backend_binary_path(target)


def default_desktop_binary(target: str, *, root: Path = ROOT) -> Path:
    target_release = root / "desktop" / "tauri" / "src-tauri" / "target" / target / "release" / "culvia-desktop.exe"
    host_release = root / "desktop" / "tauri" / "src-tauri" / "target" / "release" / "culvia-desktop.exe"
    return target_release if target_release.exists() else host_release


def pe_machine(path: Path) -> int | None:
    with path.open("rb") as handle:
        header = handle.read(0x40)
        if len(header) < 0x40 or header[:2] != b"MZ":
            return None
        pe_offset = int.from_bytes(header[0x3C:0x40], "little")
        handle.seek(pe_offset)
        signature = handle.read(6)
    if len(signature) < 6 or signature[:4] != b"PE\0\0":
        return None
    return int.from_bytes(signature[4:6], "little")


def is_pe(path: Path) -> bool:
    return pe_machine(path) is not None


def validate_pe_executable(path: Path, *, label: str, target: str) -> list[str]:
    if not path.exists():
        return [f"missing {label}: {path}"]
    if not path.is_file():
        return [f"{label} is not a file: {path}"]
    issues: list[str] = []
    if path.suffix.lower() != ".exe":
        issues.append(f"{label} must use .exe suffix: {path}")
    machine = pe_machine(path)
    if machine is None:
        issues.append(f"{label} must be a Windows PE executable: {path}")
    expected_machine = PE_MACHINE_BY_TARGET.get(target)
    if machine is not None and expected_machine is not None and machine != expected_machine:
        issues.append(f"{label} machine must match {target}: expected 0x{expected_machine:04x}, got 0x{machine:04x}")
    return issues


def web_files(root: Path = ROOT) -> list[Path]:
    web_dir = root / "web"
    return sorted(path for path in web_dir.rglob("*") if path.is_file())


def validate_inputs(
    *,
    target: str,
    desktop_binary: Path,
    backend_binary: Path,
    root: Path = ROOT,
    runtime_profile: str = "full",
) -> list[str]:
    issues: list[str] = []
    web_dir = root / "web"
    if not is_lite_profile(runtime_profile) and (not web_dir.exists() or not (web_dir / "index.html").is_file()):
        issues.append(f"missing web assets: {web_dir}")
    if desktop_binary.name != "culvia-desktop.exe":
        issues.append(f"Windows desktop shell binary must be named culvia-desktop.exe: {desktop_binary}")
    issues.extend(validate_pe_executable(desktop_binary, label="Windows desktop shell binary", target=target))
    if not is_lite_profile(runtime_profile):
        expected_backend_name = backend_binary_name(target)
        if backend_binary.name != expected_backend_name:
            issues.append(f"Windows backend binary must be named {expected_backend_name}: {backend_binary}")
        issues.extend(validate_pe_executable(backend_binary, label="Windows backend binary", target=target))
        if backend_binary.parent.name != "culvia-server":
            issues.append(
                f"Windows backend binary must live inside a culvia-server runtime directory: {backend_binary}"
            )
    return issues


def backend_package_dir(target: str) -> Path:
    return Path(PACKAGE_BACKEND_RUNTIME_ROOT) / target / "culvia-server"


def backend_package_binary(target: str) -> Path:
    return backend_package_dir(target) / PACKAGE_BACKEND_NAME


def manifest_payload(
    *,
    version: str,
    target: str,
    source_desktop: Path,
    source_backend: Path | None,
    config: dict[str, Any],
    runtime_profile: str = "full",
) -> dict[str, Any]:
    if is_lite_profile(runtime_profile):
        return {
            "schemaVersion": 1,
            "kind": WINDOWS_LITE_PACKAGE_KIND,
            "runtimeProfile": "lite",
            "productName": product_name(config),
            "version": version,
            "target": target,
            "launcher": PACKAGE_DESKTOP_NAME,
            "desktop": {
                "sourceName": source_desktop.name,
                "path": PACKAGE_DESKTOP_NAME,
                "expectedFormat": "PE",
                "defaultRuntimeMode": "lite",
            },
            "backend": {
                "mode": "lite",
                "bundled": False,
                "mustNotRequireUserPython": False,
                "managedVenv": True,
                "config": "runtime.json",
            },
            "smoke": {
                "command": PACKAGE_DESKTOP_NAME,
                "runtime": (
                    "Desktop shell starts in Lite mode, creates or repairs an app-managed Python environment, "
                    "then opens the local Web UI."
                ),
                "healthPath": "/health",
            },
        }
    assert source_backend is not None
    return {
        "schemaVersion": 1,
        "kind": WINDOWS_PACKAGE_KIND,
        "productName": product_name(config),
        "version": version,
        "target": target,
        "launcher": PACKAGE_DESKTOP_NAME,
        "desktop": {
            "sourceName": source_desktop.name,
            "path": PACKAGE_DESKTOP_NAME,
            "expectedFormat": "PE",
        },
        "backend": {
            "sourceName": source_backend.name,
            "path": backend_package_binary(target).as_posix(),
            "runtimeDir": backend_package_dir(target).as_posix(),
            "mustNotRequireUserPython": True,
            "expectedFormat": "PE",
        },
        "web": {
            "path": "share/culvia/web",
            "entry": "share/culvia/web/index.html",
        },
        "smoke": {
            "command": PACKAGE_DESKTOP_NAME,
            "runtime": (
                "Desktop shell finds culvia-server.exe next to the executable, waits for /health, "
                "then creates the desktop window."
            ),
            "healthPath": "/health",
        },
    }


def readme_text(*, version: str, target: str, runtime_profile: str = "full") -> str:
    if is_lite_profile(runtime_profile):
        return "\n".join(
            (
                "# Culvia Windows Lite Package",
                "",
                f"Version: {version}",
                f"Target: {target}",
                "",
                "This archive contains the desktop shell only.",
                "On first launch, Culvia uses Python 3.11+ to create an app-managed virtualenv and install the runtime package.",
                "",
                "Run `culvia-desktop.exe` from the extracted folder.",
                "",
                "Lite runtime configuration is stored in the user's Culvia runtime directory as `runtime.json`.",
                "API keys, model caches, databases, and exported photos are not bundled into this archive.",
                "",
            )
        )
    return "\n".join(
        (
            "# Culvia Windows Package",
            "",
            f"Version: {version}",
            f"Target: {target}",
            "",
            "This archive is a self-contained desktop package.",
            "The bundled Python backend does not require a system Python installation.",
            "",
            "Run `culvia-desktop.exe` from the extracted folder.",
            "",
            "Keep the `runtime/backend` directory next to `culvia-desktop.exe`.",
            "Model weights are still managed as local cache data and are not bundled into this archive.",
            "",
        )
    )


def copy_web_assets(*, root: Path, destination: Path) -> None:
    shutil.copytree(root / "web", destination)


def stage_package(
    *,
    desktop_binary: Path,
    backend_binary: Path,
    target: str,
    output_dir: Path,
    root: Path = ROOT,
    config: dict[str, Any] | None = None,
    runtime_profile: str = "full",
) -> tuple[Path, dict[str, Any]]:
    config = read_desktop_config() if config is None else config
    version = product_version(config)
    package_root = output_dir / package_dir_name(version, target, runtime_profile=runtime_profile)
    if package_root.exists():
        shutil.rmtree(package_root)
    (package_root / "share" / "culvia").mkdir(parents=True)

    shutil.copy2(desktop_binary, package_root / PACKAGE_DESKTOP_NAME)
    if not is_lite_profile(runtime_profile):
        shutil.copytree(backend_binary.parent, package_root / backend_package_dir(target))
        copy_web_assets(root=root, destination=package_root / "share" / "culvia" / "web")

    manifest = manifest_payload(
        version=version,
        target=target,
        source_desktop=desktop_binary,
        source_backend=None if is_lite_profile(runtime_profile) else backend_binary,
        config=config,
        runtime_profile=runtime_profile,
    )
    (package_root / "share" / "culvia" / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (package_root / "README.md").write_text(
        readme_text(version=version, target=target, runtime_profile=runtime_profile), encoding="utf-8"
    )
    return package_root, manifest


def add_tree_to_zip(archive: zipfile.ZipFile, package_root: Path) -> None:
    for path in sorted(package_root.rglob("*")):
        archive.write(path, arcname=path.relative_to(package_root.parent).as_posix())


def build_archive(
    *, package_root: Path, output_dir: Path, version: str, target: str, runtime_profile: str = "full"
) -> Path:
    archive_path = output_dir / archive_name(version, target, runtime_profile=runtime_profile)
    if archive_path.exists():
        archive_path.unlink()
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        add_tree_to_zip(archive, package_root)
    return archive_path


def plan_payload(
    *,
    target: str,
    desktop_binary: Path,
    backend_binary: Path,
    output_dir: Path,
    root: Path = ROOT,
    config: dict[str, Any] | None = None,
    runtime_profile: str = "full",
) -> dict[str, Any]:
    config = read_desktop_config() if config is None else config
    version = product_version(config)
    issues = validate_inputs(
        target=target,
        desktop_binary=desktop_binary,
        backend_binary=backend_binary,
        root=root,
        runtime_profile=runtime_profile,
    )
    return {
        "ok": not issues,
        "issues": issues,
        "kind": WINDOWS_LITE_PACKAGE_KIND if is_lite_profile(runtime_profile) else WINDOWS_PACKAGE_KIND,
        "runtimeProfile": "lite" if is_lite_profile(runtime_profile) else "full",
        "productName": product_name(config),
        "version": version,
        "target": target,
        "desktopBinary": str(desktop_binary),
        "backendBinary": "" if is_lite_profile(runtime_profile) else str(backend_binary),
        "backendRuntimeDir": "" if is_lite_profile(runtime_profile) else str(backend_binary.parent),
        "packageDir": str(output_dir / package_dir_name(version, target, runtime_profile=runtime_profile)),
        "archive": str(output_dir / archive_name(version, target, runtime_profile=runtime_profile)),
        "webFileCount": 0 if is_lite_profile(runtime_profile) else len(web_files(root)),
        "requiresSystemPython": is_lite_profile(runtime_profile),
        "installerRequired": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or validate a portable Windows .zip release package.")
    parser.add_argument("--target", default=DEFAULT_TARGET)
    parser.add_argument("--runtime-profile", choices=("full", "lite"), default="full")
    parser.add_argument("--desktop-binary", type=Path, default=None)
    parser.add_argument("--backend-binary", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--check-plan", action="store_true")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target = str(args.target)
    runtime_profile = str(args.runtime_profile)
    desktop_binary = args.desktop_binary or default_desktop_binary(target)
    backend_binary = args.backend_binary or default_backend_binary(target)
    output_dir = args.output_dir or ROOT / "dist" / ("windows-lite" if is_lite_profile(runtime_profile) else "windows")
    payload = plan_payload(
        target=target,
        desktop_binary=desktop_binary,
        backend_binary=backend_binary,
        output_dir=output_dir,
        runtime_profile=runtime_profile,
    )
    if args.check_plan or not args.build:
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(("OK" if payload["ok"] else "FAIL") + f" windows zip plan: {payload['archive']}")
            for issue in payload["issues"]:
                print(f"FAIL {issue}")
        return 0 if payload["ok"] else 1

    if not payload["ok"]:
        for issue in payload["issues"]:
            print(f"FAIL {issue}")
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)
    config = read_desktop_config()
    package_root, manifest = stage_package(
        desktop_binary=desktop_binary,
        backend_binary=backend_binary,
        target=target,
        output_dir=output_dir,
        config=config,
        runtime_profile=runtime_profile,
    )
    archive_path = build_archive(
        package_root=package_root,
        output_dir=output_dir,
        version=product_version(config),
        target=target,
        runtime_profile=runtime_profile,
    )
    payload.update(
        {
            "ok": True,
            "archive": str(archive_path),
            "packageDir": str(package_root),
            "manifest": manifest,
            "builtAt": int(time.time()),
        }
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        label = "windows lite zip" if is_lite_profile(runtime_profile) else "windows zip"
        print(f"OK {label}: {archive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
