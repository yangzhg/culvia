from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import build_linux_tgz, build_windows_zip, write_release_evidence_manifest


LINUX_TARGET = "x86_64-unknown-linux-gnu"
WINDOWS_TARGET = "x86_64-pc-windows-msvc"


@dataclass(frozen=True)
class ReleaseStep:
    name: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class PlatformContract:
    key: str
    profile: str
    host_system: str
    runner: str
    target: str
    archive: Path
    checksum: Path
    evidence_manifest: Path
    artifact_glob: str
    artifact_name: str
    desktop_binary: Path
    backend_binary: Path
    artifact_flag: str
    preflight_arg: str
    package_build_tool: Path
    runner_dependencies: tuple[str, ...]


def read_desktop_config() -> dict[str, Any]:
    return build_windows_zip.read_desktop_config()


def product_version() -> str:
    return build_windows_zip.product_version(read_desktop_config())


def platform_contract(key: str, *, root: Path = ROOT, profile: str = "full") -> PlatformContract:
    normalized = key.lower().strip()
    if ":" in normalized:
        normalized, profile = normalized.split(":", 1)
    profile = profile.lower().strip() or "full"
    if profile not in {"full", "lite"}:
        raise ValueError(f"Unsupported desktop release profile: {profile!r}. Use full or lite.")
    version = product_version()
    if normalized == "windows":
        output_dir = root / "dist" / ("windows-lite" if profile == "lite" else "windows")
        archive = output_dir / build_windows_zip.archive_name(
            version,
            WINDOWS_TARGET,
            runtime_profile=profile,
        )
        return PlatformContract(
            key="windows",
            profile=profile,
            host_system="Windows",
            runner="windows-latest",
            target=WINDOWS_TARGET,
            archive=archive,
            checksum=Path(str(archive) + ".sha256"),
            evidence_manifest=Path(str(archive) + ".evidence.json"),
            artifact_glob="dist/windows-lite/*.zip" if profile == "lite" else "dist/windows/*.zip",
            artifact_name="culvia-windows-lite-x64" if profile == "lite" else "culvia-windows-x64",
            desktop_binary=root / "desktop" / "tauri" / "src-tauri" / "target" / "release" / "culvia-desktop.exe",
            backend_binary=Path("")
            if profile == "lite"
            else build_windows_zip.default_backend_binary(WINDOWS_TARGET, root=root),
            artifact_flag="--windows-lite-zip-artifact" if profile == "lite" else "--windows-zip-artifact",
            preflight_arg="--windows-lite-zip" if profile == "lite" else "--windows-zip",
            package_build_tool=root / "tools" / "build_windows_zip.py",
            runner_dependencies=(
                "Python 3.11+",
                "Node.js 20+",
                "Rust stable MSVC toolchain",
                *(() if profile == "lite" else ("PyInstaller from .[desktop]",)),
                "desktop shell CLI from desktop/tauri/package-lock.json",
            ),
        )
    if normalized == "linux":
        output_dir = root / "dist" / ("linux-lite" if profile == "lite" else "linux")
        archive = output_dir / build_linux_tgz.archive_name(
            version,
            LINUX_TARGET,
            runtime_profile=profile,
        )
        return PlatformContract(
            key="linux",
            profile=profile,
            host_system="Linux",
            runner="ubuntu-latest",
            target=LINUX_TARGET,
            archive=archive,
            checksum=Path(str(archive) + ".sha256"),
            evidence_manifest=Path(str(archive) + ".evidence.json"),
            artifact_glob="dist/linux-lite/*.tar.gz" if profile == "lite" else "dist/linux/*.tar.gz",
            artifact_name="culvia-linux-lite-x64" if profile == "lite" else "culvia-linux-x64",
            desktop_binary=root / "desktop" / "tauri" / "src-tauri" / "target" / "release" / "culvia-desktop",
            backend_binary=Path("")
            if profile == "lite"
            else build_linux_tgz.default_backend_binary(LINUX_TARGET, root=root),
            artifact_flag="--linux-lite-tgz-artifact" if profile == "lite" else "--linux-tgz-artifact",
            preflight_arg="--linux-lite-tgz" if profile == "lite" else "--linux-tgz",
            package_build_tool=root / "tools" / "build_linux_tgz.py",
            runner_dependencies=(
                "Python 3.11+",
                "Node.js 20+",
                "Rust stable GNU toolchain",
                *(() if profile == "lite" else ("PyInstaller from .[desktop]",)),
                "desktop shell CLI from desktop/tauri/package-lock.json",
                "Linux desktop shell packages: libwebkit2gtk-4.1-dev, libgtk-3-dev, libayatana-appindicator3-dev, librsvg2-dev, patchelf, xvfb",
            ),
        )
    raise ValueError(f"Unsupported desktop release platform: {key!r}. Use windows or linux.")


