from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import check_macos_artifact_preflight, write_release_checksum, write_release_evidence_manifest

APPLE_SIGNING_IDENTITY_ENV = "APPLE_SIGNING_IDENTITY"
BACKEND_CODESIGN_IDENTITY_ENV = "CULVIA_MACOS_BACKEND_CODESIGN_IDENTITY"
AD_HOC_IDENTITY = "-"
DEFAULT_OUTPUT_SUBDIR = Path("dist") / "macos"
DEFAULT_LITE_OUTPUT_SUBDIR = Path("dist") / "macos-lite"
MACOS_APP_PREFLIGHT_STEP = "macos app preflight"
MACOS_APP_CLEANUP_SCRIPT = "tools/clean_macos_app_artifacts.py"
STREAMED_PROGRESS_STEPS = {
    "install desktop npm dependencies",
    "build macos backend",
    "build macos app and dmg",
    "build macos lite app and dmg",
    "macos app launch smoke",
}
MACOS_DMG_BUILD_STEPS = {
    "build macos app and dmg",
    "build macos lite app and dmg",
}
EXTRA_TOOLCHAIN_DIRECTORIES = (
    Path.home() / ".cargo" / "bin",
    Path("/opt/homebrew/opt/rustup/bin"),
    Path("/usr/local/opt/rustup/bin"),
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
)


@dataclass(frozen=True)
class MacosBuildStep:
    name: str
    command: tuple[str, ...]


def npm_executable(*, system: str | None = None) -> str:
    current = (system or platform.system()).lower()
    return "npm.cmd" if current.startswith("win") else "npm"


def tail_text(value: str, *, max_chars: int = 2000) -> str:
    if len(value) <= max_chars:
        return value
    return value[-max_chars:]


