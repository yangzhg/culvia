from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import subprocess
import sys
import tempfile
import time
import zipfile
from contextlib import contextmanager
from email.parser import Parser
from pathlib import Path
from typing import Any, Iterator, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import (
    check_macos_artifact_preflight,
    check_portable_package_preflight,
    check_portable_package_runtime,
    write_release_checksum,
)


SCHEMA = "culvia-lite-runtime-evidence-v1"
PLATFORM_SYSTEMS = {"macos": "Darwin", "windows": "Windows", "linux": "Linux"}
TARGET_SUFFIXES = {"macos": "apple-darwin", "windows": "pc-windows-msvc", "linux": "unknown-linux-gnu"}


class VerificationFailure(ValueError):
    pass


def require(checks: list[dict[str, Any]], name: str, ok: bool, detail: str) -> None:
    checks.append({"name": name, "ok": bool(ok), "detail": detail})
    if not ok:
        raise VerificationFailure(detail)


def wheel_version(wheel: Path) -> str:
    with zipfile.ZipFile(wheel) as archive:
        metadata = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata) != 1:
            raise ValueError("candidate wheel must contain exactly one distribution METADATA")
        parsed = Parser().parsestr(archive.read(metadata[0]).decode("utf-8"))
    version = str(parsed.get("Version") or "").strip()
    if parsed.get("Name") != "culvia" or not version or wheel.name != f"culvia-{version}-py3-none-any.whl":
        raise ValueError("candidate must be the versioned Culvia universal wheel")
    return version


def file_evidence(path: Path) -> dict[str, Any]:
    return {"name": path.name, "sha256": write_release_checksum.sha256_file(path), "sizeBytes": path.stat().st_size}


def host_target(package_platform: str) -> str:
    arch = check_portable_package_runtime.native_arch_key()
    if arch not in {"aarch64", "x86_64"}:
        raise ValueError(f"unsupported native architecture: {arch}")
    return f"{arch}-{TARGET_SUFFIXES[package_platform]}"


def run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=True, timeout=120)


def detach_dmg(mount: Path) -> None:
    for attempt in range(3):
        try:
            run_command(["hdiutil", "detach", str(mount)])
            return
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if attempt < 2:
                time.sleep(0.25)
    run_command(["hdiutil", "detach", "-force", str(mount)])


@contextmanager
def package_workspace(checks: list[dict[str, Any]]) -> Iterator[Path]:
    destination = Path(tempfile.mkdtemp(prefix="culvia-lite-package-"))
    try:
        yield destination
    finally:
        if (destination / "mount").is_mount():
            checks.append(
                {
                    "name": "temporary package workspace cleanup",
                    "ok": False,
                    "detail": f"DMG still mounted; retained temporary workspace: {destination}",
                }
            )
        else:
            error = check_portable_package_runtime.remove_tree_with_retries(destination)
            checks.append(
                {"name": "temporary package workspace cleanup", "ok": not error, "detail": error or "removed"}
            )