def native_platform_key() -> str | None:
    system = platform.system().lower()
    if system.startswith("win"):
        return "windows"
    if system == "linux":
        return "linux"
    return None


def npm_executable(contract: PlatformContract) -> str:
    return "npm.cmd" if contract.key == "windows" else "npm"


def collect_steps(
    contract: PlatformContract, *, python: Path = Path(sys.executable), root: Path = ROOT
) -> list[ReleaseStep]:
    backend_script = root / "desktop" / "tauri" / "scripts" / "build-backend.py"
    package_tool = contract.package_build_tool
    npm = npm_executable(contract)
    if contract.profile == "lite":
        return [
            ReleaseStep("install python release extras", (str(python), "-m", "pip", "install", "-e", ".[release]")),
            ReleaseStep("install desktop npm dependencies", (npm, "--prefix", "desktop/tauri", "ci")),
            ReleaseStep(
                "desktop shell lite build",
                (str(python), str(root / "desktop" / "tauri" / "scripts" / "build-lite-headless.py")),
            ),
            ReleaseStep(
                "lite package plan",
                (
                    str(python),
                    str(package_tool),
                    "--check-plan",
                    "--runtime-profile",
                    "lite",
                    "--target",
                    contract.target,
                    "--desktop-binary",
                    str(contract.desktop_binary),
                    "--json",
                ),
            ),
            ReleaseStep(
                "lite package build",
                (
                    str(python),
                    str(package_tool),
                    "--build",
                    "--runtime-profile",
                    "lite",
                    "--target",
                    contract.target,
                    "--desktop-binary",
                    str(contract.desktop_binary),
                    "--json",
                ),
            ),
            ReleaseStep(
                "lite package artifact preflight",
                (
                    str(python),
                    str(root / "tools" / "check_portable_package_preflight.py"),
                    contract.preflight_arg,
                    str(contract.archive),
                    "--json",
                ),
            ),
            ReleaseStep(
                "write release checksum",
                (
                    str(python),
                    str(root / "tools" / "write_release_checksum.py"),
                    str(contract.archive),
                    "--output",
                    str(contract.checksum),
                    "--json",
                ),
            ),
        ]
    return [
        ReleaseStep("install python desktop extras", (str(python), "-m", "pip", "install", "-e", ".[desktop]")),
        ReleaseStep("install desktop npm dependencies", (npm, "--prefix", "desktop/tauri", "ci")),
        ReleaseStep(
            "backend build plan",
            (str(python), str(backend_script), "--check-plan", "--target", contract.target, "--json"),
        ),
        ReleaseStep(
            "backend build",
            (str(python), str(backend_script), "--build", "--target", contract.target, "--json"),
        ),
        ReleaseStep(
            "backend smoke",
            (
                str(python),
                str(root / "tools" / "check_backend_smoke.py"),
                "--binary",
                str(contract.backend_binary),
                "--timeout",
                "90",
                "--json",
            ),
        ),
        ReleaseStep("desktop shell build", (npm, "--prefix", "desktop/tauri", "run", "tauri:build")),
        ReleaseStep(
            "portable package plan",
            (
                str(python),
                str(package_tool),
                "--check-plan",
                "--target",
                contract.target,
                "--desktop-binary",
                str(contract.desktop_binary),
                "--backend-binary",
                str(contract.backend_binary),
                "--json",
            ),
        ),
        ReleaseStep(
            "portable package build",
            (
                str(python),
                str(package_tool),
                "--build",
                "--target",
                contract.target,
                "--desktop-binary",
                str(contract.desktop_binary),
                "--backend-binary",
                str(contract.backend_binary),
                "--json",
            ),
        ),
        ReleaseStep(
            "portable package artifact preflight",
            (
                str(python),
                str(root / "tools" / "check_portable_package_preflight.py"),
                contract.preflight_arg,
                str(contract.archive),
                "--json",
            ),
        ),
        ReleaseStep(
            "portable package runtime verification",
            (
                str(python),
                str(root / "tools" / "check_portable_package_runtime.py"),
                contract.preflight_arg,
                str(contract.archive),
                "--timeout",
                "90",
                "--exit-after-ms",
                "20000",
                "--json",
            ),
        ),
        ReleaseStep(
            "formal package gate",
            (
                str(python),
                str(root / "tools" / "formal_gate.py"),
                contract.artifact_flag,
                str(contract.archive),
                "--skip-release-smoke",
                "--skip-unit-tests",
            ),
        ),
        ReleaseStep(
            "write release checksum",
            (
                str(python),
                str(root / "tools" / "write_release_checksum.py"),
                str(contract.archive),
                "--output",
                str(contract.checksum),
                "--json",
            ),
        ),
    ]


