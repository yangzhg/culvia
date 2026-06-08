from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DESKTOP_CONFIG_PATH = ROOT / "desktop" / "tauri" / "src-tauri" / "tauri.conf.json"
APPLE_SIGNING_IDENTITY_ENV = "APPLE_SIGNING_IDENTITY"
BACKEND_CODESIGN_IDENTITY_ENV = "CULVIA_MACOS_BACKEND_CODESIGN_IDENTITY"
APPLE_DEVELOPMENT_PREFIX = "Apple Development:"
DEVELOPER_ID_PREFIX = "Developer ID Application:"
AD_HOC_IDENTITY = "-"
EXTRA_TOOLCHAIN_DIRECTORIES = (
    Path.home() / ".cargo" / "bin",
    Path("/opt/homebrew/opt/rustup/bin"),
    Path("/usr/local/opt/rustup/bin"),
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    optional: bool = False


def read_json(path: Path) -> tuple[dict, str]:
    if not path.exists():
        return {}, f"{path} is missing."
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {}, f"{path} is invalid JSON: {exc}"
    if not isinstance(payload, dict):
        return {}, f"{path} must contain a JSON object."
    return payload, ""


def env_value(env: Mapping[str, str], name: str) -> str:
    return env.get(name, "").strip()


def configured_macos_identity(config: dict) -> str:
    bundle = config.get("bundle", {}) if isinstance(config.get("bundle"), dict) else {}
    macos = bundle.get("macOS", {}) if isinstance(bundle.get("macOS"), dict) else {}
    return str(macos.get("signingIdentity", "")).strip()


def command_available(name: str) -> bool:
    if shutil.which(name):
        return True
    return any((directory / name).exists() for directory in EXTRA_TOOLCHAIN_DIRECTORIES)


def xcode_license_check() -> tuple[bool, str]:
    if not command_available("xcodebuild"):
        return False, "xcodebuild is not available."
    result = subprocess.run(
        ["xcodebuild", "-license", "check"],
        text=True,
        capture_output=True,
        check=False,
    )
    output = (result.stdout + "\n" + result.stderr).strip()
    if result.returncode == 0:
        return True, output or "Xcode license accepted."
    return False, output or f"xcodebuild -license check failed with exit code {result.returncode}."


def codesigning_identities() -> tuple[list[str], str]:
    if not command_available("security"):
        return [], "security command is not available."
    result = subprocess.run(
        ["security", "find-identity", "-v", "-p", "codesigning"],
        text=True,
        capture_output=True,
        check=False,
    )
    output = (result.stdout + "\n" + result.stderr).strip()
    if result.returncode != 0:
        return [], output or f"security find-identity failed with exit code {result.returncode}."
    identities: list[str] = []
    for line in result.stdout.splitlines():
        if '"' not in line:
            continue
        parts = line.split('"')
        if len(parts) >= 3 and parts[1].strip():
            identities.append(parts[1].strip())
    return identities, output or "No codesigning identities found."


def apple_development_identities(identities: Sequence[str]) -> list[str]:
    return [identity for identity in identities if identity.startswith(APPLE_DEVELOPMENT_PREFIX)]


def identity_is_local_build_compatible(identity: str) -> bool:
    return (
        identity == AD_HOC_IDENTITY
        or identity.startswith(APPLE_DEVELOPMENT_PREFIX)
        or identity.startswith(DEVELOPER_ID_PREFIX)
    )


def selected_macos_identity(*, env: Mapping[str, str], config: dict, visible_development: Sequence[str]) -> str:
    explicit = env_value(env, APPLE_SIGNING_IDENTITY_ENV)
    if explicit:
        return explicit
    configured = configured_macos_identity(config)
    if configured and configured != AD_HOC_IDENTITY:
        return configured
    if visible_development:
        return visible_development[0]
    return configured or AD_HOC_IDENTITY


def cleanup_candidate_count(root: Path) -> tuple[int, str]:
    try:
        from tools import clean_macos_app_artifacts
    except Exception as exc:  # pragma: no cover - defensive import guard
        return -1, f"could not import macOS app cleanup tool: {exc}"
    payload = clean_macos_app_artifacts.run_cleanup(root=root, apply=False)
    return int(payload["candidateCount"]), f"{payload['candidateCount']} macOS app cleanup candidate(s)."


def next_commands(identity: str) -> list[str]:
    prefix = ""
    if identity and identity != AD_HOC_IDENTITY:
        prefix = f"APPLE_SIGNING_IDENTITY='{identity}' {BACKEND_CODESIGN_IDENTITY_ENV}='{identity}' "
    return [
        "python tools/check_macos_app_preflight.py --json",
        f"{prefix}python tools/build_macos_app.py --clean-first --json",
        "python tools/clean_macos_app_artifacts.py --apply --json",
    ]


def collect_checks(
    *,
    root: Path = ROOT,
    env: Mapping[str, str] | None = None,
    system: str = sys.platform,
    require_apple_development: bool = False,
    require_clean: bool = True,
) -> tuple[list[CheckResult], dict]:
    env = os.environ if env is None else env
    root = root.resolve()
    config, config_error = read_json(root / DESKTOP_CONFIG_PATH.relative_to(ROOT))
    identities, identity_detail = codesigning_identities() if system == "darwin" else ([], "not running on macOS.")
    development = apple_development_identities(identities)
    selected = selected_macos_identity(env=env, config=config, visible_development=development)
    cleanup_count, cleanup_detail = cleanup_candidate_count(root)
    license_ok, license_detail = (
        xcode_license_check() if system == "darwin" else (False, "macOS app builds require macOS.")
    )

    checks = [
        CheckResult(
            "macos host is available",
            system == "darwin",
            "macOS app build must run on macOS.",
        ),
        CheckResult(
            "xcode license is accepted",
            license_ok,
            license_detail,
        ),
        CheckResult(
            "rust cargo is available",
            command_available("cargo"),
            "cargo must be available for desktop builds.",
        ),
        CheckResult(
            "node npm is available",
            command_available("npm"),
            "npm must be available for desktop builds.",
        ),
        CheckResult(
            "desktop shell config is valid json",
            not config_error,
            config_error or "desktop shell config parsed.",
        ),
        CheckResult(
            "macos local signing identity is compatible",
            identity_is_local_build_compatible(selected),
            (
                "Use '-' for ad-hoc local builds, Apple Development for free-account local signing, "
                "or Developer ID for formal release builds."
            ),
        ),
        CheckResult(
            "apple development identity is visible",
            bool(development),
            identity_detail,
            optional=not require_apple_development,
        ),
        CheckResult(
            "selected signing identity is visible",
            selected == AD_HOC_IDENTITY or selected in identities,
            f"selected identity: {selected}",
            optional=selected == AD_HOC_IDENTITY,
        ),
        CheckResult(
            "macos app artifact cleanup state is clean",
            cleanup_count == 0,
            cleanup_detail,
            optional=not require_clean,
        ),
    ]
    meta = {
        "selectedIdentity": selected,
        "configuredIdentity": configured_macos_identity(config),
        "visibleAppleDevelopmentIdentities": development,
        "nextCommands": next_commands(selected),
    }
    return checks, meta


def result_payload(checks: Sequence[CheckResult], meta: dict) -> dict:
    failed = [check for check in checks if not check.ok and not check.optional]
    skipped = [check for check in checks if not check.ok and check.optional]
    return {
        "ok": not failed,
        "failed": [check.name for check in failed],
        "skipped": [check.name for check in skipped],
        "passed": [check.name for check in checks if check.ok],
        **meta,
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
    parser = argparse.ArgumentParser(description="Validate this Mac for a local desktop app build.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--require-apple-development",
        action="store_true",
        help="Fail if no Apple Development codesigning identity is visible.",
    )
    parser.add_argument(
        "--allow-existing-artifacts",
        action="store_true",
        help="Treat existing ignored build artifacts as informational after an app build has produced them.",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def print_text(payload: dict) -> None:
    for check in payload["checks"]:
        if check["ok"]:
            status = "OK"
        elif check["optional"]:
            status = "SKIP"
        else:
            status = "FAIL"
        print(f"{status} {check['name']}: {check['detail']}")
    print(f"Selected identity: {payload['selectedIdentity']}")
    print("Next commands:")
    for command in payload["nextCommands"]:
        print(f"- {command}")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    checks, meta = collect_checks(
        root=args.root,
        require_apple_development=args.require_apple_development,
        require_clean=not args.allow_existing_artifacts,
    )
    payload = result_payload(checks, meta)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_text(payload)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
