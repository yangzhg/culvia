from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE_DIR = ROOT / "desktop" / "tauri" / "src-tauri" / "target" / "release" / "bundle"
DESKTOP_CONFIG_PATH = ROOT / "desktop" / "tauri" / "src-tauri" / "tauri.conf.json"

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    optional: bool = False


@dataclass(frozen=True)
class ArtifactDiscovery:
    path: Path | None
    issue: CheckResult | None = None


def compact(text: str, *, max_chars: int = 600) -> str:
    stripped = text.strip()
    if len(stripped) <= max_chars:
        return stripped
    return stripped[-max_chars:]


def read_desktop_config(path: Path = DESKTOP_CONFIG_PATH) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def discover_unique(root: Path, pattern: str, *, directory: bool | None = None, name: str) -> ArtifactDiscovery:
    if not root.exists():
        return ArtifactDiscovery(None)
    candidates = []
    for candidate in sorted(root.rglob(pattern), key=lambda path: (len(path.parts), str(path))):
        if directory is True and not candidate.is_dir():
            continue
        if directory is False and not candidate.is_file():
            continue
        if pattern == "*.dmg" and candidate.name.startswith("rw."):
            continue
        candidates.append(candidate)
    if not candidates:
        return ArtifactDiscovery(None)
    if len(candidates) > 1:
        return ArtifactDiscovery(
            None,
            CheckResult(
                f"macos {name} artifact is unique",
                False,
                "Multiple candidates found; pass an explicit path: " + ", ".join(str(path) for path in candidates),
            ),
        )
    return ArtifactDiscovery(candidates[0])


def resolve_app_path(bundle_dir: Path, app: Path | None) -> ArtifactDiscovery:
    if app is not None:
        return ArtifactDiscovery(app)
    return discover_unique(bundle_dir, "*.app", directory=True, name="app")


def resolve_dmg_path(bundle_dir: Path, dmg: Path | None) -> ArtifactDiscovery:
    if dmg is not None:
        return ArtifactDiscovery(dmg)
    return discover_unique(bundle_dir, "*.dmg", directory=False, name="dmg")


