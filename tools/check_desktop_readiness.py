from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - project requires Python 3.11+.
    tomllib = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[1]
DESKTOP_CONTRACT_PATH = "desktop/tauri/desktop-shell.contract.json"
DESKTOP_PACKAGE_PATH = "desktop/tauri/package.json"
DESKTOP_PACKAGE_LOCK_PATH = "desktop/tauri/package-lock.json"
DESKTOP_CONFIG_PATH = "desktop/tauri/src-tauri/tauri.conf.json"
DESKTOP_CARGO_PATH = "desktop/tauri/src-tauri/Cargo.toml"
DESKTOP_CARGO_LOCK_PATH = "desktop/tauri/src-tauri/Cargo.lock"
DESKTOP_MAIN_PATH = "desktop/tauri/src-tauri/src/main.rs"
DESKTOP_SPLASH_PATH = "desktop/tauri/src-tauri/assets/splash.html"
DESKTOP_BUILD_RS_PATH = "desktop/tauri/src-tauri/build.rs"
DESKTOP_MACOS_ENTITLEMENTS_PATH = "desktop/tauri/src-tauri/entitlements.mac.plist"
DESKTOP_BACKEND_BUILD_PATH = "desktop/tauri/scripts/build-backend.py"
DESKTOP_HEADLESS_BUILD_PATH = "desktop/tauri/scripts/build-headless.py"
DESKTOP_LITE_HEADLESS_BUILD_PATH = "desktop/tauri/scripts/build-lite-headless.py"
DESKTOP_DEV_BACKEND_PATH = "desktop/tauri/scripts/start-dev-backend.py"
DESKTOP_BACKEND_ENTRY_PATH = "desktop/tauri/backend/server_entry.py"
PYTHON_SERVER_PATH = "culvia/server.py"
PYTHON_SUPERVISOR_PATH = "culvia/supervisor.py"
PYTHON_RUNTIME_MANAGER_PATH = "culvia/runtime_manager.py"
PYTHON_SECRET_STORE_PATH = "culvia/secret_store.py"
MACOS_APP_BUILD_PATH = "tools/build_macos_app.py"
MACOS_APP_PREFLIGHT_PATH = "tools/check_macos_app_preflight.py"
MACOS_ARTIFACT_PREFLIGHT_PATH = "tools/check_macos_artifact_preflight.py"
PORTABLE_PACKAGE_PREFLIGHT_PATH = "tools/check_portable_package_preflight.py"
PORTABLE_PACKAGE_RUNTIME_PATH = "tools/check_portable_package_runtime.py"
DESKTOP_RELEASE_CONTRACT_PATH = "tools/desktop_release_contract.py"
DESKTOP_RELEASE_WORKFLOW_CHECK_PATH = "tools/check_desktop_release_workflow.py"
RELEASE_STATUS_REPORT_PATH = "tools/release_status_report.py"
RELEASE_CHECKSUM_PATH = "tools/write_release_checksum.py"
RELEASE_EVIDENCE_PATH = "tools/write_release_evidence_manifest.py"
DESKTOP_RELEASE_WORKFLOW_PATH = ".github/workflows/desktop-release.yml"
DESKTOP_BACKEND_RESOURCE = "runtime/backend"


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    optional: bool = False


def read_text(root: Path, relative: str) -> str:
    return (root / relative).read_text(encoding="utf-8")


def pyproject_data(root: Path) -> dict[str, Any]:
    if tomllib is None:
        raise RuntimeError("Python 3.11+ is required because tomllib is unavailable.")
    return tomllib.loads(read_text(root, "pyproject.toml"))


def read_json(root: Path, relative: str) -> tuple[dict[str, Any], str]:
    path = root / relative
    if not path.exists():
        return {}, f"{relative} is missing."
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {}, f"{relative} is invalid JSON: {exc}"
    if not isinstance(payload, dict):
        return {}, f"{relative} must contain a JSON object."
    return payload, ""


def command_available(*names: str) -> bool:
    candidates = (
        Path("/opt/homebrew/opt/rustup/bin"),
        Path("/usr/local/opt/rustup/bin"),
        Path.home() / ".cargo" / "bin",
    )
    for name in names:
        if shutil.which(name):
            continue
        if not any((candidate / name).exists() for candidate in candidates):
            return False
    return True


def files_exist(root: Path, paths: Sequence[str]) -> tuple[bool, str]:
    missing = [path for path in paths if not (root / path).exists()]
    return not missing, "missing: " + ", ".join(missing) if missing else "all required files exist"


def script_keys(package: dict[str, Any]) -> set[str]:
    scripts = package.get("scripts", {})
    if not isinstance(scripts, dict):
        return set()
    return {str(key) for key in scripts}