def command_payload(step: ReleaseStep) -> dict[str, Any]:
    return {"name": step.name, "command": list(step.command)}


def plan_payload(
    contract: PlatformContract, *, python: Path = Path(sys.executable), root: Path = ROOT
) -> dict[str, Any]:
    steps = collect_steps(contract, python=python, root=root)
    return {
        "ok": True,
        "platform": contract.key,
        "profile": contract.profile,
        "runner": contract.runner,
        "target": contract.target,
        "archive": str(contract.archive),
        "checksum": str(contract.checksum),
        "evidenceManifest": str(contract.evidence_manifest),
        "artifactName": contract.artifact_name,
        "artifactGlob": contract.artifact_glob,
        "desktopBinary": str(contract.desktop_binary),
        "backendBinary": "" if contract.profile == "lite" else str(contract.backend_binary),
        "runnerDependencies": list(contract.runner_dependencies),
        "steps": [command_payload(step) for step in steps],
        "uploadRule": "Upload only the verified final archive, its SHA-256 checksum, and its release evidence manifest.",
    }


def ensure_native_platform(contract: PlatformContract) -> list[str]:
    current = native_platform_key()
    if current != contract.key:
        return [
            (
                f"{contract.key} release contract must run on {contract.host_system}; "
                f"current platform is {platform.system() or 'unknown'}."
            )
        ]
    return []


def run_step(step: ReleaseStep, *, root: Path = ROOT) -> dict[str, Any]:
    started = time.monotonic()
    result = subprocess.run(list(step.command), cwd=root, text=True, capture_output=True, check=False)
    payload: dict[str, Any] = {
        "name": step.name,
        "command": list(step.command),
        "returncode": int(result.returncode),
        "seconds": round(time.monotonic() - started, 3),
        "ok": result.returncode == 0,
    }
    if result.stdout:
        payload["stdoutTail"] = result.stdout[-4000:]
    if result.stderr:
        payload["stderrTail"] = result.stderr[-4000:]
    return payload