def parse_json_output(value: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def progress_line(prefix: str, message: str) -> None:
    print(f"[{prefix}] {message}", file=sys.stderr, flush=True)


def toolchain_environment(env: Mapping[str, str]) -> dict[str, str]:
    updated = dict(env)
    existing_path = updated.get("PATH", "")
    existing_parts = [part for part in existing_path.split(os.pathsep) if part]
    extra_parts = [str(path) for path in EXTRA_TOOLCHAIN_DIRECTORIES if path.is_dir()]
    merged_parts = [*extra_parts, *existing_parts]
    deduped = list(dict.fromkeys(merged_parts))
    if deduped:
        updated["PATH"] = os.pathsep.join(deduped)
    return updated


def macos_build_environment(env: Mapping[str, str], identity: str | None) -> dict[str, str]:
    updated = toolchain_environment(env)
    selected = (identity or "").strip()
    if selected and selected != AD_HOC_IDENTITY:
        updated[APPLE_SIGNING_IDENTITY_ENV] = selected
        updated[BACKEND_CODESIGN_IDENTITY_ENV] = selected
    return updated


def is_lite_profile(runtime_profile: str) -> bool:
    return runtime_profile.strip().lower() == "lite"


def resolve_output_dir(*, root: Path, output_dir: Path | None, runtime_profile: str = "full") -> Path:
    selected = DEFAULT_LITE_OUTPUT_SUBDIR if output_dir is None and is_lite_profile(runtime_profile) else output_dir
    selected = DEFAULT_OUTPUT_SUBDIR if selected is None else selected
    return selected if selected.is_absolute() else root / selected


def collect_steps(
    *,
    root: Path = ROOT,
    python: Path = Path(sys.executable),
    npm_action: str = "ci",
    clean_first: bool = False,
    require_apple_development: bool = False,
    skip_launch_smoke: bool = False,
    strict_release_signing: bool = False,
    strict_artifacts: bool = False,
    runtime_profile: str = "full",
) -> list[MacosBuildStep]:
    root = root.resolve()
    npm = npm_executable()
    preflight_command = [
        str(python),
        str(root / "tools" / "check_macos_app_preflight.py"),
        "--json",
    ]
    if require_apple_development:
        preflight_command.append("--require-apple-development")
    steps: list[MacosBuildStep] = []
    if clean_first:
        steps.append(
            MacosBuildStep(
                "clean macos app artifacts",
                (
                    str(python),
                    str(root / MACOS_APP_CLEANUP_SCRIPT),
                    "--apply",
                    "--json",
                ),
            )
        )
    if strict_release_signing:
        steps.append(
            MacosBuildStep(
                "macos release signing preflight",
                (
                    str(python),
                    str(root / "tools" / "check_desktop_release_preflight.py"),
                    "--strict-signing",
                    "--json",
                ),
            )
        )
    steps.append(MacosBuildStep(MACOS_APP_PREFLIGHT_STEP, tuple(preflight_command)))
    if npm_action != "skip":
        steps.append(
            MacosBuildStep(
                "install desktop npm dependencies",
                (npm, "--prefix", "desktop/tauri", npm_action),
            )
        )
    artifact_preflight_command = [
        str(python),
        str(root / "tools" / "check_macos_artifact_preflight.py"),
        "--json",
    ]
    if is_lite_profile(runtime_profile):
        artifact_preflight_command.extend(("--runtime-profile", "lite"))
    if strict_artifacts:
        artifact_preflight_command.append("--strict")
    if is_lite_profile(runtime_profile):
        steps.extend(
            [
                MacosBuildStep(
                    "build macos lite app and dmg",
                    (str(python), str(root / "desktop" / "tauri" / "scripts" / "build-lite-headless.py")),
                ),
                MacosBuildStep("macos artifact preflight", tuple(artifact_preflight_command)),
            ]
        )
    else:
        steps.extend(
            [
                MacosBuildStep(
                    "build macos backend",
                    (
                        str(python),
                        str(root / "desktop" / "tauri" / "scripts" / "build-backend.py"),
                        "--build",
                        "--json",
                    ),
                ),
                MacosBuildStep(
                    "build macos app and dmg",
                    (npm, "--prefix", "desktop/tauri", "run", "tauri:build:headless"),
                ),
                MacosBuildStep("macos artifact preflight", tuple(artifact_preflight_command)),
            ]
        )
    if not skip_launch_smoke and not is_lite_profile(runtime_profile):
        steps.append(
            MacosBuildStep(
                "macos app launch smoke",
                (
                    str(python),
                    str(root / "tools" / "check_macos_app_launch_smoke.py"),
                    "--json",
                ),
            )
        )
    return steps


def step_payload(step: MacosBuildStep) -> dict[str, Any]:
    return {"name": step.name, "command": list(step.command)}


def plan_payload(
    *,
    root: Path = ROOT,
    python: Path = Path(sys.executable),
    npm_action: str = "ci",
    clean_first: bool = False,
    require_apple_development: bool = False,
    skip_launch_smoke: bool = False,
    strict_release_signing: bool = False,
    strict_artifacts: bool = False,
    output_dir: Path | None = None,
    runtime_profile: str = "full",
) -> dict[str, Any]:
    output_dir = resolve_output_dir(root=root.resolve(), output_dir=output_dir, runtime_profile=runtime_profile)
    steps = collect_steps(
        root=root,
        python=python,
        npm_action=npm_action,
        clean_first=clean_first,
        require_apple_development=require_apple_development,
        skip_launch_smoke=skip_launch_smoke,
        strict_release_signing=strict_release_signing,
        strict_artifacts=strict_artifacts,
        runtime_profile=runtime_profile,
    )
    return {
        "ok": True,
        "root": str(root.resolve()),
        "runtimeProfile": "lite" if is_lite_profile(runtime_profile) else "full",
        "npmAction": npm_action,
        "cleanFirst": clean_first,
        "requireAppleDevelopment": require_apple_development,
        "skipLaunchSmoke": skip_launch_smoke,
        "strictReleaseSigning": strict_release_signing,
        "strictArtifacts": strict_artifacts,
        "outputDir": str(output_dir),
        "steps": [step_payload(step) for step in steps],
    }


def pipe_reader(pipe: Any, collector: list[str], *, prefix: str) -> None:
    try:
        for line in iter(pipe.readline, ""):
            collector.append(line)
            print(f"[{prefix}] {line}", file=sys.stderr, end="", flush=True)
    finally:
        pipe.close()


def run_streamed_step(
    step: MacosBuildStep, *, root: Path, env: Mapping[str, str], progress_prefix: str = "macos-release"
) -> dict[str, Any]:
    started = time.monotonic()
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    try:
        process = subprocess.Popen(  # noqa: S603 - commands are repository build steps, not shell input.
            list(step.command),
            cwd=root,
            env=dict(env),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )
    except FileNotFoundError as exc:
        seconds = round(time.monotonic() - started, 3)
        return {
            "name": step.name,
            "command": list(step.command),
            "ok": False,
            "returncode": 127,
            "seconds": seconds,
            "stdoutTail": "",
            "stderrTail": tail_text(str(exc)),
        }

    readers = [
        threading.Thread(
            target=pipe_reader,
            args=(process.stdout, stdout_lines),
            kwargs={"prefix": f"{progress_prefix}:stdout"},
            daemon=True,
        ),
        threading.Thread(
            target=pipe_reader,
            args=(process.stderr, stderr_lines),
            kwargs={"prefix": f"{progress_prefix}:stderr"},
            daemon=True,
        ),
    ]
    for reader in readers:
        reader.start()
    returncode = process.wait()
    for reader in readers:
        reader.join()
    seconds = round(time.monotonic() - started, 3)
    return {
        "name": step.name,
        "command": list(step.command),
        "ok": returncode == 0,
        "returncode": returncode,
        "seconds": seconds,
        "stdoutTail": tail_text("".join(stdout_lines)),
        "stderrTail": tail_text("".join(stderr_lines)),
    }


def run_step(
    step: MacosBuildStep,
    *,
    root: Path,
    env: Mapping[str, str],
    stream_output: bool = False,
    progress_prefix: str = "macos-release",
) -> dict[str, Any]:
    if stream_output:
        return run_streamed_step(step, root=root, env=env, progress_prefix=progress_prefix)
    started = time.monotonic()
    result = subprocess.run(
        list(step.command),
        cwd=root,
        env=dict(env),
        text=True,
        capture_output=True,
        check=False,
    )
    seconds = round(time.monotonic() - started, 3)
    return {
        "name": step.name,
        "command": list(step.command),
        "ok": result.returncode == 0,
        "returncode": result.returncode,
        "seconds": seconds,
        "stdoutTail": tail_text(result.stdout),
        "stderrTail": tail_text(result.stderr),
    }


def local_step_result(
    name: str, command: Sequence[str], *, started: float, ok: bool, detail: str = ""
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": name,
        "command": list(command),
        "ok": ok,
        "returncode": 0 if ok else 1,
        "seconds": round(time.monotonic() - started, 3),
    }
    if detail:
        payload["stdoutTail"] = tail_text(detail)
    return payload


def bundle_dir(root: Path) -> Path:
    return root / "desktop" / "tauri" / "src-tauri" / "target" / "release" / "bundle"


def resolve_macos_artifacts(*, root: Path) -> tuple[Path | None, Path | None, str]:
    artifacts_dir = bundle_dir(root)
    app_discovery = check_macos_artifact_preflight.resolve_app_path(artifacts_dir, None)
    dmg_discovery = check_macos_artifact_preflight.resolve_dmg_path(artifacts_dir, None)
    issues: list[str] = []
    if app_discovery.issue:
        issues.append(app_discovery.issue.detail)
    if dmg_discovery.issue:
        issues.append(dmg_discovery.issue.detail)
    if app_discovery.path is None:
        issues.append(f"No .app bundle found under {artifacts_dir}.")
    if dmg_discovery.path is None:
        issues.append(f"No .dmg found under {artifacts_dir}.")
    return app_discovery.path, dmg_discovery.path, "; ".join(issues)


def macos_dmg_arch_suffix(machine: str | None = None) -> str:
    current = (machine or platform.machine()).lower()
    if current in {"arm64", "aarch64"}:
        return "aarch64"
    if current in {"x86_64", "amd64"}:
        return "x64"
    return current or "macos"


def fallback_macos_dmg_path(*, root: Path) -> Path:
    config = check_macos_artifact_preflight.read_desktop_config(
        root / "desktop" / "tauri" / "src-tauri" / "tauri.conf.json"
    )
    product_name = str(config.get("productName") or "Culvia").strip() or "Culvia"
    version = str(config.get("version") or "0.0.0").strip() or "0.0.0"
    safe_product_name = "_".join(product_name.split())
    return bundle_dir(root) / "dmg" / f"{safe_product_name}_{version}_{macos_dmg_arch_suffix()}.dmg"


def recover_macos_dmg_build(
    step: MacosBuildStep,
    *,
    root: Path,
    env: Mapping[str, str],
    progress: bool = False,
    progress_prefix: str = "macos-release",
) -> dict[str, Any] | None:
    if step.name not in MACOS_DMG_BUILD_STEPS:
        return None

    artifacts_dir = bundle_dir(root)
    app_discovery = check_macos_artifact_preflight.resolve_app_path(artifacts_dir, None)
    if app_discovery.path is None:
        started = time.monotonic()
        detail = app_discovery.issue.detail if app_discovery.issue else f"No .app bundle found under {artifacts_dir}."
        return local_step_result(
            step.name,
            ("fallback-macos-dmg", str(artifacts_dir)),
            started=started,
            ok=False,
            detail=detail,
        )

    dmg_discovery = check_macos_artifact_preflight.resolve_dmg_path(artifacts_dir, None)
    if dmg_discovery.path is not None and dmg_discovery.path.is_file() and dmg_discovery.path.stat().st_size > 0:
        started = time.monotonic()
        return local_step_result(
            step.name,
            ("reuse-existing-macos-dmg", str(dmg_discovery.path)),
            started=started,
            ok=True,
            detail=json.dumps({"app": str(app_discovery.path), "dmg": str(dmg_discovery.path)}, ensure_ascii=False),
        )

    if platform.system() != "Darwin":
        started = time.monotonic()
        return local_step_result(
            step.name,
            ("hdiutil", "create"),
            started=started,
            ok=False,
            detail="Fallback DMG creation requires macOS hdiutil.",
        )

    dmg = fallback_macos_dmg_path(root=root)
    dmg.parent.mkdir(parents=True, exist_ok=True)
    remove_existing_path(dmg)
    command = (
        "hdiutil",
        "create",
        "-volname",
        app_discovery.path.stem,
        "-srcfolder",
        str(app_discovery.path),
        "-ov",
        "-format",
        "UDZO",
        str(dmg),
    )
    if progress:
        progress_line(progress_prefix, f"recovering {step.name} with hdiutil fallback ...")
    result = run_step(
        MacosBuildStep(step.name, command),
        root=root,
        env=env,
        stream_output=progress,
        progress_prefix=progress_prefix,
    )
    result["fallback"] = "hdiutil-create-from-app"
    return result


def make_removable(path: Path) -> None:
    try:
        path.chmod(os.stat(path, follow_symlinks=False).st_mode | stat.S_IWUSR)
    except OSError:
        pass
    if hasattr(os, "chflags"):
        try:
            os.chflags(path, 0, follow_symlinks=False)
        except (OSError, TypeError):
            pass


def remove_existing_path(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_dir() and not path.is_symlink():
        for child in sorted(path.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            make_removable(child)
        make_removable(path)
        shutil.rmtree(path)
        return
    make_removable(path)
    path.unlink()


def copy_path_without_extended_attributes(source: Path, destination: Path) -> None:
    if source.is_symlink():
        destination.symlink_to(os.readlink(source))
        return
    with source.open("rb") as source_file, destination.open("wb") as destination_file:
        shutil.copyfileobj(source_file, destination_file, length=1024 * 1024)
    shutil.copymode(source, destination, follow_symlinks=False)


def copy_tree_without_extended_attributes(source: Path, destination: Path) -> None:
    remove_existing_path(destination)
    destination.mkdir(parents=True)
    for current, dir_names, file_names in os.walk(source):
        current_path = Path(current)
        target_dir = destination / current_path.relative_to(source)
        target_dir.mkdir(parents=True, exist_ok=True)
        try:
            target_dir.chmod(os.stat(current_path, follow_symlinks=False).st_mode & 0o777)
        except OSError:
            pass
        for name in tuple(dir_names):
            child = current_path / name
            if child.is_symlink():
                copy_path_without_extended_attributes(child, target_dir / name)
                dir_names.remove(name)
        for name in file_names:
            copy_path_without_extended_attributes(current_path / name, target_dir / name)


def stage_macos_release_artifacts(*, app: Path, dmg: Path, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    staged_app = output_dir / app.name
    staged_dmg = output_dir / dmg.name
    copy_tree_without_extended_attributes(app, staged_app)
    remove_existing_path(staged_dmg)
    copy_path_without_extended_attributes(dmg, staged_dmg)
    return staged_app.resolve(), staged_dmg.resolve()


def write_macos_evidence(
    *,
    root: Path,
    results: list[dict[str, Any]],
    selected_identity: str,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    output_dir = resolve_output_dir(root=root.resolve(), output_dir=output_dir)
    app, dmg, artifact_issue = resolve_macos_artifacts(root=root)
    checksum_path = Path(str(dmg) + ".sha256") if dmg is not None else None
    manifest_path = Path(str(dmg) + ".evidence.json") if dmg is not None else None
    checksum_command = (
        str(root / "tools" / "write_release_checksum.py"),
        str(dmg or ""),
        "--json",
    )
    if app is None or dmg is None:
        results.append(
            local_step_result(
                "write release checksum",
                checksum_command,
                started=time.monotonic(),
                ok=False,
                detail=artifact_issue,
            )
        )
        return {
            "ok": False,
            "failedStep": "write release checksum",
            "selectedIdentity": selected_identity,
            "steps": results,
            "app": str(app or ""),
            "dmg": str(dmg or ""),
            "outputDir": str(output_dir),
            "checksum": str(checksum_path or ""),
            "evidenceManifest": str(manifest_path or ""),
        }

    stage_started = time.monotonic()
    stage_command = (
        "stage-macos-release-artifacts",
        str(app),
        str(dmg),
        str(output_dir),
    )
    try:
        app, dmg = stage_macos_release_artifacts(app=app, dmg=dmg, output_dir=output_dir)
    except OSError as exc:
        results.append(
            local_step_result(
                "stage macos release artifacts",
                stage_command,
                started=stage_started,
                ok=False,
                detail=str(exc),
            )
        )
        return {
            "ok": False,
            "failedStep": "stage macos release artifacts",
            "selectedIdentity": selected_identity,
            "steps": results,
            "app": str(app),
            "dmg": str(dmg),
            "outputDir": str(output_dir),
            "checksum": "",
            "evidenceManifest": "",
        }
    results.append(
        local_step_result(
            "stage macos release artifacts",
            stage_command,
            started=stage_started,
            ok=True,
            detail=json.dumps({"app": str(app), "dmg": str(dmg)}, ensure_ascii=False),
        )
    )

    checksum_path = Path(str(dmg) + ".sha256")
    manifest_path = Path(str(dmg) + ".evidence.json")
    checksum_command = (
        str(root / "tools" / "write_release_checksum.py"),
        str(dmg),
        "--json",
    )
    checksum_started = time.monotonic()
    checksum = write_release_checksum.write_checksum(artifact=dmg)
    machine = platform.machine()
    target = "aarch64-apple-darwin" if machine == "arm64" else f"{machine}-apple-darwin"
    results.append(
        local_step_result(
            "write release checksum",
            checksum_command,
            started=checksum_started,
            ok=bool(checksum.get("ok")),
            detail=json.dumps(checksum, ensure_ascii=False),
        )
    )
    payload: dict[str, Any] = {
        "ok": bool(checksum.get("ok")),
        "platform": "macos",
        "runner": "local-macos",
        "target": target if platform.system() == "Darwin" else "macos",
        "app": str(app),
        "dmg": str(dmg),
        "archive": str(dmg),
        "outputDir": str(output_dir),
        "checksum": str(checksum.get("checksumPath") or checksum_path),
        "selectedIdentity": selected_identity,
        "results": results,
    }
    evidence = write_release_evidence_manifest.write_macos_app_manifest(payload)
    payload["evidenceManifestResult"] = evidence
    payload["evidenceManifest"] = str(evidence.get("manifestPath") or manifest_path)
    payload["steps"] = results
    if not evidence["ok"]:
        payload["ok"] = False
        payload["failedStep"] = "write release evidence manifest"
    else:
        payload["failedStep"] = ""
    return payload


def write_macos_lite_evidence(
    *,
    root: Path,
    results: list[dict[str, Any]],
    selected_identity: str,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    output_dir = resolve_output_dir(root=root.resolve(), output_dir=output_dir, runtime_profile="lite")
    app, dmg, artifact_issue = resolve_macos_artifacts(root=root)
    if app is None or dmg is None:
        return {
            "ok": False,
            "failedStep": "resolve macos lite artifacts",
            "selectedIdentity": selected_identity,
            "steps": results,
            "app": str(app or ""),
            "dmg": str(dmg or ""),
            "outputDir": str(output_dir),
            "checksum": "",
            "evidenceManifest": "",
            "issues": [artifact_issue],
        }

    stage_started = time.monotonic()
    stage_command = (
        "stage-macos-lite-release-artifacts",
        str(app),
        str(dmg),
        str(output_dir),
    )
    try:
        app, dmg = stage_macos_release_artifacts(app=app, dmg=dmg, output_dir=output_dir)
    except OSError as exc:
        results.append(
            local_step_result(
                "stage macos lite release artifacts",
                stage_command,
                started=stage_started,
                ok=False,
                detail=str(exc),
            )
        )
        return {
            "ok": False,
            "failedStep": "stage macos lite release artifacts",
            "selectedIdentity": selected_identity,
            "steps": results,
            "app": str(app),
            "dmg": str(dmg),
            "outputDir": str(output_dir),
            "checksum": "",
            "evidenceManifest": "",
        }
    results.append(
        local_step_result(
            "stage macos lite release artifacts",
            stage_command,
            started=stage_started,
            ok=True,
            detail=json.dumps({"app": str(app), "dmg": str(dmg)}, ensure_ascii=False),
        )
    )

    checksum_started = time.monotonic()
    checksum = write_release_checksum.write_checksum(artifact=dmg)
    results.append(
        local_step_result(
            "write release checksum",
            (
                str(root / "tools" / "write_release_checksum.py"),
                str(dmg),
                "--json",
            ),
            started=checksum_started,
            ok=bool(checksum.get("ok")),
            detail=json.dumps(checksum, ensure_ascii=False),
        )
    )
    checksum_path = Path(str(checksum.get("checksumPath") or Path(str(dmg) + ".sha256")))
    manifest_path = Path(str(dmg) + ".evidence.json")
    machine = platform.machine()
    target = "aarch64-apple-darwin" if machine == "arm64" else f"{machine}-apple-darwin"
    payload: dict[str, Any] = {
        "ok": bool(checksum.get("ok")),
        "platform": "macos",
        "runtimeProfile": "lite",
        "runner": "local-macos",
        "target": target if platform.system() == "Darwin" else "macos",
        "app": str(app),
        "dmg": str(dmg),
        "archive": str(dmg),
        "outputDir": str(output_dir),
        "checksum": str(checksum_path),
        "selectedIdentity": selected_identity,
        "results": results,
        "steps": results,
    }
    if payload["ok"]:
        evidence = write_release_evidence_manifest.write_macos_app_manifest(payload)
        payload["evidenceManifestResult"] = evidence
        payload["evidenceManifest"] = str(evidence.get("manifestPath") or manifest_path)
        if not evidence["ok"]:
            payload["ok"] = False
            payload["failedStep"] = "write release evidence manifest"
        else:
            payload["failedStep"] = ""
    else:
        payload["evidenceManifest"] = str(manifest_path)
        payload["failedStep"] = "write release checksum"
    return payload


def run_macos_build(
    *,
    root: Path = ROOT,
    python: Path = Path(sys.executable),
    npm_action: str = "ci",
    clean_first: bool = False,
    require_apple_development: bool = False,
    skip_launch_smoke: bool = False,
    strict_release_signing: bool = False,
    strict_artifacts: bool = False,
    runtime_profile: str = "full",
    env: Mapping[str, str] | None = None,
    progress: bool = False,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    output_dir = resolve_output_dir(root=root, output_dir=output_dir, runtime_profile=runtime_profile)
    steps = collect_steps(
        root=root,
        python=python,
        npm_action=npm_action,
        clean_first=clean_first,
        require_apple_development=require_apple_development,
        skip_launch_smoke=skip_launch_smoke,
        strict_release_signing=strict_release_signing,
        strict_artifacts=strict_artifacts,
        runtime_profile=runtime_profile,
    )
    current_env = toolchain_environment(os.environ if env is None else env)
    if is_lite_profile(runtime_profile):
        current_env["CULVIA_DESKTOP_DEFAULT_RUNTIME_MODE"] = "lite"
    executed: list[dict[str, Any]] = []
    selected_identity = ""
    progress_prefix = "macos-lite-release" if is_lite_profile(runtime_profile) else "macos-release"
    for index, step in enumerate(steps, start=1):
        if progress:
            stream_note = " with live output" if step.name in STREAMED_PROGRESS_STEPS else ""
            progress_line(progress_prefix, f"{index}/{len(steps)} {step.name}{stream_note} ...")
        result = run_step(
            step,
            root=root,
            env=current_env,
            stream_output=progress and step.name in STREAMED_PROGRESS_STEPS,
            progress_prefix=progress_prefix,
        )
        executed.append(result)
        if progress:
            status = "OK" if result["ok"] else "FAIL"
            progress_line(progress_prefix, f"{index}/{len(steps)} {status} {step.name} ({result['seconds']}s)")
        if not result["ok"]:
            recovery = recover_macos_dmg_build(
                step,
                root=root,
                env=current_env,
                progress=progress,
                progress_prefix=progress_prefix,
            )
            if recovery is not None:
                executed.append(recovery)
                result = recovery
                if progress:
                    status = "OK" if result["ok"] else "FAIL"
                    progress_line(
                        progress_prefix,
                        f"{index}/{len(steps)} {status} {step.name} recovery ({result['seconds']}s)",
                    )
        if step.name == MACOS_APP_PREFLIGHT_STEP and result["ok"]:
            preflight = parse_json_output(str(result.get("stdoutTail") or ""))
            if preflight is not None:
                selected_identity = str(preflight.get("selectedIdentity") or "")
                current_env = macos_build_environment(current_env, selected_identity)
        if not result["ok"]:
            return {
                "ok": False,
                "failedStep": step.name,
                "selectedIdentity": selected_identity,
                "steps": executed,
                "outputDir": str(output_dir),
            }
    payload = {
        "ok": True,
        "failedStep": "",
        "selectedIdentity": selected_identity,
        "runtimeProfile": "lite" if is_lite_profile(runtime_profile) else "full",
        "steps": executed,
    }
    if is_lite_profile(runtime_profile):
        evidence_payload = write_macos_lite_evidence(
            root=root,
            results=executed,
            selected_identity=selected_identity,
            output_dir=output_dir,
        )
        return {
            **payload,
            **evidence_payload,
        }
    if skip_launch_smoke:
        return payload
    evidence_payload = write_macos_evidence(
        root=root,
        results=executed,
        selected_identity=selected_identity,
        output_dir=output_dir,
    )
    return {
        **payload,
        **evidence_payload,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build and verify the local macOS desktop app/dmg.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--npm", choices=("ci", "install", "skip"), default="ci")
    parser.add_argument(
        "--clean-first", action="store_true", help="Remove ignored generated artifacts before preflight and build."
    )
    parser.add_argument(
        "--require-apple-development",
        action="store_true",
        help="Fail preflight unless an Apple Development signing identity is visible.",
    )
    parser.add_argument("--skip-launch-smoke", action="store_true")
    parser.add_argument(
        "--strict-release-signing",
        action="store_true",
        help="Fail unless Developer ID signing and notarization inputs are configured.",
    )
    parser.add_argument(
        "--strict-artifacts",
        action="store_true",
        help="Fail artifact preflight on missing Gatekeeper or notarization/stapler checks.",
    )
    parser.add_argument("--runtime-profile", choices=("full", "lite"), default="full")
    parser.add_argument("--check-plan", action="store_true")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for final .app, .dmg, checksum, and evidence artifacts.",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def print_text(payload: dict[str, Any], *, plan: bool = False) -> None:
    profile = str(payload.get("runtimeProfile") or "full")
    label = "macOS Lite app build" if is_lite_profile(profile) else "macOS app build"
    if plan:
        print(f"{label} plan:")
        if payload.get("outputDir"):
            print(f"output: {payload['outputDir']}")
        for index, step in enumerate(payload["steps"], start=1):
            print(f"{index}. {step['name']}: {' '.join(step['command'])}")
        return
    print(f"OK {label}" if payload["ok"] else f"FAIL {label}")
    if payload.get("selectedIdentity"):
        print(f"selected identity: {payload['selectedIdentity']}")
    for step in payload["steps"]:
        status = "OK" if step["ok"] else "FAIL"
        print(f"{status} {step['name']} ({step['seconds']}s)")
        if not step["ok"]:
            if step.get("stdoutTail"):
                print(step["stdoutTail"])
            if step.get("stderrTail"):
                print(step["stderrTail"])
    if not payload["ok"] and not any(not step["ok"] for step in payload["steps"]):
        if payload.get("failedStep"):
            print(f"failed step: {payload['failedStep']}")
        evidence = payload.get("evidenceManifestResult")
        if isinstance(evidence, dict):
            for issue in evidence.get("issues", []):
                print(f"FAIL {issue}")
    print_artifact_summary(payload)


def print_artifact_summary(payload: Mapping[str, Any]) -> None:
    entries = (
        ("dist", payload.get("outputDir")),
        ("app", payload.get("app")),
        ("dmg", payload.get("dmg")),
        ("checksum", payload.get("checksum")),
        ("evidence", payload.get("evidenceManifest")),
    )
    visible_entries = [(label, str(value)) for label, value in entries if str(value or "").strip()]
    if not visible_entries:
        return
    print("Artifacts:")
    for label, value in visible_entries:
        print(f"  {label}: {value}")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.check_plan:
        payload = plan_payload(
            root=args.root,
            python=args.python,
            npm_action=args.npm,
            clean_first=args.clean_first,
            require_apple_development=args.require_apple_development,
            skip_launch_smoke=args.skip_launch_smoke,
            strict_release_signing=args.strict_release_signing,
            strict_artifacts=args.strict_artifacts,
            output_dir=args.output_dir,
            runtime_profile=args.runtime_profile,
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print_text(payload, plan=True)
        return 0

    payload = run_macos_build(
        root=args.root,
        python=args.python,
        npm_action=args.npm,
        clean_first=args.clean_first,
        require_apple_development=args.require_apple_development,
        skip_launch_smoke=args.skip_launch_smoke,
        strict_release_signing=args.strict_release_signing,
        strict_artifacts=args.strict_artifacts,
        runtime_profile=args.runtime_profile,
        progress=True,
        output_dir=args.output_dir,
    )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_text(payload)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