@contextmanager
def unpack_macos_dmg(artifact: Path, destination: Path) -> Iterator[Path]:
    mount = destination / "mount"
    mount.mkdir()
    attached = False
    try:
        run_command(["hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mount), str(artifact)])
        attached = True
        apps = list(mount.glob("*.app"))
        if len(apps) != 1 or apps[0].is_symlink() or not apps[0].is_dir():
            raise ValueError("candidate DMG must contain exactly one real app bundle")
        app = destination / apps[0].name
        run_command(["ditto", str(apps[0]), str(app)])
        yield app
    finally:
        if attached or mount.is_mount():
            detach_dmg(mount)


def macos_launcher(app: Path, artifact: Path, *, version: str, target: str, checks: list[dict[str, Any]]) -> Path:
    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    executable_name = str(info.get("CFBundleExecutable") or "")
    require(
        checks,
        "macOS executable stays inside the app bundle",
        bool(executable_name) and Path(executable_name).name == executable_name,
        "Info.plist executable must be a basename",
    )
    config = {**check_macos_artifact_preflight.read_desktop_config(), "version": version}
    ok, detail, executable = check_macos_artifact_preflight.app_bundle_detail(app, config=config)
    require(checks, "macOS bundle matches candidate wheel version", ok, detail)
    assert executable is not None
    preflight = check_macos_artifact_preflight.collect_checks(
        app=app, dmg=artifact, runtime_profile="lite", config=config
    )
    payload = check_macos_artifact_preflight.result_payload(preflight)
    require(checks, "macOS candidate artifact preflight", payload["ok"], json.dumps(payload))
    architectures = run_command(["lipo", "-archs", str(executable)]).stdout.split()
    expected = "arm64" if target.startswith("aarch64-") else "x86_64"
    require(checks, "macOS executable matches native architecture", expected in architectures, str(architectures))
    return executable


def portable_launcher(
    artifact: Path,
    destination: Path,
    *,
    package_platform: str,
    version: str,
    target: str,
    checks: list[dict[str, Any]],
) -> Path:
    if package_platform == "windows":
        preflight = check_portable_package_preflight.collect_windows_lite_zip_checks(artifact)
        extract = check_portable_package_runtime.extract_windows_zip
    else:
        preflight = check_portable_package_preflight.collect_linux_lite_tgz_checks(artifact)
        extract = check_portable_package_runtime.extract_linux_tgz
    result = check_portable_package_preflight.result_payload(preflight)
    require(checks, "Lite portable artifact preflight", result["ok"], json.dumps(result))
    package, issues = extract(artifact, destination)
    require(checks, "Lite archive extracts safely", package is not None and not issues, "; ".join(issues))
    assert package is not None
    manifest, error = check_portable_package_runtime.read_manifest(package)
    require(checks, "Lite package manifest loads", manifest is not None, error)
    assert manifest is not None
    require(checks, "package declares Lite runtime", manifest.get("runtimeProfile") == "lite", "runtimeProfile=lite")
    require(
        checks,
        "package version matches candidate wheel",
        manifest.get("version") == version,
        f"package={manifest.get('version')!r}, wheel={version!r}",
    )
    require(
        checks,
        "package target matches native runner",
        manifest.get("target") == target,
        f"package={manifest.get('target')!r}, runner={target!r}",
    )
    launcher = check_portable_package_runtime.safe_join(package, manifest.get("launcher"))
    require(
        checks, "packaged Lite launcher exists", launcher is not None and launcher.is_file(), "safe manifest launcher"
    )
    assert launcher is not None
    return launcher


def verify_package(
    *,
    artifact: Path,
    package_platform: str,
    wheel: Path,
    python: Path,
    timeout: float = 900,
    exit_after_ms: int = 20000,
) -> dict[str, Any]:
    from tools.lite_runtime_smoke import run_lite_smoke

    checks: list[dict[str, Any]] = []
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "ok": False,
        "runtimeProfile": "lite",
        "platform": package_platform,
        "checks": checks,
        "firstLaunch": {"ok": False, "status": "not_run"},
        "reuseLaunch": {"ok": False, "status": "not_run"},
        "workflowRunId": os.environ.get("GITHUB_RUN_ID", ""),
        "workflowSha": os.environ.get("GITHUB_SHA", ""),
    }
    artifact, wheel, python = artifact.absolute(), wheel.absolute(), python.absolute()
    try:
        require(
            checks,
            "Lite smoke runs on native target OS",
            platform.system() == PLATFORM_SYSTEMS[package_platform],
            f"requested={package_platform}, native={platform.system()}",
        )
        payload["artifact"], payload["wheel"] = file_evidence(artifact), file_evidence(wheel)
        sidecar = Path(str(artifact) + ".sha256")
        expected_checksum = write_release_checksum.checksum_text(
            digest=payload["artifact"]["sha256"], artifact=artifact
        )
        require(
            checks,
            "candidate package checksum matches",
            sidecar.is_file() and sidecar.read_text(encoding="utf-8") == expected_checksum,
            f"SHA-256 sidecar for {artifact.name}",
        )
        version = wheel_version(wheel)
        target = host_target(package_platform)
        payload.update(version=version, target=target)
        require(checks, "base Python exists", python.is_file(), str(python))
        with package_workspace(checks) as destination:

            def launch(executable: Path) -> None:
                runtime = destination / "smoke"
                runtime.mkdir()
                result = run_lite_smoke(
                    launcher=executable,
                    expected_version=version,
                    expected_target=target,
                    wheel=wheel,
                    python=python,
                    work_dir=runtime,
                    timeout=timeout,
                    exit_after_ms=exit_after_ms,
                )
                checks.extend(result.get("checks", []))
                payload["firstLaunch"] = result.get("firstLaunch") or {"ok": False, "status": "not_run"}
                payload["reuseLaunch"] = result.get("reuseLaunch") or {"ok": False, "status": "not_run"}
                require(
                    checks,
                    "Lite first launch and runtime reuse pass",
                    result.get("ok") is True
                    and payload["firstLaunch"].get("ok") is True
                    and payload["reuseLaunch"].get("ok") is True,
                    "; ".join(result.get("failed", [])) or "fresh installation and installation-disabled restart",
                )

            if package_platform == "macos":
                with unpack_macos_dmg(artifact, destination) as app:
                    launch(macos_launcher(app, artifact, version=version, target=target, checks=checks))
            else:
                launch(
                    portable_launcher(
                        artifact,
                        destination,
                        package_platform=package_platform,
                        version=version,
                        target=target,
                        checks=checks,
                    )
                )
    except VerificationFailure:
        pass
    except Exception as exc:  # noqa: BLE001 - failure is persisted even when extraction or launch raises.
        checks.append(
            {"name": "Lite package verification completes", "ok": False, "detail": f"{type(exc).__name__}: {exc}"}
        )
    payload["failed"] = [item["name"] for item in checks if not item["ok"]]
    payload["ok"] = bool(checks) and not payload["failed"]
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify a Lite desktop package installs and reuses its candidate wheel."
    )
    package = parser.add_mutually_exclusive_group(required=True)
    package.add_argument("--macos-dmg", type=Path)
    package.add_argument("--windows-zip", type=Path)
    package.add_argument("--linux-tgz", type=Path)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument(
        "--python", required=True, type=Path, help="Base Python 3.11+ used by the desktop shell to create its venv."
    )
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--exit-after-ms", type=int, default=20000)
    parser.add_argument("--output", type=Path, help="Persist the result, including failures, as JSON evidence.")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    package_platform, artifact = next(
        (name, path)
        for name, path in (("macos", args.macos_dmg), ("windows", args.windows_zip), ("linux", args.linux_tgz))
        if path
    )
    output = args.output or Path(str(artifact) + ".lite-runtime.json")
    protected = (
        artifact,
        args.wheel,
        args.python,
        Path(str(artifact) + ".sha256"),
        Path(str(artifact) + ".evidence.json"),
    )
    if any(
        output.resolve() == path.resolve() or (output.exists() and path.exists() and output.samefile(path))
        for path in protected
    ):
        raise SystemExit("runtime evidence must not overwrite the package, wheel, interpreter, or existing sidecars")
    payload = verify_package(
        artifact=artifact,
        package_platform=package_platform,
        wheel=args.wheel,
        python=args.python,
        timeout=max(1, args.timeout),
        exit_after_ms=max(1, args.exit_after_ms),
    )
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=output.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(text + "\n")
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(text if args.json else f"{'OK' if payload['ok'] else 'FAIL'} Lite package runtime: {output}")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
