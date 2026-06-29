from __future__ import annotations

import argparse
import configparser
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import venv
import zipfile
from pathlib import Path
from email.parser import Parser
from typing import Sequence
from urllib.parse import urlparse

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - project requires Python 3.11+.
    tomllib = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[1]
WEB_DATA_PREFIX = "share/culvia/web"
DEFAULT_PYTHON_DIST_DIR = ROOT / "dist" / "python"
STATIC_REFERENCE_RE = re.compile(r'(?:href|src)="([^"]+)"')
MODULE_IMPORT_RE = re.compile(r"""^\s*import\s+(?:[^"']*?\bfrom\s+)?["'](\.{1,2}/[^"']+)["']""", re.MULTILINE)
REQUIRED_PACKAGE_SUFFIXES = (
    "culvia/__init__.py",
    "culvia/settings.py",
    "culvia/server.py",
    "culvia/supervisor.py",
    "culvia/scoring.py",
    "culvia_app.py",
)
INSTALLED_WEB_REQUIRED_FILES = (
    "index.html",
    "i18n_messages.js",
    "locales/zh-CN.js",
    "locales/en.js",
    "i18n.js",
    "styles.css",
    "styles/00-foundation.css",
    "styles/90-responsive.css",
    "llm_config_view.js",
    "export_result_data.js",
    "distribution_view.js",
    "viewer_inspector.js",
    "app_config.js",
    "icons.js",
    "ui_helpers.js",
    "gallery_view.js",
    "app.js",
)
REQUIRED_PROJECT_URLS = ("Homepage", "Documentation", "Issues", "Source")
REQUIRED_CLASSIFIERS = (
    "License :: OSI Approved :: MIT License",
    "Operating System :: MacOS",
    "Operating System :: Microsoft :: Windows",
    "Operating System :: POSIX :: Linux",
)
REQUIRED_RELEASE_EXTRA_DEPENDENCIES = ("build>=1.2", "twine>=5", "wheel>=0.43")
RUNTIME_DIRECTORY_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".codex",
    ".agents",
    "model_cache",
    "analysis_cache",
    "thumbnail_cache",
    "upload_cache",
    "culvia_uploads",
}
RUNTIME_FILE_SUFFIXES = (
    ".sqlite",
    ".sqlite3",
    ".db",
    ".csv",
    ".pyc",
    ".pyo",
    ".tmp",
    ".part",
)
RUNTIME_FILE_MARKERS = (
    ".sqlite-",
    ".sqlite3-",
    ".db-",
)


def load_pyproject(root: Path = ROOT) -> dict:
    if tomllib is None:
        raise RuntimeError("Python 3.11+ is required because tomllib is unavailable.")
    return tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))


def dependency_name(requirement: str) -> str:
    return re.split(r"[<>=!~;\[\]\s]", requirement.strip().lower(), maxsplit=1)[0].replace("_", "-")


def static_references_from_html(html: str) -> set[str]:
    references: set[str] = set()
    for reference in STATIC_REFERENCE_RE.findall(html):
        parsed = urlparse(reference)
        if parsed.scheme or parsed.netloc:
            continue
        if parsed.path.startswith("/static/"):
            references.add(parsed.path.removeprefix("/static/"))
    return references


def module_graph_files(web_dir: Path, entry_relative: str) -> set[str]:
    """Relative paths of a JS module and everything it transitively imports."""
    resolved: set[str] = set()
    queue = [entry_relative]
    while queue:
        relative = queue.pop()
        normalized = os.path.normpath(relative).replace(os.sep, "/")
        if normalized in resolved or normalized.startswith(".."):
            continue
        resolved.add(normalized)
        path = web_dir / normalized
        if path.suffix != ".js" or not path.exists():
            continue
        parent = os.path.dirname(normalized)
        for spec in MODULE_IMPORT_RE.findall(path.read_text(encoding="utf-8")):
            queue.append(os.path.join(parent, spec))
    return resolved


def web_static_files(root: Path = ROOT) -> set[str]:
    web_dir = root / "web"
    html = (web_dir / "index.html").read_text(encoding="utf-8")
    files: set[str] = set()
    for relative in static_references_from_html(html):
        files.update(module_graph_files(web_dir, relative))
    return files


def expected_web_data_files(root: Path = ROOT) -> set[str]:
    expected = {f"{WEB_DATA_PREFIX}/index.html"}
    expected.update(f"{WEB_DATA_PREFIX}/{relative}" for relative in INSTALLED_WEB_REQUIRED_FILES)
    expected.update(f"{WEB_DATA_PREFIX}/{relative}" for relative in web_static_files(root))
    return expected


