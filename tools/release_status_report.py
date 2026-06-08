from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import (
    check_desktop_release_workflow,
    check_portable_package_preflight,
    check_macos_artifact_preflight,
    check_macos_app_preflight,
    check_desktop_readiness,
    desktop_release_contract,
    release_smoke,
    write_release_checksum,
    write_release_evidence_manifest,
)


PUBLIC_STRING_LIMIT = 2000
MACOS_APP_ARTIFACT_BLOCKERS = frozenset(
    {
        "macos app artifact exists",
        "macos dmg artifact exists",
    }
)
MACOS_FORMAL_ARTIFACT_BLOCKERS = frozenset(
    {
        "macos app signature details",
        "macos app gatekeeper assessment",
        "macos bundled backend signature details",
        "macos dmg stapler validation",
        "macos dmg gatekeeper assessment",
    }
)
MACOS_APP_BUILD_COMMANDS = [
    "python tools/build_macos_app.py --clean-first --json",
]
MACOS_LITE_DIST_DIR = Path("dist") / "macos-lite"
MACOS_LITE_APP_BUILD_COMMANDS = [
    "python tools/build_macos_app.py --clean-first --runtime-profile lite --json",
]
MACOS_DIST_DIR = Path("dist") / "macos"
PYTHON_DIST_DIR = Path("dist") / "python"
PYTHON_RELEASE_COMMANDS = [
    "make python-release",
    "python tools/release_smoke.py --build --wheelhouse dist/python --build-sdist --dist-dir dist/python --install --twine-check --strict",
    "python tools/release_status_report.py --release-smoke --build-sdist --wheelhouse dist/python --dist-dir dist/python --json",
]
MACOS_FORMAL_RELEASE_COMMANDS = [
    "python tools/check_desktop_release_preflight.py --strict-signing --backend-binary desktop/tauri/src-tauri/runtime/backend/aarch64-apple-darwin/culvia-server/culvia-server --json",
    "python tools/check_macos_artifact_preflight.py --strict --json",
]
SECRET_TEXT_PATTERNS = (
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"), "sk-<redacted>"),
    (re.compile(r"\bpypi-[A-Za-z0-9_-]{8,}\b"), "pypi-<redacted>"),
    (re.compile(r"\bgh[opusr]_[A-Za-z0-9_]{8,}\b"), "gh<redacted>"),
    (re.compile(r"\b([A-Z][A-Z0-9_]{2,}(?:API_KEY|TOKEN|SECRET|PASSWORD))=([^\s'\";,]+)"), r"\1=<redacted>"),
    (re.compile(r"(https?://)([^/\s:@]+):([^@\s/]+)@"), r"\1<redacted>@"),
)
ABSOLUTE_PATH_PATTERNS = (
    re.compile(
        r"(?<![\w<>])/(?:Users|home|var/folders|private/tmp|tmp|Volumes|opt|mnt|root|workspace|build)(?:/[^\s,'\";:)]+)+"
    ),
    re.compile(r"\b[A-Za-z]:\\(?:Users|Temp|tmp|workspace|build)\\[^\s,'\";)]+"),
)


@dataclass(frozen=True)
class PlatformReport:
    key: str
    label: str
    status: str
    ready: bool
    evidence: list[str]
    blockers: list[str]
    nextCommands: list[str]


def check_payload(checks: Sequence[Any]) -> dict[str, Any]:
    return {
        "ok": all(bool(getattr(check, "ok", False)) or bool(getattr(check, "optional", False)) for check in checks),
        "failed": [check.name for check in checks if not check.ok and not getattr(check, "optional", False)],
        "skipped": [check.name for check in checks if not check.ok and getattr(check, "optional", False)],
        "passed": [check.name for check in checks if check.ok],
    }


def temp_path(name: str) -> Path:
    return Path(tempfile.gettempdir()) / name


def gate_check(name: str, ok: bool, detail: str = "", *, optional: bool = False) -> dict[str, Any]:
    return {"name": name, "ok": ok, "optional": optional, "detail": detail}


def gate_payload(checks: Sequence[dict[str, Any]], *, next_commands: Sequence[str] = ()) -> dict[str, Any]:
    return {
        "ok": all(bool(check.get("ok")) or bool(check.get("optional")) for check in checks),
        "failed": [str(check["name"]) for check in checks if not check.get("ok") and not check.get("optional")],
        "skipped": [str(check["name"]) for check in checks if not check.get("ok") and check.get("optional")],
        "passed": [str(check["name"]) for check in checks if check.get("ok")],
        "checks": list(checks),
        "nextCommands": list(next_commands),
    }


