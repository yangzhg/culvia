from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import stat
import sys
import tarfile
import time
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
DESKTOP_CONFIG_PATH = ROOT / "desktop" / "tauri" / "src-tauri" / "tauri.conf.json"
BACKEND_BUILD_SCRIPT = ROOT / "desktop" / "tauri" / "scripts" / "build-backend.py"
DEFAULT_TARGET = "x86_64-unknown-linux-gnu"
PACKAGE_SLUG = "culvia"
LINUX_PACKAGE_KIND = "culvia-linux-tgz"
LINUX_LITE_PACKAGE_KIND = "culvia-linux-lite-tgz"
PACKAGE_DESKTOP_NAME = "culvia-desktop"
PACKAGE_BACKEND_NAME = "culvia-server"
PACKAGE_BACKEND_RUNTIME_ROOT = "runtime/backend"


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
        return f"{PACKAGE_SLUG}-{version}-linux-lite-{target}"
    return f"{PACKAGE_SLUG}-{version}-linux-{target}"


def archive_name(version: str, target: str, *, runtime_profile: str = "full") -> str:
    return f"{package_dir_name(version, target, runtime_profile=runtime_profile)}.tar.gz"


def backend_binary_name(target: str) -> str:
    return str(load_backend_build_tool().backend_binary_name(target, os_name="Linux"))


def default_backend_binary(target: str, *, root: Path = ROOT) -> Path:
    tool = load_backend_build_tool()
    return tool.backend_binary_path(target)


def default_desktop_binary(target: str, *, root: Path = ROOT) -> Path:
    target_release = root / "desktop" / "tauri" / "src-tauri" / "target" / target / "release" / PACKAGE_DESKTOP_NAME
    host_release = root / "desktop" / "tauri" / "src-tauri" / "target" / "release" / PACKAGE_DESKTOP_NAME
    return target_release if target_release.exists() else host_release


def is_executable(path: Path) -> bool:
    return bool(path.stat().st_mode & stat.S_IXUSR)