def is_macho_binary(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            magic = handle.read(4)
    except OSError:
        return False
    return magic in {
        b"\xfe\xed\xfa\xce",
        b"\xce\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf",
        b"\xcf\xfa\xed\xfe",
        b"\xca\xfe\xba\xbe",
        b"\xbe\xba\xfe\xca",
    }


def executable_ok(path: Path) -> tuple[bool, str]:
    if not path.exists() or not path.is_file():
        return False, f"Expected executable at {path}."
    if not (path.stat().st_mode & stat.S_IXUSR):
        return False, f"Executable is not user-executable: {path}."
    if not is_macho_binary(path):
        return False, f"Executable is not a Mach-O binary: {path}."
    return True, f"{path.name} is executable and has a Mach-O header."


def app_bundle_detail(app: Path, *, config: dict) -> tuple[bool, str, Path | None]:
    if not app.exists() or not app.is_dir() or app.suffix != ".app":
        return False, f"Expected a .app bundle directory at {app}.", None
    plist_path = app / "Contents" / "Info.plist"
    if not plist_path.exists():
        return False, f"Expected Info.plist at {plist_path}.", None
    try:
        info = plistlib.loads(plist_path.read_bytes())
    except Exception as exc:
        return False, f"Info.plist is not readable: {exc}.", None
    executable_name = str(info.get("CFBundleExecutable", "")).strip()
    identifier = str(info.get("CFBundleIdentifier", "")).strip()
    version = str(info.get("CFBundleShortVersionString", "")).strip()
    package_type = str(info.get("CFBundlePackageType", "")).strip()
    expected_identifier = str(config.get("identifier", "")).strip()
    expected_version = str(config.get("version", "")).strip()
    if not executable_name:
        return False, "Info.plist must include CFBundleExecutable.", None
    if not identifier:
        return False, "Info.plist must include CFBundleIdentifier.", None
    if expected_identifier and identifier != expected_identifier:
        return False, f"CFBundleIdentifier {identifier} does not match desktop identifier {expected_identifier}.", None
    if expected_version and version != expected_version:
        return (
            False,
            f"CFBundleShortVersionString {version or '<missing>'} does not match desktop version {expected_version}.",
            None,
        )
    if package_type != "APPL":
        return False, f"CFBundlePackageType must be APPL, got {package_type or '<missing>'}.", None
    executable = app / "Contents" / "MacOS" / executable_name
    ok, executable_detail = executable_ok(executable)
    if not ok:
        return False, executable_detail, executable
    return (
        True,
        f"{app} contains Info.plist, identifier {identifier}, version {version}, and executable {executable.name}.",
        executable,
    )


def backend_candidates(app: Path) -> list[Path]:
    resources = app / "Contents" / "Resources"
    candidates: list[Path] = []
    runtime_root = resources / "runtime" / "backend"
    if runtime_root.exists():
        candidates.extend(sorted(runtime_root.glob("*/culvia-server/culvia-server")))
    return candidates


def backend_detail(app: Path) -> tuple[bool, str, Path | None]:
    candidates = [path for path in backend_candidates(app) if path.is_file()]
    if not candidates:
        return False, f"Expected bundled backend under {app}/Contents/Resources/runtime/backend.", None
    if len(candidates) > 1:
        return False, "Multiple bundled backends found: " + ", ".join(str(path) for path in candidates), None
    backend = candidates[0]
    ok, detail = executable_ok(backend)
    return ok, detail, backend


def dmg_detail(dmg: Path) -> tuple[bool, str]:
    if not dmg.exists() or not dmg.is_file() or dmg.suffix.lower() != ".dmg":
        return False, f"Expected a .dmg file at {dmg}."
    if dmg.stat().st_size <= 0:
        return False, f"DMG is empty: {dmg}."
    return True, f"{dmg} exists and is non-empty."


def run_default(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        text=True,
        capture_output=True,
        check=False,
    )


def command_check(name: str, command: Sequence[str], *, runner: Runner, optional: bool = False) -> CheckResult:
    try:
        result = runner(command)
    except FileNotFoundError as exc:
        return CheckResult(name, False, f"Command is unavailable: {exc}.", optional=optional)
    detail_parts = [f"{' '.join(command)} exited {result.returncode}."]
    output = compact((result.stdout or "") + "\n" + (result.stderr or ""))
    if output:
        detail_parts.append(output)
    return CheckResult(name, result.returncode == 0, " ".join(detail_parts), optional=optional)


def signature_detail_check(name: str, command: Sequence[str], *, runner: Runner, optional: bool = False) -> CheckResult:
    result = command_check(name, command, runner=runner, optional=optional)
    if not result.ok:
        return result
    output = result.detail
    required = ("Authority=Developer ID Application", "TeamIdentifier=", "Runtime Version=")
    missing = [text for text in required if text not in output]
    if missing:
        return CheckResult(
            name,
            False,
            f"{result.detail} Missing signature details: {', '.join(missing)}.",
            optional=optional,
        )
    return result


def collect_checks(
    *,
    bundle_dir: Path = DEFAULT_BUNDLE_DIR,
    app: Path | None = None,
    dmg: Path | None = None,
    strict: bool = False,
    runtime_profile: str = "full",
    runner: Runner = run_default,
    system: str | None = None,
) -> list[CheckResult]:
    system = system or platform.system()
    config = read_desktop_config()
    app_discovery = resolve_app_path(bundle_dir, app)
    dmg_discovery = resolve_dmg_path(bundle_dir, dmg)
    app_path = app_discovery.path
    dmg_path = dmg_discovery.path
    checks: list[CheckResult] = []
    app_executable: Path | None = None
    backend_path: Path | None = None

    if app_discovery.issue:
        checks.append(app_discovery.issue)
    if dmg_discovery.issue:
        checks.append(dmg_discovery.issue)

    if app_path is None:
        checks.append(
            CheckResult(
                "macos app artifact exists",
                False,
                f"No .app bundle found under {bundle_dir}. Run npm --prefix desktop/tauri run tauri:build first or pass --app.",
                optional=not strict,
            )
        )
    else:
        ok, detail, app_executable = app_bundle_detail(app_path, config=config)
        checks.append(CheckResult("macos app bundle structure", ok, detail))
        if ok and runtime_profile != "lite":
            backend_ok, backend_message, backend_path = backend_detail(app_path)
            checks.append(CheckResult("macos bundled backend structure", backend_ok, backend_message))

    if dmg_path is None:
        checks.append(
            CheckResult(
                "macos dmg artifact exists",
                False,
                f"No .dmg found under {bundle_dir}. Run npm --prefix desktop/tauri run tauri:build first or pass --dmg.",
                optional=not strict,
            )
        )
    else:
        ok, detail = dmg_detail(dmg_path)
        checks.append(CheckResult("macos dmg artifact structure", ok, detail))

    artifact_available = app_path is not None or dmg_path is not None
    if system != "Darwin":
        checks.append(
            CheckResult(
                "macos artifact checks run on Darwin",
                False,
                f"Current platform is {system}; codesign, spctl, and stapler checks require macOS.",
                optional=not strict or not artifact_available,
            )
        )
        return checks

    if app_path is not None and app_executable is not None:
        checks.append(
            command_check(
                "macos app codesign verification",
                ("codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app_path)),
                runner=runner,
            )
        )
        checks.append(
            command_check(
                "macos app executable codesign verification",
                ("codesign", "--verify", "--strict", "--verbose=2", str(app_executable)),
                runner=runner,
            )
        )
        checks.append(
            signature_detail_check(
                "macos app signature details",
                ("codesign", "-dv", "--verbose=4", str(app_path)),
                runner=runner,
                optional=not strict,
            )
        )
        checks.append(
            command_check(
                "macos app gatekeeper assessment",
                ("spctl", "--assess", "--type", "execute", "--verbose=4", str(app_path)),
                runner=runner,
                optional=not strict,
            )
        )
        checks.append(
            command_check(
                "macos app executable architecture",
                ("lipo", "-archs", str(app_executable)),
                runner=runner,
            )
        )

    if backend_path is not None:
        checks.append(
            command_check(
                "macos bundled backend codesign verification",
                ("codesign", "--verify", "--strict", "--verbose=2", str(backend_path)),
                runner=runner,
            )
        )
        checks.append(
            signature_detail_check(
                "macos bundled backend signature details",
                ("codesign", "-dv", "--verbose=4", str(backend_path)),
                runner=runner,
                optional=not strict,
            )
        )
        checks.append(
            command_check(
                "macos bundled backend architecture",
                ("lipo", "-archs", str(backend_path)),
                runner=runner,
            )
        )

    if dmg_path is not None and dmg_detail(dmg_path)[0]:
        checks.append(
            command_check(
                "macos dmg hdiutil verification",
                ("hdiutil", "verify", str(dmg_path)),
                runner=runner,
            )
        )
        checks.append(
            command_check(
                "macos dmg stapler validation",
                ("xcrun", "stapler", "validate", str(dmg_path)),
                runner=runner,
                optional=not strict,
            )
        )
        checks.append(
            command_check(
                "macos dmg gatekeeper assessment",
                ("spctl", "--assess", "--type", "open", "--verbose=4", str(dmg_path)),
                runner=runner,
                optional=not strict,
            )
        )

    return checks


def result_payload(checks: Sequence[CheckResult]) -> dict:
    failed = [check for check in checks if not check.ok and not check.optional]
    skipped = [check for check in checks if not check.ok and check.optional]
    return {
        "ok": not failed,
        "failed": [check.name for check in failed],
        "skipped": [check.name for check in skipped],
        "checks": [
            {
                "name": check.name,
                "ok": check.ok,
                "optional": check.optional,
                "detail": check.detail,
            }
            for check in checks
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate built macOS desktop artifacts.")
    parser.add_argument("--bundle-dir", type=Path, default=DEFAULT_BUNDLE_DIR)
    parser.add_argument("--app", type=Path, default=None, help="Path to a built .app bundle.")
    parser.add_argument("--dmg", type=Path, default=None, help="Path to a built .dmg installer.")
    parser.add_argument(
        "--strict", action="store_true", help="Fail when artifacts are missing or checks are not running on macOS."
    )
    parser.add_argument("--runtime-profile", choices=("full", "lite"), default="full")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    checks = collect_checks(
        bundle_dir=args.bundle_dir,
        app=args.app,
        dmg=args.dmg,
        strict=args.strict,
        runtime_profile=args.runtime_profile,
    )
    payload = result_payload(checks)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for check in checks:
            if check.ok:
                status = "OK"
            elif check.optional:
                status = "SKIP"
            else:
                status = "FAIL"
            print(f"{status} {check.name}: {check.detail}")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
