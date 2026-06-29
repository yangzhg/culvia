from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
MACOS_RELEASE_DIR = Path("dist") / "macos"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SECRET_PATTERN = "sk-[A-Za-z0-9]{12,}"
SECRET_SCAN_EXCLUDES = (
    "!model_cache/**",
    "!thumbnail_cache/**",
    "!upload_cache/**",
    "!culvia_uploads/**",
    "!__pycache__/**",
)
XCODE_LICENSE_ERROR = "You have not agreed to the Xcode license"
WHITESPACE_EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "analysis_cache",
    "binaries",
    "build",
    "dist",
    "gen",
    "model_cache",
    "node_modules",
    "culvia.egg-info",
    "culvia_uploads",
    "target",
    "thumbnail_cache",
    "upload_cache",
}
WHITESPACE_TEXT_SUFFIXES = {
    ".cfg",
    ".bat",
    ".cmd",
    ".css",
    ".gitignore",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".plist",
    ".py",
    ".ps1",
    ".rs",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
WHITESPACE_TEXT_NAMES = {
    "Dockerfile",
    "LICENSE",
    "Makefile",
    "culvia-dev",
    "culvia-supervisor",
    "culvia-web",
}


@dataclass(frozen=True)
class GateStep:
    name: str
    command: tuple[str, ...]
    ok_returncodes: tuple[int, ...] = (0,)
    env: Mapping[str, str] | None = None


@dataclass(frozen=True)
class GateResult:
    name: str
    command: tuple[str, ...]
    status: str
    returncode: int
    seconds: float
    stdout: str = ""
    stderr: str = ""


def temp_path(name: str) -> Path:
    return Path("/private/tmp" if Path("/private/tmp").exists() else tempfile.gettempdir()) / name


def command_text(command: Sequence[str]) -> str:
    return shlex.join(str(part) for part in command)


def tool_path_prefix() -> str:
    paths = [
        Path("/opt/homebrew/opt/rustup/bin"),
        Path("/usr/local/opt/rustup/bin"),
        Path.home() / ".cargo" / "bin",
    ]
    return os.pathsep.join(str(path) for path in paths if path.exists())


def compact_output(text: str, *, max_chars: int = 1600) -> str:
    stripped = text.strip()
    if len(stripped) <= max_chars:
        return stripped
    return stripped[-max_chars:]


def git_blocked_by_xcode_license(stdout: str, stderr: str) -> bool:
    return XCODE_LICENSE_ERROR in stdout or XCODE_LICENSE_ERROR in stderr


def should_scan_text_file(path: Path, *, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    if any(part in WHITESPACE_EXCLUDED_DIRS for part in relative.parts[:-1]):
        return False
    name = path.name
    if name in WHITESPACE_TEXT_NAMES or name.startswith(".") and name in WHITESPACE_TEXT_SUFFIXES:
        return True
    return path.suffix in WHITESPACE_TEXT_SUFFIXES


def whitespace_fallback_check(*, root: Path = ROOT) -> tuple[int, str]:
    issues: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not should_scan_text_file(path, root=root):
            continue
        data = path.read_bytes()
        if not data:
            continue
        if b"\0" in data[:4096]:
            continue
        relative = path.relative_to(root).as_posix()
        if not data.endswith(b"\n"):
            issues.append(f"{relative}: missing newline at end of file")
        for line_number, raw_line in enumerate(data.splitlines(keepends=True), start=1):
            content = raw_line.rstrip(b"\r\n")
            if content.endswith((b" ", b"\t")):
                issues.append(f"{relative}:{line_number}: trailing whitespace")
    if issues:
        return 1, "\n".join(issues)
    return 0, "git diff --check unavailable because Xcode license is not accepted; Python whitespace fallback passed."


def should_secret_scan_file(path: Path, *, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    excluded_dirs = WHITESPACE_EXCLUDED_DIRS | {
        glob.removeprefix("!").removesuffix("/**") for glob in SECRET_SCAN_EXCLUDES if glob.startswith("!")
    }
    return not any(part in excluded_dirs for part in relative.parts[:-1])


def sensitive_scan_fallback_check(*, root: Path = ROOT, pattern: str = SECRET_PATTERN) -> tuple[int, str]:
    regex = re.compile(pattern)
    matches: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not should_secret_scan_file(path, root=root):
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:4096]:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="ignore")
        for line_number, line in enumerate(text.splitlines(), start=1):
            match = regex.search(line)
            if match:
                matches.append(f"{path.relative_to(root).as_posix()}:{line_number}:{match.group(0)}")
    if matches:
        return 0, "\n".join(matches)
    return 1, "rg unavailable; Python sensitive information fallback found no matches."


def collect_steps(
    *,
    root: Path = ROOT,
    python: Path = Path(sys.executable),
    wheelhouse: Path | None = None,
    install_venv: Path | None = None,
    dist_dir: Path | None = None,
    strict_desktop: bool = False,
    include_release_smoke: bool = True,
    include_sdist_smoke: bool = False,
    sdist_artifact: Path | None = None,
    include_release_preflight: bool = False,
    strict_signing: bool = False,
    include_backend_smoke: bool = False,
    include_backend_workflow_smoke: bool = False,
    backend_binary: Path | None = None,
    include_macos_artifact_preflight: bool = False,
    strict_macos_artifacts: bool = False,
    include_macos_app_launch_smoke: bool = False,
    macos_app: Path | None = None,
    macos_dmg: Path | None = None,
    macos_bundle_dir: Path | None = None,
    windows_zip_artifact: Path | None = None,
    linux_tgz_artifact: Path | None = None,
) -> list[GateStep]:
    compile_env = {"PYTHONPYCACHEPREFIX": str(temp_path("culvia-pycache"))}
    wheelhouse = wheelhouse or temp_path("culvia-wheelhouse")
    install_venv = install_venv or temp_path("culvia-install-check")
    dist_dir = dist_dir or temp_path("culvia-dist")
    steps = [
        GateStep("unit tests", (str(python), "-m", "unittest", "discover", "-s", "tests")),
        GateStep(
            "compileall",
            (
                str(python),
                "-m",
                "compileall",
                "-q",
                "culvia_app.py",
                "culvia",
                "tests",
                "tools",
            ),
            env=compile_env,
        ),
        GateStep("whitespace", ("git", "diff", "--check")),
        GateStep(
            "sensitive information scan",
            (
                "rg",
                "-n",
                SECRET_PATTERN,
                ".",
                *tuple(arg for glob in SECRET_SCAN_EXCLUDES for arg in ("--glob", glob)),
            ),
            ok_returncodes=(1,),
        ),
        GateStep(
            "desktop readiness",
            (
                str(python),
                str(root / "tools" / "check_desktop_readiness.py"),
                "--json",
                *(("--strict-toolchain",) if strict_desktop else ()),
            ),
        ),
        GateStep(
            "desktop release workflow contract",
            (
                str(python),
                str(root / "tools" / "check_desktop_release_workflow.py"),
                "--json",
            ),
        ),
    ]

    if include_release_smoke:
        steps.append(
            GateStep(
                "release smoke",
                (
                    str(python),
                    str(root / "tools" / "release_smoke.py"),
                    "--build",
                    "--wheelhouse",
                    str(wheelhouse),
                    "--install",
                    "--venv",
                    str(install_venv),
                    "--strict",
                ),
            )
        )

    if include_sdist_smoke or sdist_artifact is not None:
        sdist_args = (
            ("--sdist", str(sdist_artifact))
            if sdist_artifact is not None
            else ("--build-sdist", "--dist-dir", str(dist_dir))
        )
        steps.append(
            GateStep(
                "sdist release smoke",
                (
                    str(python),
                    str(root / "tools" / "release_smoke.py"),
                    *sdist_args,
                    "--strict",
                ),
            )
        )

    if strict_desktop:
        preflight_backend_args = ("--backend-binary", str(backend_binary)) if backend_binary else ()
        strict_signing_args = ("--strict-signing",) if strict_signing else ()
        steps.extend(
            [
                GateStep(
                    "desktop release preflight",
                    (
                        str(python),
                        str(root / "tools" / "check_desktop_release_preflight.py"),
                        "--json",
                        *preflight_backend_args,
                        *strict_signing_args,
                    ),
                ),
                GateStep(
                    "backend placeholder",
                    (
                        str(python),
                        "desktop/tauri/scripts/build-backend.py",
                        "--ensure-placeholder",
                        "--json",
                    ),
                ),
                GateStep(
                    "desktop cargo check",
                    ("cargo", "check", "--manifest-path", "desktop/tauri/src-tauri/Cargo.toml"),
                ),
                GateStep(
                    "desktop cargo test",
                    ("cargo", "test", "--manifest-path", "desktop/tauri/src-tauri/Cargo.toml"),
                ),
                GateStep(
                    "desktop shell info",
                    ("npm", "--prefix", "desktop/tauri", "run", "tauri:info"),
                ),
                GateStep(
                    "backend build plan",
                    (
                        str(python),
                        "desktop/tauri/scripts/build-backend.py",
                        "--check-plan",
                        "--json",
                    ),
                ),
            ]
        )

    if include_release_preflight and not strict_desktop:
        preflight_backend_args = ("--backend-binary", str(backend_binary)) if backend_binary else ()
        strict_signing_args = ("--strict-signing",) if strict_signing else ()
        steps.append(
            GateStep(
                "desktop release preflight",
                (
                    str(python),
                    str(root / "tools" / "check_desktop_release_preflight.py"),
                    "--json",
                    *preflight_backend_args,
                    *strict_signing_args,
                ),
            )
        )

    if include_backend_smoke:
        binary_args = ("--binary", str(backend_binary)) if backend_binary else ()
        steps.append(
            GateStep(
                "backend smoke",
                (
                    str(python),
                    str(root / "tools" / "check_backend_smoke.py"),
                    *binary_args,
                    "--timeout",
                    "90",
                    "--json",
                ),
            )
        )

    if include_backend_workflow_smoke:
        binary_args = ("--binary", str(backend_binary)) if backend_binary else ()
        steps.append(
            GateStep(
                "backend workflow smoke",
                (
                    str(python),
                    str(root / "tools" / "check_backend_workflow_smoke.py"),
                    *binary_args,
                    "--timeout",
                    "120",
                    "--json",
                ),
            )
        )

    if include_macos_artifact_preflight:
        app_args = ("--app", str(macos_app)) if macos_app else ()
        dmg_args = ("--dmg", str(macos_dmg)) if macos_dmg else ()
        selected_bundle_dir = macos_bundle_dir or root / MACOS_RELEASE_DIR
        bundle_args = (
            "--bundle-dir",
            str(selected_bundle_dir),
        )
        strict_args = ("--strict",) if strict_macos_artifacts else ()
        steps.append(
            GateStep(
                "macos artifact preflight",
                (
                    str(python),
                    str(root / "tools" / "check_macos_artifact_preflight.py"),
                    "--json",
                    *bundle_args,
                    *app_args,
                    *dmg_args,
                    *strict_args,
                ),
            )
        )

    if include_macos_app_launch_smoke:
        app_args = ("--app", str(macos_app)) if macos_app else ()
        selected_bundle_dir = macos_bundle_dir or root / MACOS_RELEASE_DIR
        bundle_args = (
            "--bundle-dir",
            str(selected_bundle_dir),
        )
        steps.append(
            GateStep(
                "macos app launch smoke",
                (
                    str(python),
                    str(root / "tools" / "check_macos_app_launch_smoke.py"),
                    "--json",
                    *bundle_args,
                    *app_args,
                ),
            )
        )

    if windows_zip_artifact is not None:
        steps.append(
            GateStep(
                "windows portable package preflight",
                (
                    str(python),
                    str(root / "tools" / "check_portable_package_preflight.py"),
                    "--windows-zip",
                    str(windows_zip_artifact),
                    "--json",
                ),
            )
        )

    if linux_tgz_artifact is not None:
        steps.append(
            GateStep(
                "linux portable package preflight",
                (
                    str(python),
                    str(root / "tools" / "check_portable_package_preflight.py"),
                    "--linux-tgz",
                    str(linux_tgz_artifact),
                    "--json",
                ),
            )
        )

    return steps


def run_step(step: GateStep, *, root: Path = ROOT) -> GateResult:
    env = os.environ.copy()
    prefix = tool_path_prefix()
    if prefix:
        env["PATH"] = prefix + os.pathsep + env.get("PATH", "")
    if step.env:
        env.update(step.env)
    started = time.monotonic()
    try:
        result = subprocess.run(
            list(step.command),
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        if step.name == "sensitive information scan" and step.command[:1] == ("rg",):
            returncode, stdout = sensitive_scan_fallback_check(root=root)
            seconds = time.monotonic() - started
            status = "OK" if returncode in step.ok_returncodes else "FAIL"
            return GateResult(
                name=step.name,
                command=step.command,
                status=status,
                returncode=returncode,
                seconds=seconds,
                stdout=compact_output(stdout),
                stderr=compact_output(str(exc)),
            )
        seconds = time.monotonic() - started
        return GateResult(
            name=step.name,
            command=step.command,
            status="FAIL",
            returncode=127,
            seconds=seconds,
            stdout="",
            stderr=compact_output(str(exc)),
        )
    seconds = time.monotonic() - started
    if (
        step.name == "whitespace"
        and result.returncode not in step.ok_returncodes
        and git_blocked_by_xcode_license(result.stdout, result.stderr)
    ):
        fallback_started = time.monotonic()
        returncode, stdout = whitespace_fallback_check(root=root)
        seconds += time.monotonic() - fallback_started
        status = "OK" if returncode in step.ok_returncodes else "FAIL"
        return GateResult(
            name=step.name,
            command=step.command,
            status=status,
            returncode=returncode,
            seconds=seconds,
            stdout=compact_output(stdout),
            stderr=compact_output(result.stderr),
        )
    status = "OK" if result.returncode in step.ok_returncodes else "FAIL"
    return GateResult(
        name=step.name,
        command=step.command,
        status=status,
        returncode=int(result.returncode),
        seconds=seconds,
        stdout=compact_output(result.stdout),
        stderr=compact_output(result.stderr),
    )


def run_steps(steps: Sequence[GateStep], *, root: Path = ROOT, progress: bool = False) -> list[GateResult]:
    results: list[GateResult] = []
    for index, step in enumerate(steps, start=1):
        if progress:
            print(f"[formal-gate] {index}/{len(steps)} {step.name} ...", file=sys.stderr, flush=True)
        result = run_step(step, root=root)
        results.append(result)
        if progress:
            print(
                f"[formal-gate] {index}/{len(steps)} {result.status} {step.name} ({result.seconds:.1f}s)",
                file=sys.stderr,
                flush=True,
            )
    return results


def results_payload(results: Sequence[GateResult]) -> dict:
    failed = [result.name for result in results if result.status != "OK"]
    return {
        "ok": not failed,
        "failed": failed,
        "results": [
            {
                "name": result.name,
                "status": result.status,
                "returncode": result.returncode,
                "seconds": round(result.seconds, 3),
                "command": list(result.command),
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
            for result in results
        ],
    }


def print_text_results(results: Sequence[GateResult]) -> None:
    for result in results:
        print(f"{result.status} {result.name} ({result.seconds:.1f}s): {command_text(result.command)}")
        if result.status != "OK":
            if result.stdout:
                print(result.stdout)
            if result.stderr:
                print(result.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the formal release gate for Culvia.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--wheelhouse", type=Path, default=temp_path("culvia-wheelhouse"))
    parser.add_argument("--venv", type=Path, default=temp_path("culvia-install-check"))
    parser.add_argument("--dist-dir", type=Path, default=temp_path("culvia-dist"))
    parser.add_argument("--skip-release-smoke", action="store_true", help="Skip wheel build/install smoke.")
    sdist_group = parser.add_mutually_exclusive_group()
    sdist_group.add_argument(
        "--build-sdist", action="store_true", help="Build and verify an sdist as a strict release smoke step."
    )
    sdist_group.add_argument(
        "--sdist-artifact",
        type=Path,
        default=None,
        help="Verify an existing culvia-*.tar.gz sdist as a strict release smoke step.",
    )
    parser.add_argument("--strict-desktop", action="store_true", help="Fail when desktop build tooling is missing.")
    parser.add_argument("--release-preflight", action="store_true", help="Run desktop release prerequisite checks.")
    parser.add_argument(
        "--strict-signing",
        action="store_true",
        help="Fail Desktop release preflight when signing/notarization inputs are missing.",
    )
    parser.add_argument("--backend-smoke", action="store_true", help="Run smoke test against a built desktop backend.")
    parser.add_argument(
        "--backend-workflow-smoke",
        action="store_true",
        help="Run fixture curation/export workflow smoke against a built desktop backend.",
    )
    parser.add_argument("--backend-binary", type=Path, default=None, help="Backend binary used by backend smoke gates.")
    parser.add_argument(
        "--macos-artifacts", action="store_true", help="Run checks against built macOS .app/.dmg artifacts."
    )
    parser.add_argument(
        "--strict-macos-artifacts",
        action="store_true",
        help="Fail when macOS artifacts are missing or checks cannot run.",
    )
    parser.add_argument(
        "--macos-app-launch-smoke",
        action="store_true",
        help="Launch a built macOS .app and verify backend, window, and fixture runtime APIs.",
    )
    parser.add_argument("--macos-app", type=Path, default=None, help="Path to a built macOS .app bundle.")
    parser.add_argument("--macos-dmg", type=Path, default=None, help="Path to a built macOS .dmg installer.")
    parser.add_argument(
        "--macos-bundle-dir",
        type=Path,
        default=None,
        help="Desktop bundle output directory used to discover .app/.dmg artifacts.",
    )
    parser.add_argument(
        "--windows-zip-artifact", type=Path, default=None, help="Path to a built Windows portable .zip artifact."
    )
    parser.add_argument("--linux-tgz-artifact", type=Path, default=None, help="Path to a built Linux .tar.gz artifact.")
    parser.add_argument("--list", action="store_true", help="List planned gate steps and exit.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable gate results.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    steps = collect_steps(
        root=args.root,
        python=args.python,
        wheelhouse=args.wheelhouse,
        install_venv=args.venv,
        dist_dir=args.dist_dir,
        strict_desktop=args.strict_desktop,
        include_release_smoke=not args.skip_release_smoke,
        include_sdist_smoke=args.build_sdist,
        sdist_artifact=args.sdist_artifact,
        include_release_preflight=args.release_preflight or args.strict_signing,
        strict_signing=args.strict_signing,
        include_backend_smoke=args.backend_smoke,
        include_backend_workflow_smoke=args.backend_workflow_smoke,
        backend_binary=args.backend_binary,
        include_macos_artifact_preflight=(
            args.macos_artifacts
            or args.strict_macos_artifacts
            or args.macos_app is not None
            or args.macos_dmg is not None
        ),
        strict_macos_artifacts=args.strict_macos_artifacts,
        include_macos_app_launch_smoke=args.macos_app_launch_smoke,
        macos_app=args.macos_app,
        macos_dmg=args.macos_dmg,
        macos_bundle_dir=args.macos_bundle_dir,
        windows_zip_artifact=args.windows_zip_artifact,
        linux_tgz_artifact=args.linux_tgz_artifact,
    )
    if args.list:
        for step in steps:
            print(f"{step.name}: {command_text(step.command)}")
        return 0

    results = run_steps(steps, root=args.root, progress=True)
    payload = results_payload(results)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_text_results(results)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