def unique_strings(items: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        value = str(item)
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def redaction_pairs(root: Path = ROOT) -> list[tuple[str, str]]:
    temp_root = Path(tempfile.gettempdir())
    home_root = Path.home()
    candidates = [
        (root, "<repo>"),
        (root.resolve(), "<repo>"),
        (temp_root, "<tmp>"),
        (temp_root.resolve(), "<tmp>"),
        (home_root, "<home>"),
        (home_root.resolve(), "<home>"),
    ]
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for path, label in sorted(candidates, key=lambda item: len(str(item[0])), reverse=True):
        for value in (str(path), path.as_posix()):
            if not value or value == "/" or value in seen:
                continue
            seen.add(value)
            pairs.append((value, label))
    return pairs


def redact_public_text(value: str, *, root: Path = ROOT) -> str:
    redacted = value
    for source, replacement in redaction_pairs(root):
        redacted = redacted.replace(source, replacement)
    for pattern, replacement in SECRET_TEXT_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    for pattern in ABSOLUTE_PATH_PATTERNS:
        redacted = pattern.sub("<path>", redacted)
    if len(redacted) > PUBLIC_STRING_LIMIT:
        redacted = redacted[:PUBLIC_STRING_LIMIT] + "...<truncated>"
    return redacted


def redact_local_paths(value: Any, *, root: Path = ROOT) -> Any:
    if isinstance(value, dict):
        return {key: redact_local_paths(item, root=root) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_local_paths(item, root=root) for item in value]
    if isinstance(value, tuple):
        return [redact_local_paths(item, root=root) for item in value]
    if isinstance(value, str):
        return redact_public_text(value, root=root)
    return value


def public_release_payload(payload: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    redacted = redact_local_paths(payload, root=root)
    if not isinstance(redacted, dict):
        return {"visibility": "public-redacted", "redacted": True, "payload": redacted}
    return {
        **redacted,
        "visibility": "public-redacted",
        "redacted": True,
    }


def write_json_report(payload: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def same_output_path(left: Path, right: Path) -> bool:
    return left.expanduser().resolve(strict=False) == right.expanduser().resolve(strict=False)


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def git_remote_configured(root: Path) -> bool:
    if not (root / ".git").exists():
        return False
    result = subprocess.run(
        ["git", "remote"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def release_environment(root: Path = ROOT) -> dict[str, Any]:
    return {
        "system": platform.system(),
        "machine": platform.machine(),
        "gitRemoteConfigured": git_remote_configured(root),
        "ghAvailable": command_exists("gh"),
        "rustcAvailable": command_exists("rustc"),
        "cargoAvailable": command_exists("cargo"),
        "npmAvailable": command_exists("npm"),
    }


def estimated_remaining_payload(*, formal_ready: bool, blocker_summary: dict[str, list[str]]) -> dict[str, str]:
    if formal_ready:
        return {
            "beta": "0",
            "formal": "0",
            "localActionable": "0",
            "externalRelease": "0",
        }

    local_pending = bool(blocker_summary.get("localActionable"))
    external_pending = bool(blocker_summary.get("externalRequired") or blocker_summary.get("environment"))
    local = "1-2 local passes" if local_pending else "0"
    external = "1-2 release runs" if external_pending else "0"
    if local_pending and external_pending:
        formal = "local checks plus external release evidence"
    elif local_pending:
        formal = "local checks only"
    elif external_pending:
        formal = "external release evidence only"
    else:
        formal = "unknown"
    return {
        "beta": "0",
        "formal": formal,
        "localActionable": local,
        "externalRelease": external,
    }


def portable_package_runtime_tool() -> Any:
    from tools import check_portable_package_runtime

    return check_portable_package_runtime


def macos_app_launch_smoke_tool() -> Any:
    from tools import check_macos_app_launch_smoke

    return check_macos_app_launch_smoke


def runtime_fixture_tool() -> Any:
    from tools import prepare_runtime_fixture

    return prepare_runtime_fixture


def keychain_smoke_tool() -> Any:
    from tools import check_secret_store_keychain_smoke

    return check_secret_store_keychain_smoke


def release_evidence_manifest_issues(artifact: Path, checksum: Path, manifest: Path) -> list[str]:
    if not manifest.is_file():
        return [f"missing evidence manifest: {manifest}"]
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read evidence manifest: {exc}"]
    if not isinstance(payload, dict):
        return ["release evidence manifest must contain an object"]

    issues: list[str] = []
    expected_digest = write_release_checksum.sha256_file(artifact)
    schema = payload.get("schema")
    if schema == write_release_evidence_manifest.MACOS_APP_SCHEMA:
        expected_schema = write_release_evidence_manifest.MACOS_APP_SCHEMA
        runtime_profile = str(payload.get("runtimeProfile") or "full")
        expected_steps = list(
            write_release_evidence_manifest.MACOS_APP_LITE_REQUIRED_STEPS
            if runtime_profile == "lite"
            else write_release_evidence_manifest.MACOS_APP_REQUIRED_STEPS
        )
        if payload.get("platform") != "macos":
            issues.append("release evidence manifest platform mismatch")
    else:
        expected_schema = write_release_evidence_manifest.SCHEMA
        if payload.get("profile") == "lite":
            expected_steps = list(write_release_evidence_manifest.LITE_REQUIRED_RESULT_STEPS)
        else:
            expected_steps = list(write_release_evidence_manifest.REQUIRED_RESULT_STEPS)
    step_payloads = payload.get("steps")
    step_names = (
        [str(item.get("name") or "") for item in step_payloads if isinstance(item, dict)]
        if isinstance(step_payloads, list)
        else []
    )
    if payload.get("schema") != expected_schema:
        issues.append("release evidence manifest schema mismatch")
    if payload.get("artifactName") != artifact.name:
        issues.append("release evidence manifest artifactName mismatch")
    if payload.get("checksumName") != checksum.name:
        issues.append("release evidence manifest checksumName mismatch")
    if payload.get("sha256") != expected_digest:
        issues.append("release evidence manifest sha256 mismatch")
    if payload.get("sizeBytes") != artifact.stat().st_size:
        issues.append("release evidence manifest sizeBytes mismatch")
    if payload.get("contractOk") is not True:
        issues.append("release evidence manifest contractOk must be true")
    if payload.get("requiredSteps") != expected_steps:
        issues.append("release evidence manifest requiredSteps mismatch")
    if step_names != expected_steps:
        issues.append("release evidence manifest steps mismatch")
    if isinstance(step_payloads, list) and any(
        isinstance(item, dict) and item.get("ok") is not True for item in step_payloads
    ):
        issues.append("release evidence manifest contains failed steps")
    return issues


def release_evidence_manifest_step_ok(manifest: Path, *, schema: str, step_name: str) -> bool:
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict) or payload.get("schema") != schema:
        return False
    steps = payload.get("steps")
    if not isinstance(steps, list):
        return False
    return any(isinstance(item, dict) and item.get("name") == step_name and item.get("ok") is True for item in steps)


def keychain_smoke_payload(*, run: bool = False) -> dict[str, Any]:
    command = "python tools/check_secret_store_keychain_smoke.py --allow-write --preserve-existing --json"
    if not run:
        return {
            "ok": False,
            "failed": ["keychain smoke not executed with --keychain-smoke"],
            "checks": [
                {
                    "name": "keychain smoke not executed with --keychain-smoke",
                    "ok": False,
                    "detail": "run release_status_report.py --keychain-smoke on each native OS user session",
                }
            ],
            "nextCommands": [command],
        }
    check_secret_store_keychain_smoke = keychain_smoke_tool()
    checks, metadata = check_secret_store_keychain_smoke.collect_checks(allow_write=True, preserve_existing=True)
    payload = check_secret_store_keychain_smoke.result_payload(checks, **metadata)
    payload["nextCommands"] = [command]
    return payload


def pip_distribution_payload(
    *,
    root: Path = ROOT,
    python: Path = Path(sys.executable),
    run: bool = False,
    sdist_artifact: Path | None = None,
    build_sdist: bool = False,
    wheelhouse: Path | None = None,
    dist_dir: Path | None = None,
    install_venv: Path | None = None,
) -> dict[str, Any]:
    wheelhouse = wheelhouse or root / PYTHON_DIST_DIR
    dist_dir = dist_dir or root / PYTHON_DIST_DIR
    release_env = temp_path("culvia-release-env")
    release_python = release_env / ("Scripts/python.exe" if platform.system() == "Windows" else "bin/python")
    next_commands = [
        f"python -m venv {release_env}",
        f"{release_python} -m pip install -U pip",
        f"{release_python} -m pip install -e '.[release]'",
        *PYTHON_RELEASE_COMMANDS,
        f"{release_python} tools/release_smoke.py --build --wheelhouse {wheelhouse} --build-sdist --dist-dir {dist_dir} --install --venv {install_venv or temp_path('culvia-release-status-install')} --twine-check --strict",
        "python tools/release_status_report.py --release-smoke --sdist-artifact <culvia-*.tar.gz> --json",
    ]
    if not run:
        return gate_payload(
            [
                gate_check(
                    "pip distribution smoke not executed with --release-smoke",
                    False,
                    "run release_status_report.py --release-smoke with --build-sdist or --sdist-artifact before formal release",
                )
            ],
            next_commands=next_commands,
        )

    checks: list[dict[str, Any]] = []
    metadata_issues = release_smoke.check_project_metadata(root)
    checks.append(
        gate_check(
            "open-source package metadata is valid",
            not metadata_issues,
            "; ".join(metadata_issues)
            if metadata_issues
            else "LICENSE, pyproject metadata, classifiers, and URLs pass",
        )
    )

    wheel_path, wheel_build_issues, wheel_build_skips = release_smoke.build_wheel(
        root,
        wheelhouse,
        python,
        strict=True,
    )
    checks.append(
        gate_check(
            "wheel builds with pip --no-build-isolation",
            wheel_path is not None and not wheel_build_issues,
            "; ".join(wheel_build_issues or wheel_build_skips)
            if (wheel_build_issues or wheel_build_skips)
            else str(wheel_path),
        )
    )
    if wheel_path is not None:
        wheel_issues = release_smoke.check_wheel_archive(wheel_path, root)
        checks.append(
            gate_check(
                "wheel bundles web data, metadata, license, and entrypoints",
                not wheel_issues,
                "; ".join(wheel_issues) if wheel_issues else str(wheel_path),
            )
        )
        if install_venv is None:
            with tempfile.TemporaryDirectory(prefix="culvia-release-status-install-") as temp_dir:
                install_issues, install_skips = release_smoke.install_and_check_wheel(wheel_path, Path(temp_dir), root)
        else:
            install_issues, install_skips = release_smoke.install_and_check_wheel(wheel_path, install_venv, root)
        checks.append(
            gate_check(
                "installed wheel entrypoints and web data work",
                not install_issues,
                "; ".join(install_issues or install_skips) if (install_issues or install_skips) else str(wheel_path),
            )
        )
    else:
        checks.append(
            gate_check("wheel bundles web data, metadata, license, and entrypoints", False, "wheel was not built")
        )
        checks.append(gate_check("installed wheel entrypoints and web data work", False, "wheel was not built"))

    resolved_sdist = sdist_artifact
    if build_sdist:
        resolved_sdist, sdist_build_issues, sdist_build_skips = release_smoke.build_sdist(
            root,
            dist_dir,
            python,
            strict=True,
        )
        checks.append(
            gate_check(
                "sdist builds",
                resolved_sdist is not None and not sdist_build_issues,
                "; ".join(sdist_build_issues or sdist_build_skips)
                if (sdist_build_issues or sdist_build_skips)
                else str(resolved_sdist),
            )
        )
    elif resolved_sdist is None:
        checks.append(
            gate_check(
                "sdist release smoke executed",
                False,
                "pass --build-sdist or --sdist-artifact <culvia-*.tar.gz>",
            )
        )

    if resolved_sdist is not None:
        sdist_issues = release_smoke.check_sdist_archive(resolved_sdist, root)
        checks.append(
            gate_check(
                "sdist contains source files and no runtime artifacts",
                not sdist_issues,
                "; ".join(sdist_issues) if sdist_issues else str(resolved_sdist),
            )
        )
    else:
        checks.append(
            gate_check("sdist contains source files and no runtime artifacts", False, "sdist was not provided or built")
        )

    return gate_payload(checks, next_commands=next_commands)


def macos_app_launch_smoke_payload(
    *,
    bundle_dir: Path,
    timeout: float = 120.0,
) -> dict[str, Any]:
    check_macos_app_launch_smoke = macos_app_launch_smoke_tool()
    prepare_runtime_fixture = runtime_fixture_tool()
    app, app_error = check_macos_app_launch_smoke.resolve_app_path(bundle_dir)
    if app is None:
        return {
            "ok": False,
            "failed": ["macos app bundle exists"],
            "checks": [{"name": "macos app bundle exists", "ok": False, "detail": app_error}],
        }
    executable, executable_error = check_macos_app_launch_smoke.app_executable(app)
    if executable is None:
        return {
            "ok": False,
            "failed": ["macos app executable exists"],
            "checks": [{"name": "macos app executable exists", "ok": False, "detail": executable_error}],
            "app": str(app),
        }
    with tempfile.TemporaryDirectory(prefix="culvia-release-status-app-smoke-") as tmp:
        fixture = prepare_runtime_fixture.write_fixture(Path(tmp), count=4, force=False)
        return check_macos_app_launch_smoke.run_app_smoke(
            app=app,
            executable=executable,
            fixture=fixture,
            timeout=timeout,
            exit_after_ms=check_macos_app_launch_smoke.DEFAULT_EXIT_AFTER_MS,
        )


def macos_app_preflight_payload(*, root: Path = ROOT, require_clean: bool = True) -> dict[str, Any]:
    checks, meta = check_macos_app_preflight.collect_checks(root=root, require_clean=require_clean)
    return check_macos_app_preflight.result_payload(checks, meta)


def release_checksum_issues(artifact: Path, checksum_path: Path) -> list[str]:
    if not checksum_path.is_file():
        return [f"missing checksum: {checksum_path}"]
    expected_checksum = write_release_checksum.checksum_text(
        digest=write_release_checksum.sha256_file(artifact),
        artifact=artifact,
    )
    try:
        actual_checksum = checksum_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read checksum: {exc}"]
    if actual_checksum != expected_checksum:
        return [f"checksum mismatch: {checksum_path}"]
    return []


def macos_report(
    *,
    root: Path = ROOT,
    strict: bool = False,
    launch_runtime: bool = False,
    runtime_profile: str = "full",
) -> PlatformReport:
    is_lite = runtime_profile == "lite"
    bundle_dir = root / (MACOS_LITE_DIST_DIR if is_lite else MACOS_DIST_DIR)
    build_commands = MACOS_LITE_APP_BUILD_COMMANDS if is_lite else MACOS_APP_BUILD_COMMANDS
    non_strict_checks = check_macos_artifact_preflight.collect_checks(
        bundle_dir=bundle_dir,
        runtime_profile=runtime_profile,
    )
    strict_checks = check_macos_artifact_preflight.collect_checks(
        bundle_dir=bundle_dir,
        strict=True,
        runtime_profile=runtime_profile,
    )
    non_strict = check_payload(non_strict_checks)
    strict_payload = check_payload(strict_checks)
    missing = {"macos app artifact exists", "macos dmg artifact exists"} & set(non_strict.get("skipped", []))
    app_preflight = macos_app_preflight_payload(root=root, require_clean=bool(missing))
    blockers: list[str] = []
    if missing:
        status = "missing"
        blockers.extend(sorted(missing))
    elif strict_payload["ok"]:
        status = "ready"
    elif non_strict["ok"]:
        status = "partial"
        blockers.extend(strict_payload["failed"])
    else:
        status = "blocked"
        blockers.extend(non_strict["failed"])
    if strict and strict_payload["failed"]:
        blockers = sorted(set(blockers) | set(strict_payload["failed"]))
    evidence = [
        *[f"passed: macos app preflight: {name}" for name in app_preflight.get("passed", [])],
        *[f"skipped: macos app preflight: {name}" for name in app_preflight.get("skipped", [])],
        *[f"passed: {name}" for name in non_strict.get("passed", [])],
        *[f"skipped: {name}" for name in non_strict.get("skipped", [])],
    ]
    if not app_preflight["ok"]:
        blockers.extend(f"macos app preflight: {name}" for name in app_preflight["failed"])
        if status in {"missing", "partial", "ready"}:
            status = "blocked"
    manifest_app_smoke_ready = False
    if not missing and non_strict["ok"]:
        dmg_discovery = check_macos_artifact_preflight.resolve_dmg_path(bundle_dir, None)
        dmg_path = dmg_discovery.path
        if dmg_path is not None:
            checksum_path = Path(str(dmg_path) + ".sha256")
            checksum_issues = release_checksum_issues(dmg_path, checksum_path)
            if checksum_issues:
                blockers.extend(checksum_issues)
                status = "blocked"
            else:
                evidence.append(f"passed: release checksum matches: {checksum_path}")
                manifest_path = Path(str(dmg_path) + ".evidence.json")
                manifest_issues = release_evidence_manifest_issues(dmg_path, checksum_path, manifest_path)
                if manifest_issues:
                    blockers.extend(manifest_issues)
                    status = "blocked"
                else:
                    evidence.append(f"passed: release evidence manifest matches: {manifest_path}")
                    if is_lite:
                        manifest_app_smoke_ready = True
                        evidence.append("passed: lite evidence manifest")
                    else:
                        manifest_app_smoke_ready = release_evidence_manifest_step_ok(
                            manifest_path,
                            schema=write_release_evidence_manifest.MACOS_APP_SCHEMA,
                            step_name="macos app launch smoke",
                        )
                        if manifest_app_smoke_ready:
                            evidence.append("passed: app launch smoke: macos evidence manifest")
    app_smoke_ready = manifest_app_smoke_ready
    if not missing and not is_lite:
        if launch_runtime and platform.system() == "Darwin":
            app_smoke = macos_app_launch_smoke_payload(bundle_dir=bundle_dir)
            evidence.extend(f"passed: app launch smoke: {item['name']}" for item in app_smoke["checks"] if item["ok"])
            if app_smoke["ok"]:
                app_smoke_ready = True
            else:
                blockers.extend(f"app launch smoke: {name}" for name in app_smoke["failed"])
        elif not app_smoke_ready:
            blockers.append("app launch smoke runtime workflow not executed on native macOS runner")
    ready = strict_payload["ok"] and app_smoke_ready
    if status == "ready" and not ready:
        status = "partial"
    return PlatformReport(
        key="macosLite" if is_lite else "macos",
        label="macOS Lite .app/.dmg" if is_lite else "macOS .app/.dmg",
        status=status,
        ready=ready,
        evidence=evidence,
        blockers=blockers,
        nextCommands=[
            *build_commands,
            *(() if is_lite else tuple(MACOS_FORMAL_RELEASE_COMMANDS)),
        ],
    )


def portable_package_report(
    *,
    key: str,
    label: str,
    artifact: Path,
    preflight_arg: str,
    native_platform: str,
    platform_key: str | None = None,
    runtime_profile: str = "full",
    root: Path = ROOT,
    launch_runtime: bool = False,
) -> PlatformReport:
    platform_key = platform_key or key
    if not artifact.is_file():
        return PlatformReport(
            key=key,
            label=label,
            status="missing",
            ready=False,
            evidence=[],
            blockers=[f"missing artifact: {artifact}"],
            nextCommands=[
                f"python tools/desktop_release_contract.py --platform {platform_key}{profile_arg(runtime_profile)} --run --json"
            ],
        )

    if platform_key == "windows" and runtime_profile == "lite":
        preflight_checks = check_portable_package_preflight.collect_windows_lite_zip_checks(artifact)
    elif platform_key == "windows":
        preflight_checks = check_portable_package_preflight.collect_windows_zip_checks(artifact)
    elif runtime_profile == "lite":
        preflight_checks = check_portable_package_preflight.collect_linux_lite_tgz_checks(artifact)
    else:
        preflight_checks = check_portable_package_preflight.collect_linux_tgz_checks(artifact)
    preflight = check_portable_package_preflight.result_payload(preflight_checks)
    evidence = [f"passed: {item['name']}" for item in preflight["checks"] if item["ok"]]
    blockers: list[str] = []
    if not preflight["ok"]:
        return PlatformReport(
            key=key,
            label=label,
            status="blocked",
            ready=False,
            evidence=evidence,
            blockers=list(preflight["failed"]),
            nextCommands=[
                f"python tools/check_portable_package_preflight.py {preflight_arg} {artifact} --json",
            ],
        )

    checksum_path = Path(str(artifact) + ".sha256")
    checksum_command = f"python tools/write_release_checksum.py {artifact} --json"
    if not checksum_path.is_file():
        return PlatformReport(
            key=key,
            label=label,
            status="blocked",
            ready=False,
            evidence=evidence,
            blockers=[f"missing checksum: {checksum_path}"],
            nextCommands=[
                f"python tools/check_portable_package_preflight.py {preflight_arg} {artifact} --json",
                checksum_command,
            ],
        )
    expected_checksum = write_release_checksum.checksum_text(
        digest=write_release_checksum.sha256_file(artifact),
        artifact=artifact,
    )
    try:
        actual_checksum = checksum_path.read_text(encoding="utf-8")
    except OSError as exc:
        return PlatformReport(
            key=key,
            label=label,
            status="blocked",
            ready=False,
            evidence=evidence,
            blockers=[f"cannot read checksum: {exc}"],
            nextCommands=[
                f"python tools/check_portable_package_preflight.py {preflight_arg} {artifact} --json",
                checksum_command,
            ],
        )
    if actual_checksum != expected_checksum:
        return PlatformReport(
            key=key,
            label=label,
            status="blocked",
            ready=False,
            evidence=evidence,
            blockers=[f"checksum mismatch: {checksum_path}"],
            nextCommands=[
                f"python tools/check_portable_package_preflight.py {preflight_arg} {artifact} --json",
                checksum_command,
            ],
        )
    evidence.append(f"passed: release checksum matches: {checksum_path}")

    manifest_path = Path(str(artifact) + ".evidence.json")
    manifest_command = (
        f"python tools/desktop_release_contract.py --platform {platform_key}{profile_arg(runtime_profile)} --run --json"
    )
    manifest_issues = release_evidence_manifest_issues(artifact, checksum_path, manifest_path)
    if manifest_issues:
        return PlatformReport(
            key=key,
            label=label,
            status="blocked",
            ready=False,
            evidence=evidence,
            blockers=manifest_issues,
            nextCommands=[
                f"python tools/check_portable_package_preflight.py {preflight_arg} {artifact} --json",
                checksum_command,
                manifest_command,
            ],
        )
    evidence.append(f"passed: release evidence manifest matches: {manifest_path}")

    if runtime_profile == "lite":
        status = "ready"
        ready = True
    elif not launch_runtime:
        status = "partial"
        ready = False
        blockers.append(f"runtime launch not executed on native {native_platform} runner")
    else:
        check_portable_package_runtime = portable_package_runtime_tool()
        current_platform = check_portable_package_runtime.native_platform_key()
        should_launch = current_platform == native_platform
        runtime = check_portable_package_runtime.result_payload(
            check_portable_package_runtime.collect_checks(
                windows_zip=artifact if platform_key == "windows" else None,
                linux_tgz=artifact if platform_key == "linux" else None,
                launch=should_launch,
                root=root,
            )
        )
        evidence.extend(f"passed: {item['name']}" for item in runtime["checks"] if item["ok"])
        if runtime["ok"] and should_launch:
            status = "ready"
            ready = True
        elif runtime["ok"]:
            status = "partial"
            ready = False
            blockers.append(f"runtime launch not executed on native {native_platform} runner")
        else:
            status = "blocked"
            ready = False
            blockers.extend(runtime["failed"])

    next_commands = [
        f"python tools/check_portable_package_preflight.py {preflight_arg} {artifact} --json",
        checksum_command,
        manifest_command,
    ]
    if runtime_profile != "lite":
        next_commands.insert(
            1,
            f"python tools/check_portable_package_runtime.py {preflight_arg} {artifact} --exit-after-ms 20000 --json",
        )
    if status != "ready":
        next_commands = [manifest_command, *[command for command in next_commands if command != manifest_command]]
    return PlatformReport(
        key=key,
        label=label,
        status=status,
        ready=ready,
        evidence=evidence,
        blockers=blockers,
        nextCommands=next_commands,
    )


def profile_arg(runtime_profile: str) -> str:
    return " --profile lite" if runtime_profile == "lite" else ""


def windows_report(*, root: Path = ROOT, launch_runtime: bool = False) -> PlatformReport:
    contract = desktop_release_contract.platform_contract("windows", root=root)
    return portable_package_report(
        key="windows",
        label="Windows portable zip",
        platform_key="windows",
        runtime_profile="full",
        artifact=contract.archive,
        preflight_arg=contract.preflight_arg,
        native_platform="windows",
        root=root,
        launch_runtime=launch_runtime,
    )


def windows_lite_report(*, root: Path = ROOT) -> PlatformReport:
    contract = desktop_release_contract.platform_contract("windows", root=root, profile="lite")
    return portable_package_report(
        key="windowsLite",
        label="Windows Lite portable zip",
        platform_key="windows",
        runtime_profile="lite",
        artifact=contract.archive,
        preflight_arg=contract.preflight_arg,
        native_platform="windows",
        root=root,
        launch_runtime=False,
    )


def linux_report(*, root: Path = ROOT, launch_runtime: bool = False) -> PlatformReport:
    contract = desktop_release_contract.platform_contract("linux", root=root)
    return portable_package_report(
        key="linux",
        label="Linux portable tgz",
        platform_key="linux",
        runtime_profile="full",
        artifact=contract.archive,
        preflight_arg=contract.preflight_arg,
        native_platform="linux",
        root=root,
        launch_runtime=launch_runtime,
    )


def linux_lite_report(*, root: Path = ROOT) -> PlatformReport:
    contract = desktop_release_contract.platform_contract("linux", root=root, profile="lite")
    return portable_package_report(
        key="linuxLite",
        label="Linux Lite portable tgz",
        platform_key="linux",
        runtime_profile="lite",
        artifact=contract.archive,
        preflight_arg=contract.preflight_arg,
        native_platform="linux",
        root=root,
        launch_runtime=False,
    )


def report_to_dict(report: PlatformReport) -> dict[str, Any]:
    return {
        "key": report.key,
        "label": report.label,
        "status": report.status,
        "ready": report.ready,
        "evidence": report.evidence,
        "blockers": report.blockers,
        "nextCommands": report.nextCommands,
    }


def is_macos_report(report: PlatformReport) -> bool:
    return report.key in {"macos", "macosLite"}


def platform_blocker_category(report: PlatformReport, blocker: str) -> str:
    if is_macos_report(report) and blocker.startswith("macos app preflight:"):
        return "localActionable"
    if is_macos_report(report) and blocker in MACOS_APP_ARTIFACT_BLOCKERS:
        return "localActionable" if platform.system() == "Darwin" else "externalRequired"
    if is_macos_report(report) and blocker == "app launch smoke runtime workflow not executed on native macOS runner":
        return "localActionable" if platform.system() == "Darwin" else "externalRequired"
    if is_macos_report(report) and ("checksum" in blocker or "evidence manifest" in blocker):
        return "localActionable" if platform.system() == "Darwin" else "externalRequired"
    return "externalRequired"


def platform_blocker_next_commands(report: PlatformReport, blocker: str) -> list[str]:
    macos_build_commands = MACOS_LITE_APP_BUILD_COMMANDS if report.key == "macosLite" else MACOS_APP_BUILD_COMMANDS
    if is_macos_report(report) and blocker.startswith("macos app preflight:"):
        return [
            "python tools/check_macos_app_preflight.py --json",
            "python tools/clean_macos_app_artifacts.py --apply --json",
        ]
    if is_macos_report(report) and blocker in MACOS_APP_ARTIFACT_BLOCKERS:
        return macos_build_commands
    if is_macos_report(report) and blocker == "app launch smoke runtime workflow not executed on native macOS runner":
        return [
            "python tools/release_status_report.py --launch-runtime --json",
            "python tools/check_macos_app_launch_smoke.py --json",
        ]
    if is_macos_report(report) and ("checksum" in blocker or "evidence manifest" in blocker):
        return macos_build_commands
    if report.key == "macos" and blocker in MACOS_FORMAL_ARTIFACT_BLOCKERS:
        return MACOS_FORMAL_RELEASE_COMMANDS
    return report.nextCommands


def collect_report(
    *,
    root: Path = ROOT,
    focus: str = "all",
    launch_runtime: bool = False,
    keychain_smoke: bool = False,
    release_smoke_run: bool = False,
    sdist_artifact: Path | None = None,
    build_sdist: bool = False,
    wheelhouse: Path | None = None,
    dist_dir: Path | None = None,
    install_venv: Path | None = None,
    python: Path = Path(sys.executable),
) -> dict[str, Any]:
    readiness = check_desktop_readiness.result_payload(check_desktop_readiness.collect_checks(root))
    workflow = check_desktop_release_workflow.result_payload(check_desktop_release_workflow.collect_checks(root))
    keychain = keychain_smoke_payload(run=keychain_smoke)
    platforms = [
        macos_report(root=root, launch_runtime=launch_runtime),
        macos_report(root=root, launch_runtime=launch_runtime, runtime_profile="lite"),
        windows_report(root=root, launch_runtime=launch_runtime),
        windows_lite_report(root=root),
        linux_report(root=root, launch_runtime=launch_runtime),
        linux_lite_report(root=root),
    ]
    pip_distribution = pip_distribution_payload(
        root=root,
        python=python,
        run=release_smoke_run,
        sdist_artifact=sdist_artifact,
        build_sdist=build_sdist,
        wheelhouse=wheelhouse,
        dist_dir=dist_dir,
        install_venv=install_venv,
    )
    focus = focus if focus in {"all", "macos"} else "all"
    focused_platforms = {"macos", "macosLite"} if focus == "macos" else {item.key for item in platforms}
    environment = release_environment(root)
    blockers: list[str] = []
    deferred_blockers: list[str] = []
    blocker_summary: dict[str, list[str]] = {
        "localActionable": [],
        "externalRequired": [],
        "environment": [],
    }
    next_commands_by_category: dict[str, list[str]] = {
        "localActionable": [],
        "externalRequired": [],
        "environment": [],
    }
    if not readiness["ok"]:
        items = [f"desktop readiness: {name}" for name in readiness["failed"]]
        blockers.extend(items)
        blocker_summary["localActionable"].extend(items)
        next_commands_by_category["localActionable"].append("python tools/check_desktop_readiness.py --json")
    if not workflow["ok"]:
        items = [f"desktop workflow: {name}" for name in workflow["failed"]]
        blockers.extend(items)
        blocker_summary["localActionable"].extend(items)
        next_commands_by_category["localActionable"].append("python tools/check_desktop_release_workflow.py --json")
    if not keychain["ok"]:
        items = [f"keychain: {name}" for name in keychain["failed"]]
        blockers.extend(items)
        blocker_summary["externalRequired"].extend(items)
        next_commands_by_category["externalRequired"].extend(keychain.get("nextCommands", []))
    if not pip_distribution["ok"]:
        items = [f"pip distribution: {name}" for name in pip_distribution["failed"]]
        blockers.extend(items)
        blocker_summary["localActionable"].extend(items)
        next_commands_by_category["localActionable"].extend(pip_distribution.get("nextCommands", []))
    for item in platforms:
        if not item.ready:
            for blocker in item.blockers:
                name = f"{item.key}: {blocker}"
                if item.key not in focused_platforms:
                    deferred_blockers.append(name)
                    continue
                category = platform_blocker_category(item, blocker)
                blockers.append(name)
                blocker_summary[category].append(name)
                next_commands_by_category[category].extend(platform_blocker_next_commands(item, blocker))
    if not environment["gitRemoteConfigured"]:
        blocker = "release environment: git remote is not configured"
        blockers.append(blocker)
        blocker_summary["environment"].append(blocker)
        next_commands_by_category["environment"].append("git remote add origin <repo-url>")
    if not environment["ghAvailable"]:
        blocker = "release environment: gh CLI is not available"
        blockers.append(blocker)
        blocker_summary["environment"].append(blocker)
        next_commands_by_category["environment"].append("install GitHub CLI, then run gh auth login")

    blocker_summary = {key: unique_strings(values) for key, values in blocker_summary.items()}
    next_commands_by_category = {key: unique_strings(values) for key, values in next_commands_by_category.items()}
    if deferred_blockers:
        blocker_summary["deferred"] = unique_strings(deferred_blockers)
        deferred_commands: list[str] = []
        for item in platforms:
            if item.key not in focused_platforms and not item.ready:
                deferred_commands.extend(item.nextCommands)
        next_commands_by_category["deferred"] = unique_strings(deferred_commands)

    formal_ready = not blockers and not deferred_blockers and all(item.ready for item in platforms)
    focused_ready = not blockers and all(item.ready for item in platforms if item.key in focused_platforms)
    return {
        "ok": True,
        "focus": focus,
        "betaReady": True,
        "formalReady": formal_ready,
        "focusedReady": focused_ready,
        "estimatedRemaining": estimated_remaining_payload(
            formal_ready=focused_ready,
            blocker_summary=blocker_summary,
        ),
        "environment": environment,
        "gates": {
            "desktopReadiness": {
                "ok": readiness["ok"],
                "failed": readiness["failed"],
                "skipped": readiness["skipped"],
            },
            "desktopReleaseWorkflow": {
                "ok": workflow["ok"],
                "failed": workflow["failed"],
            },
            "keychainSmoke": {
                "ok": keychain["ok"],
                "failed": keychain["failed"],
                "nextCommands": keychain.get("nextCommands", []),
            },
            "pipDistribution": {
                "ok": pip_distribution["ok"],
                "failed": pip_distribution["failed"],
                "skipped": pip_distribution["skipped"],
                "passed": pip_distribution["passed"],
                "checks": pip_distribution["checks"],
                "nextCommands": pip_distribution.get("nextCommands", []),
            },
        },
        "platforms": {item.key: report_to_dict(item) for item in platforms},
        "blockers": blockers,
        "deferredBlockers": unique_strings(deferred_blockers),
        "blockerSummary": blocker_summary,
        "nextCommandsByCategory": next_commands_by_category,
        "nextCommands": unique_strings(
            [
                *next_commands_by_category["localActionable"],
                *next_commands_by_category["externalRequired"],
                *next_commands_by_category["environment"],
            ]
        ),
    }


def print_text_report(payload: dict[str, Any]) -> None:
    estimate = payload.get("estimatedRemaining") or {}
    focus = str(payload.get("focus") or "all")
    print(f"Focus: {focus}")
    print(f"Beta ready: {payload['betaReady']}")
    print(f"Formal ready: {payload['formalReady']}")
    if focus != "all":
        print(f"Focused ready: {payload.get('focusedReady')}")
    print(
        "Estimated remaining: "
        f"beta {estimate.get('beta', 'unknown')}, "
        f"local {estimate.get('localActionable', 'unknown')}, "
        f"external {estimate.get('externalRelease', 'unknown')}, "
        f"formal {estimate.get('formal', 'unknown')}"
    )
    for key, item in payload["platforms"].items():
        print(f"- {key}: {item['status']} ({'ready' if item['ready'] else 'not ready'})")
        for blocker in item["blockers"]:
            print(f"  blocker: {blocker}")
    if payload["blockers"]:
        print("Blockers:")
        for blocker in payload["blockers"]:
            print(f"- {blocker}")
    summary = payload.get("blockerSummary") or {}
    labels = {
        "localActionable": "Local actionable",
        "externalRequired": "External required",
        "environment": "Environment",
        "deferred": "Deferred",
    }
    for key in ("localActionable", "externalRequired", "environment", "deferred"):
        items = summary.get(key) or []
        if not items:
            continue
        print(f"{labels[key]} blockers:")
        for item in items:
            print(f"- {item}")
        commands = (payload.get("nextCommandsByCategory") or {}).get(key) or []
        for command in commands:
            print(f"  next: {command}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize current release readiness evidence and blockers.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--focus",
        choices=("all", "macos"),
        default="all",
        help="Scope readiness estimates to all platforms or the current macOS app release lane.",
    )
    parser.add_argument(
        "--launch-runtime",
        action="store_true",
        help="Run native runtime checks when artifacts exist on the matching OS, including macOS .app launch workflow and Windows/Linux portable packages.",
    )
    parser.add_argument(
        "--keychain-smoke",
        action="store_true",
        help="Run a native system keychain save/read/delete/restore smoke with a temporary sentinel secret.",
    )
    parser.add_argument(
        "--release-smoke",
        action="store_true",
        help="Run strict pip wheel/install release smoke and include the result in formal readiness.",
    )
    parser.add_argument(
        "--sdist-artifact",
        type=Path,
        default=None,
        help="Existing culvia-*.tar.gz source distribution to verify as release evidence.",
    )
    parser.add_argument(
        "--build-sdist", action="store_true", help="Build and verify an sdist when --release-smoke is enabled."
    )
    parser.add_argument("--wheelhouse", type=Path, default=None)
    parser.add_argument("--dist-dir", type=Path, default=None)
    parser.add_argument("--venv", type=Path, default=None, help="Venv path for release smoke install check.")
    parser.add_argument(
        "--python", type=Path, default=Path(sys.executable), help="Python executable used for release smoke probes."
    )
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when formalReady is false.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    parser.add_argument(
        "--redact-local-paths",
        action="store_true",
        help="Replace local paths and credential-like text with stable placeholders before printing or writing JSON.",
    )
    parser.add_argument(
        "--json-output", type=Path, default=None, help="Write the release status JSON payload to this path."
    )
    parser.add_argument(
        "--public-json-output",
        type=Path,
        default=None,
        help="Write a public-redacted release status JSON payload to this path.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if (
        args.json_output is not None
        and args.public_json_output is not None
        and same_output_path(args.json_output, args.public_json_output)
    ):
        raise SystemExit("--json-output and --public-json-output must write to different files")
    payload = collect_report(
        root=args.root,
        focus=args.focus,
        launch_runtime=args.launch_runtime,
        keychain_smoke=args.keychain_smoke,
        release_smoke_run=args.release_smoke,
        sdist_artifact=args.sdist_artifact,
        build_sdist=args.build_sdist,
        wheelhouse=args.wheelhouse,
        dist_dir=args.dist_dir,
        install_venv=args.venv,
        python=args.python,
    )
    if args.public_json_output is not None:
        write_json_report(public_release_payload(payload, root=args.root), args.public_json_output)
    if args.redact_local_paths:
        payload = public_release_payload(payload, root=args.root)
    if args.json_output is not None:
        write_json_report(payload, args.json_output)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_text_report(payload)
    ready = bool(payload.get("focusedReady")) if args.focus != "all" else bool(payload.get("formalReady"))
    return 0 if ready or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
