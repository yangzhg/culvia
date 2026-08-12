from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
STABLE_VERSION_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def _python_package_version(path: Path) -> str:
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', path.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise ValueError(f"missing __version__ in {path}")
    return match.group(1)


def collect_versions(root: Path = ROOT) -> dict[str, str]:
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    package_json = json.loads((root / "desktop/tauri/package.json").read_text(encoding="utf-8"))
    package_lock = json.loads((root / "desktop/tauri/package-lock.json").read_text(encoding="utf-8"))
    cargo_toml = tomllib.loads((root / "desktop/tauri/src-tauri/Cargo.toml").read_text(encoding="utf-8"))
    cargo_lock = tomllib.loads((root / "desktop/tauri/src-tauri/Cargo.lock").read_text(encoding="utf-8"))
    tauri_config = json.loads((root / "desktop/tauri/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    cargo_lock_version = next(
        (str(package["version"]) for package in cargo_lock["package"] if package.get("name") == "culvia-desktop"),
        "",
    )
    return {
        "pyproject.toml": str(pyproject["project"]["version"]),
        "culvia/__init__.py": _python_package_version(root / "culvia/__init__.py"),
        "desktop/tauri/package.json": str(package_json["version"]),
        "desktop/tauri/package-lock.json": str(package_lock["version"]),
        "desktop/tauri/package-lock.json packages root": str(package_lock["packages"][""]["version"]),
        "desktop/tauri/src-tauri/Cargo.toml": str(cargo_toml["package"]["version"]),
        "desktop/tauri/src-tauri/Cargo.lock": cargo_lock_version,
        "desktop/tauri/src-tauri/tauri.conf.json": str(tauri_config["version"]),
    }


def version_sync_errors(versions: dict[str, str], *, tag: str = "") -> list[str]:
    canonical = versions.get("pyproject.toml", "").strip()
    errors = []
    if not STABLE_VERSION_PATTERN.fullmatch(canonical):
        errors.append(f"canonical version {canonical!r} must use stable semantic X.Y.Z form")
    errors.extend(
        [
            f"{source} has version {version!r}; expected {canonical!r}"
            for source, version in versions.items()
            if version != canonical
        ]
    )
    release_tag = tag.strip()
    if release_tag and release_tag != f"v{canonical}":
        errors.append(f"release tag {release_tag!r} does not match canonical version tag 'v{canonical}'")
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check that Python, desktop, and release versions stay synchronized.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--tag", default="", help="Optional release tag; when set it must equal v<version>.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        versions = collect_versions(args.root)
    except (KeyError, OSError, TypeError, ValueError, tomllib.TOMLDecodeError, json.JSONDecodeError) as exc:
        print(f"version sync check failed: {exc}", file=sys.stderr)
        return 1
    errors = version_sync_errors(versions, tag=args.tag)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"Culvia version {versions['pyproject.toml']} is synchronized across {len(versions)} sources.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