def expected_web_source_files(root: Path = ROOT) -> set[str]:
    expected = {"web/index.html"}
    expected.update(f"web/{relative}" for relative in INSTALLED_WEB_REQUIRED_FILES)
    expected.update(f"web/{relative}" for relative in web_static_files(root))
    return expected


def expected_console_scripts(root: Path = ROOT) -> dict[str, str]:
    data = load_pyproject(root)
    return dict(data["project"]["scripts"])


def check_project_metadata(root: Path = ROOT) -> list[str]:
    issues: list[str] = []
    data = load_pyproject(root)
    project = data.get("project", {})
    runtime_dependency_names = {dependency_name(item) for item in project.get("dependencies", [])}
    optional_dependencies = project.get("optional-dependencies", {})
    release_dependencies = optional_dependencies.get("release", []) if isinstance(optional_dependencies, dict) else []
    release_dependency_names = {dependency_name(item) for item in release_dependencies}
    license_path = root / "LICENSE"
    if not license_path.is_file():
        issues.append("missing open-source license file: LICENSE")
    else:
        license_text = license_path.read_text(encoding="utf-8")
        if "MIT License" not in license_text or "Permission is hereby granted" not in license_text:
            issues.append("LICENSE must contain the MIT license text")

    license_spec = project.get("license", {})
    if not isinstance(license_spec, dict) or license_spec.get("file") != "LICENSE":
        issues.append("pyproject project.license must point to LICENSE")
    if project.get("readme") != "README.md":
        issues.append("pyproject project.readme must be README.md")
    if not project.get("authors"):
        issues.append("pyproject project.authors must not be empty")
    if len(project.get("keywords", [])) < 5:
        issues.append("pyproject project.keywords should describe the photography/culling package")

    classifiers = set(project.get("classifiers", []))
    for classifier in REQUIRED_CLASSIFIERS:
        if classifier not in classifiers:
            issues.append(f"missing pyproject classifier: {classifier}")

    urls = project.get("urls", {})
    for name in REQUIRED_PROJECT_URLS:
        value = urls.get(name) if isinstance(urls, dict) else None
        if not isinstance(value, str) or not value.startswith("https://"):
            issues.append(f"pyproject project.urls.{name} must be an https URL")
    for dependency in REQUIRED_RELEASE_EXTRA_DEPENDENCIES:
        name = dependency_name(dependency)
        if name not in release_dependency_names:
            issues.append(f"pyproject optional-dependencies.release must include {dependency}")
        if name in runtime_dependency_names:
            issues.append(f"release tool must stay out of runtime dependencies: {name}")
    return issues


def source_distribution_suffixes(root: Path = ROOT) -> set[str]:
    return {
        "LICENSE",
        "README.md",
        "pyproject.toml",
        *REQUIRED_PACKAGE_SUFFIXES,
        *expected_web_source_files(root),
    }


def missing_suffixes(names: Sequence[str], expected_suffixes: set[str] | Sequence[str]) -> list[str]:
    archive_names = tuple(names)
    return sorted(suffix for suffix in expected_suffixes if not any(name.endswith(suffix) for name in archive_names))


def find_runtime_artifacts(names: Sequence[str]) -> list[str]:
    artifacts: list[str] = []
    for name in names:
        normalized = name.replace("\\", "/")
        lowered = normalized.lower()
        parts = [part for part in lowered.split("/") if part]
        basename = parts[-1] if parts else lowered
        if any(part in RUNTIME_DIRECTORY_NAMES for part in parts):
            artifacts.append(name)
            continue
        if basename.endswith(RUNTIME_FILE_SUFFIXES) or any(marker in basename for marker in RUNTIME_FILE_MARKERS):
            artifacts.append(name)
    return sorted(artifacts)


def read_console_scripts_from_wheel(wheel_path: Path) -> dict[str, str]:
    with zipfile.ZipFile(wheel_path) as archive:
        candidates = sorted(name for name in archive.namelist() if name.endswith(".dist-info/entry_points.txt"))
        if not candidates:
            return {}
        parser = configparser.ConfigParser()
        parser.optionxform = str
        parser.read_string(archive.read(candidates[0]).decode("utf-8"))
    if not parser.has_section("console_scripts"):
        return {}
    return dict(parser.items("console_scripts"))