def is_elf(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(4) == b"\x7fELF"


def web_files(root: Path = ROOT) -> list[Path]:
    web_dir = root / "web"
    return sorted(path for path in web_dir.rglob("*") if path.is_file())


def validate_elf_executable(path: Path, *, label: str) -> list[str]:
    issues: list[str] = []
    if not path.exists():
        return [f"missing {label}: {path}"]
    if not path.is_file():
        return [f"{label} is not a file: {path}"]
    if not is_executable(path):
        issues.append(f"{label} must be executable: {path}")
    if not is_elf(path):
        issues.append(f"{label} must be a Linux ELF executable: {path}")
    return issues


def validate_inputs(
    *, desktop_binary: Path, backend_binary: Path, root: Path = ROOT, runtime_profile: str = "full"
) -> list[str]:
    issues: list[str] = []
    web_dir = root / "web"
    if not is_lite_profile(runtime_profile) and (not web_dir.exists() or not (web_dir / "index.html").is_file()):
        issues.append(f"missing web assets: {web_dir}")
    issues.extend(validate_elf_executable(desktop_binary, label="Linux desktop shell binary"))
    if not is_lite_profile(runtime_profile):
        issues.extend(validate_elf_executable(backend_binary, label="Linux backend binary"))
        if backend_binary.parent.name != "culvia-server":
            issues.append(f"Linux backend binary must live inside a culvia-server runtime directory: {backend_binary}")
    return issues


def backend_package_dir(target: str) -> Path:
    return Path(PACKAGE_BACKEND_RUNTIME_ROOT) / target / PACKAGE_BACKEND_NAME


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
            "kind": LINUX_LITE_PACKAGE_KIND,
            "runtimeProfile": "lite",
            "productName": product_name(config),
            "version": version,
            "target": target,
            "launcher": "bin/culvia",
            "desktop": {
                "sourceName": source_desktop.name,
                "path": f"bin/{PACKAGE_DESKTOP_NAME}",
                "expectedFormat": "ELF",
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
                "command": "bin/culvia",
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
        "kind": LINUX_PACKAGE_KIND,
        "productName": product_name(config),
        "version": version,
        "target": target,
        "launcher": "bin/culvia",
        "desktop": {
            "sourceName": source_desktop.name,
            "path": f"bin/{PACKAGE_DESKTOP_NAME}",
            "expectedFormat": "ELF",
        },
        "backend": {
            "sourceName": source_backend.name,
            "path": backend_package_binary(target).as_posix(),
            "runtimeDir": backend_package_dir(target).as_posix(),
            "mustNotRequireUserPython": True,
            "expectedFormat": "ELF",
        },
        "web": {
            "path": "share/culvia/web",
            "entry": "share/culvia/web/index.html",
            "env": "CULVIA_WEB_DIR",
        },
        "smoke": {
            "command": "CULVIA_DESKTOP_FORCE_BACKEND=1 bin/culvia",
            "runtime": "Desktop shell starts bundled backend, waits for /health, then creates the desktop window.",
            "healthPath": "/health",
        },
    }


def launcher_text(target: str) -> str:
    backend = backend_package_binary(target).as_posix()
    return "\n".join(
        (
            "#!/usr/bin/env sh",
            "set -eu",
            'APP_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"',
            'export CULVIA_WEB_DIR="${CULVIA_WEB_DIR:-$APP_DIR/share/culvia/web}"',
            f'export CULVIA_BACKEND_PATH="${{CULVIA_BACKEND_PATH:-$APP_DIR/{backend}}}"',
            'export CULVIA_DESKTOP_FORCE_BACKEND="${CULVIA_DESKTOP_FORCE_BACKEND:-1}"',
            'exec "$APP_DIR/bin/culvia-desktop" "$@"',
            "",
        )
    )


def lite_launcher_text() -> str:
    return "\n".join(
        (
            "#!/usr/bin/env sh",
            "set -eu",
            'APP_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"',
            'export CULVIA_DESKTOP_RUNTIME_MODE="${CULVIA_DESKTOP_RUNTIME_MODE:-lite}"',
            'exec "$APP_DIR/bin/culvia-desktop" "$@"',
            "",
        )
    )


def readme_text(*, version: str, target: str, runtime_profile: str = "full") -> str:
    if is_lite_profile(runtime_profile):
        return "\n".join(
            (
                "# Culvia Linux Lite Package",
                "",
                f"Version: {version}",
                f"Target: {target}",
                "",
                "This archive contains the desktop shell only.",
                "On first launch, Culvia uses Python 3.11+ to create an app-managed virtualenv and install the runtime package.",
                "",
                "Run:",
                "",
                "```sh",
                "bin/culvia",
                "```",
                "",
                "Lite runtime configuration is stored in the user's Culvia runtime directory as `runtime.json`.",
                "API keys, model caches, databases, and exported photos are not bundled into this archive.",
                "",
            )
        )
    return "\n".join(
        (
            "# Culvia Linux Package",
            "",
            f"Version: {version}",
            f"Target: {target}",
            "",
            "This archive is a self-contained desktop package.",
            "The bundled Python backend does not require a system Python installation.",
            "",
            "Run:",
            "",
            "```sh",
            "bin/culvia",
            "```",
            "",
            "The launcher starts the bundled desktop shell and points it at the bundled Python backend.",
            "Model weights are still managed as local cache data and are not bundled into this archive.",
            "",
        )
    )


def copy_web_assets(*, root: Path, destination: Path) -> None:
    source = root / "web"
    shutil.copytree(source, destination)


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
    (package_root / "bin").mkdir(parents=True)
    (package_root / "share" / "culvia").mkdir(parents=True)

    bundled_desktop = package_root / "bin" / PACKAGE_DESKTOP_NAME
    shutil.copy2(desktop_binary, bundled_desktop)
    bundled_desktop.chmod(bundled_desktop.stat().st_mode | stat.S_IXUSR)

    if not is_lite_profile(runtime_profile):
        shutil.copytree(backend_binary.parent, package_root / backend_package_dir(target))
        bundled_backend = package_root / backend_package_binary(target)
        bundled_backend.chmod(bundled_backend.stat().st_mode | stat.S_IXUSR)

    launcher = package_root / "bin" / "culvia"
    launcher.write_text(
        lite_launcher_text() if is_lite_profile(runtime_profile) else launcher_text(target),
        encoding="utf-8",
    )
    launcher.chmod(0o755)

    if not is_lite_profile(runtime_profile):
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


def add_tree_to_tar(archive: tarfile.TarFile, package_root: Path) -> None:
    for path in sorted(package_root.rglob("*")):
        archive.add(path, arcname=path.relative_to(package_root.parent), recursive=False)


def build_archive(
    *, package_root: Path, output_dir: Path, version: str, target: str, runtime_profile: str = "full"
) -> Path:
    archive_path = output_dir / archive_name(version, target, runtime_profile=runtime_profile)
    if archive_path.exists():
        archive_path.unlink()
    with tarfile.open(archive_path, "w:gz") as archive:
        add_tree_to_tar(archive, package_root)
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
        desktop_binary=desktop_binary,
        backend_binary=backend_binary,
        root=root,
        runtime_profile=runtime_profile,
    )
    return {
        "ok": not issues,
        "issues": issues,
        "kind": LINUX_LITE_PACKAGE_KIND if is_lite_profile(runtime_profile) else LINUX_PACKAGE_KIND,
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
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build or validate a self-contained Linux .tar.gz release package.")
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
    output_dir = args.output_dir or ROOT / "dist" / ("linux-lite" if is_lite_profile(runtime_profile) else "linux")
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
            print(("OK" if payload["ok"] else "FAIL") + f" linux tgz plan: {payload['archive']}")
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
        label = "linux lite tgz" if is_lite_profile(runtime_profile) else "linux tgz"
        print(f"OK {label}: {archive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