def run_contract(
    contract: PlatformContract, *, python: Path = Path(sys.executable), root: Path = ROOT, progress: bool = False
) -> dict[str, Any]:
    platform_issues = ensure_native_platform(contract)
    if platform_issues:
        payload = plan_payload(contract, python=python, root=root)
        payload["ok"] = False
        payload["issues"] = platform_issues
        payload["results"] = []
        return payload

    results: list[dict[str, Any]] = []
    steps = collect_steps(contract, python=python, root=root)
    progress_key = f"{contract.key}-lite-release" if contract.profile == "lite" else f"{contract.key}-release"
    for index, step in enumerate(steps, start=1):
        if progress:
            print(
                f"[{progress_key}] {index}/{len(steps)} {step.name} ...",
                file=sys.stderr,
                flush=True,
            )
        result = run_step(step, root=root)
        results.append(result)
        if progress:
            status = "OK" if result["ok"] else "FAIL"
            print(
                f"[{progress_key}] {index}/{len(steps)} {status} {step.name} ({result['seconds']}s)",
                file=sys.stderr,
                flush=True,
            )
        if not result["ok"]:
            payload = plan_payload(contract, python=python, root=root)
            payload["ok"] = False
            payload["failed"] = [result["name"]]
            payload["results"] = results
            return payload

    payload = plan_payload(contract, python=python, root=root)
    payload["results"] = results
    evidence = write_release_evidence_manifest.write_manifest_from_contract_payload(
        payload,
        output=contract.evidence_manifest,
    )
    payload["evidenceManifestResult"] = evidence
    if not evidence["ok"]:
        payload["ok"] = False
        payload["failed"] = ["write release evidence manifest"]
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan or run the Windows/Linux desktop release package contract.")
    parser.add_argument("--platform", choices=("windows", "linux"), required=True)
    parser.add_argument("--profile", choices=("full", "lite"), default="full")
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--check-plan", action="store_true", help="Print the release contract plan without running it.")
    parser.add_argument("--run", action="store_true", help="Run the release contract on the matching native platform.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    return parser


def print_failed_tail(result: dict[str, Any]) -> None:
    stdout_tail = str(result.get("stdoutTail") or "").strip()
    stderr_tail = str(result.get("stderrTail") or "").strip()
    if stdout_tail:
        print("stdout:")
        print(stdout_tail)
    if stderr_tail:
        print("stderr:")
        print(stderr_tail)


def print_text(payload: dict[str, Any], *, contract: PlatformContract, plan: bool = False) -> None:
    status = "OK" if payload["ok"] else "FAIL"
    profile = " Lite" if contract.profile == "lite" else ""
    print(f"{status} {contract.key}{profile} desktop release contract: {payload['archive']}")
    results = payload.get("results") or []
    if results:
        for result in results:
            step_status = "OK" if result["ok"] else "FAIL"
            print(f"{step_status} {result['name']} ({result.get('seconds', 0)}s)")
            if not result["ok"]:
                print_failed_tail(result)
    elif plan:
        for step in payload.get("steps", []):
            print(f"- {step['name']}: {' '.join(step['command'])}")
    evidence = payload.get("evidenceManifestResult") or {}
    if evidence:
        evidence_status = "OK" if evidence.get("ok") else "FAIL"
        print(f"{evidence_status} release evidence manifest: {evidence.get('manifestPath', '')}")
        for issue in evidence.get("issues", []):
            print(f"FAIL {issue}")
    for issue in payload.get("issues", []):
        print(f"FAIL {issue}")
    if not plan:
        print_artifact_summary(payload)


def print_artifact_summary(payload: dict[str, Any]) -> None:
    archive_value = str(payload.get("archive") or "").strip()
    archive = Path(archive_value) if archive_value else None
    entries = [
        ("dist", str(archive.parent) if archive is not None else ""),
        ("archive", archive_value),
        ("checksum", str(payload.get("checksum") or "").strip()),
        ("evidence", str(payload.get("evidenceManifest") or "").strip()),
    ]
    visible_entries = [(label, value) for label, value in entries if value]
    if not visible_entries:
        return
    print("Artifacts:")
    for label, value in visible_entries:
        print(f"  {label}: {value}")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    contract = platform_contract(args.platform, profile=args.profile)
    payload = (
        run_contract(contract, python=args.python, progress=True)
        if args.run
        else plan_payload(contract, python=args.python)
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_text(payload, contract=contract, plan=not args.run)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
