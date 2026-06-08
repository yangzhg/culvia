from __future__ import annotations

import argparse
import json
import os
import platform
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DESKTOP_SHELL_DIR = ROOT / "desktop" / "tauri"
DESKTOP_CONFIG_PATH = DESKTOP_SHELL_DIR / "src-tauri" / "tauri.conf.json"
DESKTOP_BACKEND_RESOURCE = "runtime/backend"


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


def has_all(env: Mapping[str, str], names: Sequence[str]) -> bool:
    return all(env_value(env, name) for name in names)


def is_developer_id_application_identity(identity: str) -> bool:
    return identity.startswith("Developer ID Application:")


def notarization_ready(env: Mapping[str, str]) -> bool:
    apple_id_ready = has_all(env, ("APPLE_ID", "APPLE_PASSWORD", "APPLE_TEAM_ID"))
    api_key_ready = has_all(env, ("APPLE_API_KEY", "APPLE_API_ISSUER")) and (
        bool(env_value(env, "APPLE_API_KEY_PATH")) or bool(env_value(env, "API_PRIVATE_KEYS_DIR"))
    )
    return apple_id_ready or api_key_ready


def signing_ready(env: Mapping[str, str], config: dict) -> bool:
    bundle = config.get("bundle", {}) if isinstance(config.get("bundle"), dict) else {}
    macos = bundle.get("macOS", {}) if isinstance(bundle.get("macOS"), dict) else {}
    configured_identity = str(macos.get("signingIdentity", "")).strip()
    ci_certificate_ready = has_all(env, ("APPLE_CERTIFICATE", "APPLE_CERTIFICATE_PASSWORD"))
    local_identity = env_value(env, "APPLE_SIGNING_IDENTITY") or configured_identity
    local_identity_ready = bool(
        local_identity and local_identity != "-" and is_developer_id_application_identity(local_identity)
    )
    return ci_certificate_ready or local_identity_ready


def icon_paths(config: dict, *, config_path: Path) -> list[Path]:
    bundle = config.get("bundle", {}) if isinstance(config.get("bundle"), dict) else {}
    icons = bundle.get("icon", [])
    if not isinstance(icons, list):
        return []
    return [config_path.parent / str(icon) for icon in icons if str(icon).strip()]


def icon_platform_coverage(paths: Sequence[Path]) -> set[str]:
    suffixes = {path.suffix.lower() for path in paths}
    coverage: set[str] = set()
    if ".png" in suffixes:
        coverage.add("png")
    if ".icns" in suffixes:
        coverage.add("macos")
    if ".ico" in suffixes:
        coverage.add("windows")
    return coverage


def backend_binary_ok(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    mode = path.stat().st_mode
    if platform.system().lower().startswith("win"):
        return path.suffix.lower() == ".exe"
    return bool(mode & stat.S_IXUSR)


def resources_include_backend_runtime(bundle: dict) -> bool:
    resources = bundle.get("resources")
    if isinstance(resources, list):
        return any(str(item).strip().rstrip("/") == DESKTOP_BACKEND_RESOURCE for item in resources)
    if isinstance(resources, dict):
        return any(
            str(key).strip().rstrip("/") == DESKTOP_BACKEND_RESOURCE
            or str(value).strip().rstrip("/") == DESKTOP_BACKEND_RESOURCE
            for key, value in resources.items()
        )
    return False


def codesign_identity_visible(identity: str | None, *, env: Mapping[str, str]) -> bool | None:
    if not identity or platform.system() != "Darwin":
        return None
    if identity == "-":
        return True
    try:
        result = subprocess.run(
            ["security", "find-identity", "-v", "-p", "codesigning"],
            env=dict(env),
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0 and identity in result.stdout


def collect_checks(
    *,
    root: Path = ROOT,
    env: Mapping[str, str] | None = None,
    strict_signing: bool = False,
    backend_binary: Path | None = None,
) -> list[CheckResult]:
    env = os.environ if env is None else env
    config_path = root / DESKTOP_CONFIG_PATH.relative_to(ROOT)
    config, config_error = read_json(config_path)
    bundle = config.get("bundle", {}) if isinstance(config.get("bundle"), dict) else {}
    app = config.get("app", {}) if isinstance(config.get("app"), dict) else {}
    windows = app.get("windows", []) if isinstance(app.get("windows"), list) else []
    icons = icon_paths(config, config_path=config_path)
    icon_coverage = icon_platform_coverage(icons)
    signing_is_ready = signing_ready(env, config)
    notarization_is_ready = notarization_ready(env)
    explicit_identity = env_value(env, "APPLE_SIGNING_IDENTITY")
    macos = bundle.get("macOS", {}) if isinstance(bundle.get("macOS"), dict) else {}
    configured_identity = str(macos.get("signingIdentity", "")).strip()
    identity_to_check = explicit_identity or configured_identity or None
    identity_visible = None if identity_to_check == "-" else codesign_identity_visible(identity_to_check, env=env)

    checks = [
        CheckResult(
            "desktop shell config is valid json",
            not config_error,
            config_error or "desktop shell config parsed.",
        ),
        CheckResult(
            "desktop bundle is enabled",
            bundle.get("active") is True and bool(bundle.get("targets")),
            "bundle.active must be true and bundle.targets must be set.",
        ),
        CheckResult(
            "backend runtime resource is configured",
            resources_include_backend_runtime(bundle),
            f"bundle.resources must include {DESKTOP_BACKEND_RESOURCE}.",
        ),
        CheckResult(
            "app icon is configured",
            bool(icons) and all(path.exists() and path.is_file() for path in icons),
            "bundle.icon must include existing files under desktop/tauri/src-tauri.",
        ),
        CheckResult(
            "app icons cover desktop platforms",
            {"png", "macos", "windows"}.issubset(icon_coverage),
            "bundle.icon must include PNG, ICNS, and ICO outputs from the brand icon source.",
        ),
        CheckResult(
            "main window is production gated",
            bool(windows) and windows[0].get("create") is False,
            "main window must be created after backend readiness.",
        ),
        CheckResult(
            "macos signing inputs are configured",
            signing_is_ready,
            "Set APPLE_CERTIFICATE+APPLE_CERTIFICATE_PASSWORD or a Developer ID Application APPLE_SIGNING_IDENTITY/bundle.macOS.signingIdentity.",
            optional=not strict_signing,
        ),
        CheckResult(
            "macos notarization inputs are configured",
            notarization_is_ready,
            "Set APPLE_ID+APPLE_PASSWORD+APPLE_TEAM_ID or APPLE_API_KEY+APPLE_API_ISSUER+APPLE_API_KEY_PATH/API_PRIVATE_KEYS_DIR.",
            optional=not strict_signing,
        ),
    ]
    if identity_visible is not None:
        checks.append(
            CheckResult(
                "macos signing identity is visible",
                identity_visible,
                "security find-identity must list APPLE_SIGNING_IDENTITY or bundle.macOS.signingIdentity.",
                optional=not strict_signing,
            )
        )
    if backend_binary is not None:
        checks.append(
            CheckResult(
                "backend binary is executable",
                backend_binary_ok(backend_binary),
                f"Expected executable backend binary at {backend_binary}.",
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
    parser = argparse.ArgumentParser(description="Validate desktop release prerequisites.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--strict-signing", action="store_true", help="Fail when macOS signing/notarization inputs are missing."
    )
    parser.add_argument(
        "--backend-binary", type=Path, default=None, help="Optional backend binary path to check for executability."
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    checks = collect_checks(root=args.root, strict_signing=args.strict_signing, backend_binary=args.backend_binary)
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
    raise SystemExit(main(sys.argv[1:]))