def wheel_metadata(wheel_path: Path) -> dict[str, list[str] | str]:
    with zipfile.ZipFile(wheel_path) as archive:
        candidates = sorted(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        if not candidates:
            return {}
        message = Parser().parsestr(archive.read(candidates[0]).decode("utf-8"))
    metadata: dict[str, list[str] | str] = {}
    for key in ("Name", "Version", "License-File", "Project-URL", "Classifier"):
        values = message.get_all(key, [])
        metadata[key] = values if len(values) != 1 else values[0]
    return metadata


def metadata_values(value: list[str] | str | None) -> list[str]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def entry_point_issues(found: dict[str, str], expected: dict[str, str]) -> list[str]:
    issues: list[str] = []
    for name, target in sorted(expected.items()):
        if name not in found:
            issues.append(f"missing console script: {name}")
        elif found[name] != target:
            issues.append(f"console script {name} points to {found[name]!r}, expected {target!r}")
    return issues


def check_wheel_archive(wheel_path: Path, root: Path = ROOT) -> list[str]:
    issues: list[str] = []
    if not wheel_path.exists():
        return [f"wheel does not exist: {wheel_path}"]

    with zipfile.ZipFile(wheel_path) as archive:
        names = archive.namelist()

    missing_web = missing_suffixes(names, expected_web_data_files(root))
    if missing_web:
        issues.append("missing web data files: " + ", ".join(missing_web))

    missing_packages = missing_suffixes(names, REQUIRED_PACKAGE_SUFFIXES)
    if missing_packages:
        issues.append("missing package files: " + ", ".join(missing_packages))

    runtime_artifacts = find_runtime_artifacts(names)
    if runtime_artifacts:
        issues.append("wheel contains runtime artifacts: " + ", ".join(runtime_artifacts[:12]))

    if not any(name.endswith(".dist-info/licenses/LICENSE") or name.endswith(".dist-info/LICENSE") for name in names):
        issues.append("wheel is missing bundled LICENSE file")

    metadata = wheel_metadata(wheel_path)
    if metadata:
        if metadata.get("Name") != "culvia":
            issues.append(f"wheel METADATA Name is {metadata.get('Name')!r}, expected 'culvia'")
        license_files = metadata_values(metadata.get("License-File"))
        if "LICENSE" not in license_files:
            issues.append("wheel METADATA is missing License-File: LICENSE")
        project_urls = metadata_values(metadata.get("Project-URL"))
        for name in REQUIRED_PROJECT_URLS:
            if not any(str(item).startswith(f"{name}, https://") for item in project_urls):
                issues.append(f"wheel METADATA is missing Project-URL: {name}")
        classifiers = set(metadata_values(metadata.get("Classifier")))
        for classifier in REQUIRED_CLASSIFIERS:
            if classifier not in classifiers:
                issues.append(f"wheel METADATA is missing classifier: {classifier}")
    else:
        issues.append("wheel is missing dist-info/METADATA")

    issues.extend(entry_point_issues(read_console_scripts_from_wheel(wheel_path), expected_console_scripts(root)))
    return issues


def check_sdist_archive(sdist_path: Path, root: Path = ROOT) -> list[str]:
    issues: list[str] = []
    if not sdist_path.exists():
        return [f"sdist does not exist: {sdist_path}"]
    try:
        with tarfile.open(sdist_path, "r:gz") as archive:
            names = archive.getnames()
    except (tarfile.TarError, OSError) as exc:
        return [f"sdist cannot be read as tar.gz: {exc}"]

    missing = missing_suffixes(names, source_distribution_suffixes(root))
    if missing:
        issues.append("sdist is missing source files: " + ", ".join(missing))

    runtime_artifacts = find_runtime_artifacts(names)
    if runtime_artifacts:
        issues.append("sdist contains runtime artifacts: " + ", ".join(runtime_artifacts[:12]))

    unsafe = sorted(name for name in names if name.startswith("/") or ".." in Path(name).parts)
    if unsafe:
        issues.append("sdist contains unsafe member paths: " + ", ".join(unsafe[:12]))
    return issues


def check_installed_web_dir(web_dir: Path, *, source_root: Path = ROOT) -> list[str]:
    issues: list[str] = []
    resolved = web_dir.resolve()
    source_web = (source_root / "web").resolve()
    if resolved == source_web:
        issues.append(f"resolve_web_dir returned the source tree, not installed data-files: {resolved}")

    normalized = str(resolved).replace("\\", "/")
    if WEB_DATA_PREFIX not in normalized:
        issues.append(f"installed web dir does not include {WEB_DATA_PREFIX}: {resolved}")

    for name in INSTALLED_WEB_REQUIRED_FILES:
        if not (resolved / name).exists():
            issues.append(f"installed web dir is missing {name}: {resolved}")
    index_path = resolved / "index.html"
    if index_path.exists():
        html = index_path.read_text(encoding="utf-8")
        for relative in sorted(static_references_from_html(html)):
            if not (resolved / relative).exists():
                issues.append(f"installed web dir is missing HTML static reference {relative}: {resolved}")
    return issues


def outside_source_tree_cwd(root: Path = ROOT) -> Path:
    root = root.resolve()
    for candidate in (Path("/private/tmp"), Path(tempfile.gettempdir())):
        if not candidate.is_dir():
            continue
        resolved = candidate.resolve()
        if resolved != root and root not in resolved.parents:
            return resolved
    return root.parent


def module_available(python: Path, module: str, probe_args: Sequence[str]) -> bool:
    result = subprocess.run(
        [str(python), "-m", module, *probe_args],
        cwd=outside_source_tree_cwd(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def build_wheel(
    root: Path, wheelhouse: Path, python: Path, *, strict: bool = False
) -> tuple[Path | None, list[str], list[str]]:
    issues: list[str] = []
    skips: list[str] = []
    if not module_available(python, "pip", ("--version",)):
        message = f"{python} cannot run pip; install pip before release smoke"
        (issues if strict else skips).append(message)
        return None, issues, skips
    if not module_available(python, "wheel", ("version",)):
        message = f"{python} cannot run wheel; install wheel before building with --no-build-isolation"
        (issues if strict else skips).append(message)
        return None, issues, skips

    wheelhouse.mkdir(parents=True, exist_ok=True)
    before = {path.resolve() for path in wheelhouse.glob("culvia-*.whl")}
    command = [
        str(python),
        "-m",
        "pip",
        "wheel",
        str(root),
        "--no-deps",
        "--no-build-isolation",
        "-w",
        str(wheelhouse),
    ]
    result = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        issues.append("wheel build failed:\n" + result.stdout + result.stderr)
        return None, issues, skips

    candidates = sorted(wheelhouse.glob("culvia-*.whl"), key=lambda path: path.stat().st_mtime, reverse=True)
    new_candidates = [path for path in candidates if path.resolve() not in before]
    wheel_path = (new_candidates or candidates)[0] if candidates else None
    if wheel_path is None:
        issues.append(f"wheel build produced no culvia-*.whl in {wheelhouse}")
    return wheel_path, issues, skips


def build_sdist(
    root: Path, dist_dir: Path, python: Path, *, strict: bool = False
) -> tuple[Path | None, list[str], list[str]]:
    issues: list[str] = []
    skips: list[str] = []
    if not module_available(python, "build", ("--version",)):
        message = f"{python} cannot run build; install build before creating an sdist"
        (issues if strict else skips).append(message)
        return None, issues, skips

    dist_dir.mkdir(parents=True, exist_ok=True)
    before = {path.resolve() for path in dist_dir.glob("culvia-*.tar.gz")}
    command = [
        str(python),
        "-m",
        "build",
        str(root),
        "--sdist",
        "--no-isolation",
        "--outdir",
        str(dist_dir),
    ]
    result = subprocess.run(
        command,
        cwd=outside_source_tree_cwd(root),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        issues.append("sdist build failed:\n" + result.stdout + result.stderr)
        return None, issues, skips

    candidates = sorted(dist_dir.glob("culvia-*.tar.gz"), key=lambda path: path.stat().st_mtime, reverse=True)
    new_candidates = [path for path in candidates if path.resolve() not in before]
    sdist_path = (new_candidates or candidates)[0] if candidates else None
    if sdist_path is None:
        issues.append(f"sdist build produced no culvia-*.tar.gz in {dist_dir}")
    return sdist_path, issues, skips


def script_dir_for_venv(venv_dir: Path) -> Path:
    return venv_dir / ("Scripts" if os.name == "nt" else "bin")


def python_for_venv(venv_dir: Path) -> Path:
    return script_dir_for_venv(venv_dir) / ("python.exe" if os.name == "nt" else "python")


def console_script_for_venv(venv_dir: Path, name: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return script_dir_for_venv(venv_dir) / f"{name}{suffix}"


def install_and_check_wheel(wheel_path: Path, venv_dir: Path, root: Path = ROOT) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    skips: list[str] = []
    try:
        venv.EnvBuilder(with_pip=True, clear=True).create(venv_dir)
    except Exception as exc:  # pragma: no cover - platform specific.
        return [f"could not create venv at {venv_dir}: {exc}"], skips

    python = python_for_venv(venv_dir)
    install = subprocess.run(
        [str(python), "-m", "pip", "install", "--no-deps", "--force-reinstall", str(wheel_path)],
        text=True,
        capture_output=True,
        check=False,
    )
    if install.returncode != 0:
        issues.append("wheel install failed:\n" + install.stdout + install.stderr)
        return issues, skips

    for script in expected_console_scripts(root):
        path = console_script_for_venv(venv_dir, script)
        help_result = subprocess.run([str(path), "--help"], text=True, capture_output=True, check=False)
        if help_result.returncode != 0:
            issues.append(f"{script} --help failed:\n{help_result.stdout}{help_result.stderr}")

    required = repr(tuple(INSTALLED_WEB_REQUIRED_FILES))
    prefix = repr(WEB_DATA_PREFIX)
    source_web = repr(str((root / "web").resolve()))
    check_code = (
        "from pathlib import Path\n"
        "from culvia.settings import resolve_web_dir\n"
        f"required = {required}\n"
        f"prefix = {prefix}\n"
        f"source_web = Path({source_web})\n"
        "web_dir = resolve_web_dir().resolve()\n"
        "issues = []\n"
        "if web_dir == source_web:\n"
        "    issues.append(f'resolve_web_dir returned the source tree, not installed data-files: {web_dir}')\n"
        "if prefix not in str(web_dir).replace('\\\\', '/'):\n"
        "    issues.append(f'installed web dir does not include {prefix}: {web_dir}')\n"
        "for name in required:\n"
        "    if not (web_dir / name).exists():\n"
        "        issues.append(f'installed web dir is missing {name}: {web_dir}')\n"
        "raise SystemExit('\\n'.join(issues) if issues else 0)\n"
    )
    web_check = subprocess.run(
        [str(python), "-c", check_code],
        cwd=outside_source_tree_cwd(root),
        text=True,
        capture_output=True,
        check=False,
    )
    if web_check.returncode != 0:
        issues.append("installed resolve_web_dir check failed:\n" + web_check.stdout + web_check.stderr)
    return issues, skips


def run_twine_check(artifacts: Sequence[Path], python: Path, *, strict: bool = False) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    skips: list[str] = []
    artifacts = [path for path in artifacts if path is not None]
    if not artifacts:
        message = "no distribution artifacts available for twine check"
        (issues if strict else skips).append(message)
        return issues, skips
    if not module_available(python, "twine", ("--version",)):
        message = f"{python} cannot run twine; skipping twine check"
        (issues if strict else skips).append(message)
        return issues, skips
    result = subprocess.run(
        [str(python), "-m", "twine", "check", *[str(path) for path in artifacts]],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        issues.append("twine check failed:\n" + result.stdout + result.stderr)
    return issues, skips


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify release wheel contents and installed entrypoints.")
    parser.add_argument("--root", type=Path, default=ROOT, help="Project root. Defaults to the repository root.")
    parser.add_argument(
        "--python", type=Path, default=Path(sys.executable), help="Python executable used for build/install probes."
    )
    parser.add_argument("--wheel", type=Path, default=None, help="Existing wheel to verify.")
    parser.add_argument("--sdist", type=Path, default=None, help="Existing source distribution tar.gz to verify.")
    parser.add_argument("--build", action="store_true", help="Build a no-deps wheel before checking it.")
    parser.add_argument("--build-sdist", action="store_true", help="Build a source distribution before checking it.")
    parser.add_argument(
        "--wheelhouse",
        type=Path,
        default=Path(os.environ.get("CULVIA_WHEELHOUSE", str(DEFAULT_PYTHON_DIST_DIR))),
        help="Directory for --build output.",
    )
    parser.add_argument(
        "--dist-dir",
        type=Path,
        default=Path(os.environ.get("CULVIA_DIST_DIR", str(DEFAULT_PYTHON_DIST_DIR))),
        help="Directory for --build-sdist output.",
    )
    parser.add_argument(
        "--install", action="store_true", help="Install the wheel into a clean venv and run entrypoint checks."
    )
    parser.add_argument(
        "--venv", type=Path, default=None, help="Venv path for --install. Defaults to a temporary directory."
    )
    parser.add_argument("--twine-check", action="store_true", help="Run twine check when twine is installed.")
    parser.add_argument(
        "--strict", action="store_true", help="Treat missing release tools as failures instead of SKIP."
    )
    return parser


def distribution_artifact_lines(
    *,
    wheel_path: Path | None,
    sdist_path: Path | None,
    wheelhouse: Path,
    dist_dir: Path,
    include_wheel_dir: bool = False,
    include_sdist_dir: bool = False,
) -> list[str]:
    lines: list[str] = []
    if include_wheel_dir or include_sdist_dir or wheel_path is not None or sdist_path is not None:
        if wheelhouse.resolve() == dist_dir.resolve():
            lines.append(f"  dist: {wheelhouse}")
        else:
            if include_wheel_dir or wheel_path is not None:
                lines.append(f"  wheelhouse: {wheelhouse}")
            if include_sdist_dir or sdist_path is not None:
                lines.append(f"  sdist dir: {dist_dir}")
    if wheel_path is not None:
        lines.append(f"  wheel: {wheel_path}")
    if sdist_path is not None:
        lines.append(f"  sdist: {sdist_path}")
    return lines


def print_distribution_artifacts(
    *,
    wheel_path: Path | None,
    sdist_path: Path | None,
    wheelhouse: Path,
    dist_dir: Path,
    include_wheel_dir: bool = False,
    include_sdist_dir: bool = False,
) -> None:
    lines = distribution_artifact_lines(
        wheel_path=wheel_path,
        sdist_path=sdist_path,
        wheelhouse=wheelhouse,
        dist_dir=dist_dir,
        include_wheel_dir=include_wheel_dir,
        include_sdist_dir=include_sdist_dir,
    )
    if not lines:
        return
    print("Artifacts:")
    for line in lines:
        print(line)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if os.environ.get("CULVIA_RELEASE_SMOKE") and not args.wheel and not args.build:
        args.build = True
        args.install = True

    issues: list[str] = []
    skips: list[str] = []
    wheel_path = args.wheel
    sdist_path = args.sdist
    if sys.version_info < (3, 11):
        issues.append(f"Python 3.11+ is required, got {sys.version.split()[0]}")
    issues.extend(check_project_metadata(args.root))

    if args.build:
        wheel_path, build_issues, build_skips = build_wheel(args.root, args.wheelhouse, args.python, strict=args.strict)
        issues.extend(build_issues)
        skips.extend(build_skips)

    if args.build_sdist:
        sdist_path, sdist_issues, sdist_skips = build_sdist(args.root, args.dist_dir, args.python, strict=args.strict)
        issues.extend(sdist_issues)
        skips.extend(sdist_skips)

    wants_wheel = bool(args.wheel or args.build or args.install)
    wants_sdist = bool(args.sdist or args.build_sdist)

    if wheel_path is None:
        message = "no wheel provided; pass --wheel or --build to run archive checks"
        ((issues if args.strict else skips) if wants_wheel else skips).append(message)
    else:
        issues.extend(check_wheel_archive(wheel_path, args.root))
        if args.install:
            if args.venv is None:
                with tempfile.TemporaryDirectory(prefix="culvia-install-check-") as temp_dir:
                    install_issues, install_skips = install_and_check_wheel(wheel_path, Path(temp_dir), args.root)
            else:
                install_issues, install_skips = install_and_check_wheel(wheel_path, args.venv, args.root)
            issues.extend(install_issues)
            skips.extend(install_skips)

    if sdist_path is None:
        message = "no sdist provided; pass --sdist or --build-sdist to run source archive checks"
        (issues if args.strict and wants_sdist else skips).append(message)
    else:
        issues.extend(check_sdist_archive(sdist_path, args.root))

    if args.twine_check:
        twine_artifacts = [path for path in (wheel_path, sdist_path) if path is not None]
        twine_issues, twine_skips = run_twine_check(twine_artifacts, args.python, strict=args.strict)
        issues.extend(twine_issues)
        skips.extend(twine_skips)

    if wheel_path is not None and not issues:
        print(f"OK release smoke: {wheel_path}")
    if sdist_path is not None and not issues:
        print(f"OK sdist smoke: {sdist_path}")
    for skip in skips:
        print(f"SKIP {skip}")
    for issue in issues:
        print(f"FAIL {issue}")
    print_distribution_artifacts(
        wheel_path=wheel_path,
        sdist_path=sdist_path,
        wheelhouse=args.wheelhouse,
        dist_dir=args.dist_dir,
        include_wheel_dir=bool(args.build),
        include_sdist_dir=bool(args.build_sdist),
    )
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