def resource_declares_backend(config: dict[str, Any]) -> bool:
    bundle = config.get("bundle", {})
    resources = bundle.get("resources") if isinstance(bundle, dict) else None
    if isinstance(resources, dict):
        return DESKTOP_BACKEND_RESOURCE in resources or DESKTOP_BACKEND_RESOURCE in resources.values()
    if isinstance(resources, list):
        return DESKTOP_BACKEND_RESOURCE in resources
    return False


def collect_checks(root: Path = ROOT, *, strict_toolchain: bool = False) -> list[CheckResult]:
    data = pyproject_data(root)
    project = data.get("project", {}) if isinstance(data.get("project"), dict) else {}
    scripts = project.get("scripts", {}) if isinstance(project.get("scripts"), dict) else {}
    optional = project.get("optional-dependencies", {})
    optional = optional if isinstance(optional, dict) else {}
    desktop_runtime_deps = {str(item).lower() for item in optional.get("desktop-runtime", [])}
    desktop_deps = {str(item).lower() for item in optional.get("desktop", [])}

    contract, contract_error = read_json(root, DESKTOP_CONTRACT_PATH)
    runtime_profiles = contract.get("runtimeProfiles", {}) if isinstance(contract.get("runtimeProfiles"), dict) else {}
    runtime_modes = runtime_profiles.get("modes", {}) if isinstance(runtime_profiles.get("modes"), dict) else {}
    first_stage = (
        contract.get("firstStageReleaseArtifacts", {})
        if isinstance(contract.get("firstStageReleaseArtifacts"), dict)
        else {}
    )
    release_status = (
        contract.get("releaseStatusReport", {}) if isinstance(contract.get("releaseStatusReport"), dict) else {}
    )

    package, package_error = read_json(root, DESKTOP_PACKAGE_PATH)
    package_scripts = script_keys(package)

    tauri_config, tauri_error = read_json(root, DESKTOP_CONFIG_PATH)
    tauri_build = tauri_config.get("build", {}) if isinstance(tauri_config.get("build"), dict) else {}
    tauri_app = tauri_config.get("app", {}) if isinstance(tauri_config.get("app"), dict) else {}
    tauri_bundle = tauri_config.get("bundle", {}) if isinstance(tauri_config.get("bundle"), dict) else {}
    tauri_macos = tauri_bundle.get("macOS", {}) if isinstance(tauri_bundle.get("macOS"), dict) else {}
    tauri_windows = tauri_app.get("windows", []) if isinstance(tauri_app.get("windows"), list) else []

    required_files = (
        "README.md",
        "README.zh-CN.md",
        "docs/en/developer/architecture.md",
        "docs/en/developer/desktop-build.md",
        "docs/en/developer/release-checklist.md",
        "docs/zh-CN/developer/architecture.md",
        "docs/zh-CN/developer/desktop-build.md",
        "docs/zh-CN/developer/release-checklist.md",
        DESKTOP_PACKAGE_LOCK_PATH,
        DESKTOP_CARGO_PATH,
        DESKTOP_CARGO_LOCK_PATH,
        DESKTOP_MAIN_PATH,
        DESKTOP_SPLASH_PATH,
        DESKTOP_BUILD_RS_PATH,
        DESKTOP_MACOS_ENTITLEMENTS_PATH,
        DESKTOP_DEV_BACKEND_PATH,
        DESKTOP_HEADLESS_BUILD_PATH,
        DESKTOP_LITE_HEADLESS_BUILD_PATH,
        DESKTOP_BACKEND_BUILD_PATH,
        DESKTOP_BACKEND_ENTRY_PATH,
        PYTHON_SERVER_PATH,
        PYTHON_SUPERVISOR_PATH,
        PYTHON_RUNTIME_MANAGER_PATH,
        PYTHON_SECRET_STORE_PATH,
        MACOS_APP_BUILD_PATH,
        MACOS_APP_PREFLIGHT_PATH,
        MACOS_ARTIFACT_PREFLIGHT_PATH,
        PORTABLE_PACKAGE_PREFLIGHT_PATH,
        PORTABLE_PACKAGE_RUNTIME_PATH,
        DESKTOP_RELEASE_CONTRACT_PATH,
        DESKTOP_RELEASE_WORKFLOW_CHECK_PATH,
        DESKTOP_RELEASE_WORKFLOW_PATH,
        RELEASE_STATUS_REPORT_PATH,
        RELEASE_CHECKSUM_PATH,
        RELEASE_EVIDENCE_PATH,
    )
    required_files_ok, required_files_detail = files_exist(root, required_files)

    checks = [
        CheckResult(
            "desktop source files exist",
            required_files_ok,
            required_files_detail,
        ),
        CheckResult(
            "python package exposes desktop entrypoints",
            scripts.get("culvia-web") == "culvia.server:main"
            and scripts.get("culvia-supervisor") == "culvia.supervisor:main"
            and scripts.get("culvia") == "culvia.cli:main",
            "pyproject exposes CLI, Web server, and supervised desktop backend entrypoints.",
        ),
        CheckResult(
            "desktop optional dependencies are isolated",
            "pyinstaller>=6" in desktop_deps
            and "keyring>=25" in desktop_deps
            and "keyring>=25" in desktop_runtime_deps,
            "desktop build and runtime extras are declared outside base release tooling.",
        ),
        CheckResult(
            "desktop shell contract is valid",
            not contract_error
            and contract.get("kind") == "culvia-desktop-shell-contract"
            and contract.get("frontendMode") == "local-http"
            and contract.get("backendEntrypoint") == "culvia-supervisor"
            and contract.get("healthPath") == "/health"
            and contract.get("sameOriginApiRequired") is True,
            contract_error or "desktop contract declares local HTTP frontend, backend entrypoint, and health path.",
        ),
        CheckResult(
            "desktop runtime profiles are declared",
            runtime_profiles.get("status") == "implemented"
            and runtime_profiles.get("selectorEnv") == "CULVIA_DESKTOP_RUNTIME_MODE"
            and runtime_profiles.get("configFile") == "user data dir/runtime/runtime.json"
            and runtime_modes.get("full", {}).get("mustNotRequireUserPython") is True
            and runtime_modes.get("lite", {}).get("mustNotRequireUserPython") is False
            and runtime_profiles.get("pythonRuntimeManager", {}).get("module") == "culvia.runtime_manager",
            "contract declares full bundled runtime and lite app-managed virtualenv runtime.",
        ),
        CheckResult(
            "desktop release artifacts are declared",
            first_stage.get("windows", {}).get("tool") == "tools/build_windows_zip.py"
            and first_stage.get("linux", {}).get("tool") == "tools/build_linux_tgz.py"
            and first_stage.get("macOS", {}).get("tool") == "tools/build_macos_app.py"
            and release_status.get("tool") == RELEASE_STATUS_REPORT_PATH,
            "contract points to macOS, Windows, Linux, and release status tools.",
        ),
        CheckResult(
            "desktop npm package is reproducible",
            not package_error
            and package.get("private") is True
            and "@tauri-apps/cli" in package.get("devDependencies", {})
            and {
                "backend:dev",
                "backend:plan",
                "backend:build",
                "tauri:dev",
                "tauri:build",
                "tauri:build:headless",
                "tauri:build:lite:headless",
                "windows:zip:build",
                "windows:lite:zip:build",
                "linux:tgz:build",
                "linux:lite:tgz:build",
            }.issubset(package_scripts),
            package_error or "desktop package exposes dev, build, full release, and lite release scripts.",
        ),
        CheckResult(
            "desktop tauri config targets local backend",
            not tauri_error
            and tauri_config.get("identifier") == "io.github.culvia.culvia"
            and tauri_build.get("beforeDevCommand") == "npm run backend:dev"
            and tauri_build.get("devUrl") == "http://127.0.0.1:8501"
            and tauri_build.get("frontendDist") == "http://127.0.0.1:8501"
            and bool(tauri_windows)
            and tauri_windows[0].get("create") is False,
            tauri_error or "Tauri config loads the local Python backend and creates the main window after readiness.",
        ),
        CheckResult(
            "desktop full runtime resource is declared",
            not tauri_error and resource_declares_backend(tauri_config),
            tauri_error or "Tauri bundle declares runtime/backend for full desktop packages.",
        ),
        CheckResult(
            "macos bundle policy is declared",
            not tauri_error
            and tauri_macos.get("hardenedRuntime") is True
            and tauri_macos.get("entitlements") == "entitlements.mac.plist",
            tauri_error or "macOS bundle declares hardened runtime and entitlements file.",
        ),
    ]

    has_rust = command_available("rustc", "cargo")
    checks.append(
        CheckResult(
            "rust toolchain available",
            has_rust,
            "rustc/cargo available." if has_rust else "rustc/cargo not found; install Rust before desktop builds.",
            optional=not strict_toolchain,
        )
    )

    has_desktop_cli = command_available("npm")
    checks.append(
        CheckResult(
            "node/npm available for desktop shell cli",
            has_desktop_cli,
            "npm available for the project-local desktop CLI."
            if has_desktop_cli
            else "npm not found; install Node/npm before desktop shell development.",
            optional=not strict_toolchain,
        )
    )
    return checks


def result_payload(checks: Sequence[CheckResult]) -> dict[str, Any]:
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
    parser = argparse.ArgumentParser(description="Check desktop packaging prerequisites and repository contracts.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--strict-toolchain", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = result_payload(collect_checks(args.root, strict_toolchain=args.strict_toolchain))
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for check in payload["checks"]:
            if check["ok"]:
                status = "OK"
            elif check["optional"]:
                status = "SKIP"
            else:
                status = "FAIL"
            print(f"{status} {check['name']}: {check['detail']}")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
