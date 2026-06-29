from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence

from culvia import __version__
from culvia.runtime_dependencies import REQUIRED_RUNTIME_MODULES
from culvia.settings import PROJECT_ROOT, user_data_dir


MIN_PYTHON = (3, 11)
RUNTIME_HOME_ENV = "CULVIA_RUNTIME_HOME"
RUNTIME_CONFIG_ENV = "CULVIA_RUNTIME_CONFIG"
RUNTIME_VENV_ENV = "CULVIA_RUNTIME_VENV"
RUNTIME_PYTHON_ENV = "CULVIA_RUNTIME_PYTHON"
RUNTIME_PACKAGE_ENV = "CULVIA_RUNTIME_PACKAGE"
RUNTIME_PROFILE_ENV = "CULVIA_RUNTIME_PROFILE"
RUNTIME_SKIP_INSTALL_ENV = "CULVIA_RUNTIME_SKIP_INSTALL"
DEFAULT_PROFILE = "desktop-lite"


@dataclass(frozen=True)
class RuntimeProfile:
    name: str
    extra: str | None
    required_modules: tuple[str, ...]
    description: str


RUNTIME_PROFILES: dict[str, RuntimeProfile] = {
    "desktop-lite": RuntimeProfile(
        name="desktop-lite",
        extra="desktop-runtime",
        required_modules=REQUIRED_RUNTIME_MODULES,
        description="Desktop shell with an app-managed Python virtualenv.",
    ),
    "web": RuntimeProfile(
        name="web",
        extra=None,
        required_modules=REQUIRED_RUNTIME_MODULES,
        description="Local Web runtime installed into a chosen Python environment.",
    ),
}


@dataclass(frozen=True)
class PythonInfo:
    command: tuple[str, ...]
    executable: str | None
    version: str | None
    ok: bool
    error: str | None = None


@dataclass(frozen=True)
class RuntimeConfig:
    schema_version: int = 1
    mode: str | None = None
    python: str | None = None
    venv: str | None = None
    package: str | None = None
    auto_install: bool = True


def profile_by_name(name: str | None = None) -> RuntimeProfile:
    selected = (name or os.environ.get(RUNTIME_PROFILE_ENV) or DEFAULT_PROFILE).strip()
    try:
        return RUNTIME_PROFILES[selected]
    except KeyError as exc:
        supported = ", ".join(sorted(RUNTIME_PROFILES))
        raise ValueError(f"Unsupported runtime profile {selected!r}. Supported profiles: {supported}.") from exc


def runtime_home(env: Mapping[str, str] | None = None) -> Path:
    env = env or os.environ
    override = env.get(RUNTIME_HOME_ENV)
    if override:
        return Path(override).expanduser()
    return user_data_dir() / "runtime"


def runtime_config_path(env: Mapping[str, str] | None = None) -> Path:
    env = env or os.environ
    override = env.get(RUNTIME_CONFIG_ENV)
    if override:
        return Path(override).expanduser()
    return runtime_home(env) / "runtime.json"


def load_runtime_config(path: Path | None = None, env: Mapping[str, str] | None = None) -> RuntimeConfig:
    config_path = path or runtime_config_path(env)
    if not config_path.exists():
        return RuntimeConfig()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Runtime config must be a JSON object: {config_path}")
    return RuntimeConfig(
        schema_version=int(payload.get("schemaVersion") or payload.get("schema_version") or 1),
        mode=str(payload["mode"]).strip() if payload.get("mode") else None,
        python=str(payload["python"]).strip() if payload.get("python") else None,
        venv=str(payload["venv"]).strip() if payload.get("venv") else None,
        package=str(payload["package"]).strip() if payload.get("package") else None,
        auto_install=bool(payload.get("autoInstall", payload.get("auto_install", True))),
    )


def runtime_config_payload(config: RuntimeConfig) -> dict[str, object]:
    payload: dict[str, object] = {
        "schemaVersion": config.schema_version,
        "autoInstall": config.auto_install,
    }
    if config.mode:
        payload["mode"] = config.mode
    if config.python:
        payload["python"] = config.python
    if config.venv:
        payload["venv"] = config.venv
    if config.package:
        payload["package"] = config.package
    return payload


def save_runtime_config(config: RuntimeConfig, path: Path | None = None, env: Mapping[str, str] | None = None) -> Path:
    config_path = path or runtime_config_path(env)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(runtime_config_payload(config), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return config_path


def default_venv_path(env: Mapping[str, str] | None = None, config: RuntimeConfig | None = None) -> Path:
    env = env or os.environ
    override = env.get(RUNTIME_VENV_ENV)
    if override:
        return Path(override).expanduser()
    config = config or load_runtime_config(env=env)
    if config.venv:
        return Path(config.venv).expanduser()
    return runtime_home(env) / "venv"


def venv_python_path(venv_path: Path) -> Path:
    if sys.platform.startswith("win"):
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


def _dedupe_commands(commands: list[tuple[str, ...]]) -> list[tuple[str, ...]]:
    seen: set[tuple[str, ...]] = set()
    result: list[tuple[str, ...]] = []
    for command in commands:
        if command and command not in seen:
            seen.add(command)
            result.append(command)
    return result


def python_candidate_commands(
    env: Mapping[str, str] | None = None, config: RuntimeConfig | None = None
) -> list[tuple[str, ...]]:
    env = env or os.environ
    commands: list[tuple[str, ...]] = []
    configured = env.get(RUNTIME_PYTHON_ENV)
    if configured:
        commands.append(tuple(shlex.split(configured)))
    config = config or load_runtime_config(env=env)
    if config.python:
        commands.append(tuple(shlex.split(config.python)))
    if sys.platform.startswith("win"):
        commands.extend((("py", "-3.12"), ("py", "-3.11"), ("python",)))
    else:
        commands.extend((("python3.12",), ("python3.11",), ("python3",), ("python",)))
    return _dedupe_commands(commands)


def inspect_python(command: Sequence[str], *, timeout: float = 8.0) -> PythonInfo:
    probe = (
        "import json, sys; "
        "print(json.dumps({'executable': sys.executable, "
        "'version': '.'.join(map(str, sys.version_info[:3])), "
        "'ok': sys.version_info >= (3, 11)}))"
    )
    try:
        result = subprocess.run(
            [*command, "-c", probe],
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return PythonInfo(tuple(command), None, None, False, str(exc))
    if result.returncode != 0:
        return PythonInfo(tuple(command), None, None, False, (result.stderr or result.stdout).strip() or None)
    try:
        payload = json.loads(result.stdout.strip())
    except json.JSONDecodeError as exc:
        return PythonInfo(tuple(command), None, None, False, f"invalid python probe output: {exc}")
    return PythonInfo(
        command=tuple(command),
        executable=str(payload.get("executable") or ""),
        version=str(payload.get("version") or ""),
        ok=bool(payload.get("ok")),
        error=None if payload.get("ok") else f"Python {payload.get('version')} is older than 3.11",
    )


def find_base_python(commands: Sequence[Sequence[str]] | None = None) -> PythonInfo:
    for command in commands or python_candidate_commands():
        info = inspect_python(command)
        if info.ok:
            return info
    return PythonInfo(tuple(), None, None, False, "No Python 3.11+ executable found.")


def module_status(python: Path, modules: Sequence[str]) -> dict[str, object]:
    if not python.exists():
        return {
            "ok": False,
            "python": str(python),
            "missing": list(modules),
            "error": "virtualenv python is missing",
        }
    probe = (
        "import importlib.util, json, sys; "
        "modules = sys.argv[1:]; "
        "missing = [item for item in modules if importlib.util.find_spec(item) is None]; "
        "print(json.dumps({'missing': missing, 'ok': not missing}))"
    )
    result = subprocess.run(
        [str(python), "-c", probe, *modules],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return {
            "ok": False,
            "python": str(python),
            "missing": list(modules),
            "error": (result.stderr or result.stdout).strip(),
        }
    payload = json.loads(result.stdout.strip())
    payload["python"] = str(python)
    return payload


def package_install_args(
    profile: RuntimeProfile,
    *,
    package: str | None = None,
    editable_source: Path | None = None,
    env: Mapping[str, str] | None = None,
    config: RuntimeConfig | None = None,
) -> list[str]:
    env = env or os.environ
    extra = f"[{profile.extra}]" if profile.extra else ""
    if editable_source is not None:
        return ["-e", f"{editable_source.expanduser()}{extra}"]
    config = config or load_runtime_config(env=env)
    configured = package or env.get(RUNTIME_PACKAGE_ENV) or config.package
    if configured:
        return shlex.split(configured)
    if (PROJECT_ROOT / "pyproject.toml").exists():
        return ["-e", f"{PROJECT_ROOT}{extra}"]
    return [f"culvia{extra}=={__version__}"]


def doctor_payload(
    *,
    profile: RuntimeProfile,
    venv_path: Path,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    env = env or os.environ
    config = load_runtime_config(env=env)
    venv_python = venv_python_path(venv_path)
    base_python = find_base_python(python_candidate_commands(env, config))
    venv_info = inspect_python((str(venv_python),)) if venv_python.exists() else None
    modules = module_status(venv_python, profile.required_modules)
    missing = list(modules.get("missing") or [])
    return {
        "ok": bool(venv_python.exists() and not missing),
        "profile": asdict(profile),
        "runtimeHome": str(runtime_home(env)),
        "runtimeConfigPath": str(runtime_config_path(env)),
        "runtimeConfig": runtime_config_payload(config),
        "venv": str(venv_path),
        "venvPython": str(venv_python),
        "venvExists": venv_python.exists(),
        "basePython": asdict(base_python),
        "venvInfo": asdict(venv_info) if venv_info else None,
        "modules": modules,
        "missingModules": missing,
        "installArgs": package_install_args(profile, env=env, config=config),
        "skipInstall": env.get(RUNTIME_SKIP_INSTALL_ENV) == "1" or not config.auto_install,
    }


def run_checked(command: Sequence[str], *, cwd: Path | None = None) -> None:
    result = subprocess.run(list(command), cwd=cwd, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {result.returncode}: {' '.join(command)}")


def create_runtime(*, venv_path: Path, base_python: PythonInfo | None = None) -> dict[str, object]:
    base_python = base_python or find_base_python()
    if not base_python.ok or not base_python.command:
        raise RuntimeError(base_python.error or "Python 3.11+ is required.")
    venv_path.parent.mkdir(parents=True, exist_ok=True)
    run_checked([*base_python.command, "-m", "venv", str(venv_path)])
    return {
        "action": "create",
        "venv": str(venv_path),
        "python": str(venv_python_path(venv_path)),
        "basePython": asdict(base_python),
    }


def install_runtime(
    *,
    profile: RuntimeProfile,
    venv_path: Path,
    package: str | None = None,
    editable_source: Path | None = None,
    upgrade_pip: bool = True,
) -> dict[str, object]:
    python = venv_python_path(venv_path)
    if not python.exists():
        create_runtime(venv_path=venv_path)
    if upgrade_pip:
        run_checked([str(python), "-m", "pip", "install", "-U", "pip"])
    install_args = package_install_args(profile, package=package, editable_source=editable_source)
    run_checked([str(python), "-m", "pip", "install", *install_args])
    return {
        "action": "install",
        "profile": profile.name,
        "venv": str(venv_path),
        "python": str(python),
        "installArgs": install_args,
        "modules": module_status(python, profile.required_modules),
    }


def ensure_runtime(
    *,
    profile: RuntimeProfile,
    venv_path: Path,
    package: str | None = None,
    editable_source: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    env = env or os.environ
    config = load_runtime_config(env=env)
    actions: list[dict[str, object]] = []
    python = venv_python_path(venv_path)
    if not python.exists():
        actions.append(create_runtime(venv_path=venv_path))
    status = doctor_payload(profile=profile, venv_path=venv_path, env=env)
    if status["ok"]:
        status["actions"] = actions
        return status
    if env.get(RUNTIME_SKIP_INSTALL_ENV) == "1" or not config.auto_install:
        status["actions"] = actions
        return status
    actions.append(
        install_runtime(profile=profile, venv_path=venv_path, package=package, editable_source=editable_source)
    )
    status = doctor_payload(profile=profile, venv_path=venv_path, env=env)
    status["actions"] = actions
    return status


def configure_runtime(
    *,
    mode: str | None = None,
    python: Path | None = None,
    venv: Path | None = None,
    package: str | None = None,
    auto_install: bool | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, object]:
    current = load_runtime_config(env=env)
    updated = RuntimeConfig(
        schema_version=current.schema_version,
        mode=mode if mode is not None else current.mode,
        python=str(python.expanduser()) if python is not None else current.python,
        venv=str(venv.expanduser()) if venv is not None else current.venv,
        package=package if package is not None else current.package,
        auto_install=auto_install if auto_install is not None else current.auto_install,
    )
    path = save_runtime_config(updated, env=env)
    return {
        "ok": True,
        "action": "configure",
        "runtimeConfigPath": str(path),
        "runtimeConfig": runtime_config_payload(updated),
    }


def reset_runtime_config(env: Mapping[str, str] | None = None) -> dict[str, object]:
    path = runtime_config_path(env)
    existed = path.exists()
    if existed:
        path.unlink()
    return {
        "ok": True,
        "action": "reset-config",
        "runtimeConfigPath": str(path),
        "removed": existed,
    }


def print_payload(payload: Mapping[str, object], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    ok = "OK" if payload.get("ok", True) else "NEEDS SETUP"
    print(f"{ok} Culvia runtime")
    for key in ("profile", "runtimeConfigPath", "venv", "venvPython", "runtimeHome"):
        value = payload.get(key)
        if isinstance(value, dict):
            value = value.get("name")
        if value:
            print(f"{key}: {value}")
    runtime_config = payload.get("runtimeConfig")
    if isinstance(runtime_config, dict):
        for key in ("mode", "python", "venv", "package", "autoInstall"):
            if key in runtime_config:
                print(f"{key}: {runtime_config[key]}")
    missing = payload.get("missingModules")
    if missing:
        print(f"missingModules: {', '.join(str(item) for item in missing)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage Culvia Python runtimes.")
    subcommands = parser.add_subparsers(dest="command", required=True)
    for name in ("doctor", "create", "install", "ensure"):
        command = subcommands.add_parser(name)
        command.add_argument("--profile", default=None, choices=sorted(RUNTIME_PROFILES))
        command.add_argument("--venv", type=Path, default=None)
        command.add_argument("--json", action="store_true")
        if name in {"install", "ensure"}:
            command.add_argument(
                "--package", default=None, help=f"Package spec override. Also supports ${RUNTIME_PACKAGE_ENV}."
            )
            command.add_argument("--editable-source", type=Path, default=None)
            command.add_argument("--no-pip-upgrade", action="store_true")
    config_command = subcommands.add_parser("config")
    config_command.add_argument("--json", action="store_true")
    configure_command = subcommands.add_parser("configure")
    configure_command.add_argument("--mode", choices=["full", "lite", "auto", "dev"], default=None)
    configure_command.add_argument("--python", type=Path, default=None)
    configure_command.add_argument("--venv", type=Path, default=None)
    configure_command.add_argument("--package", default=None)
    configure_command.add_argument("--auto-install", action=argparse.BooleanOptionalAction, default=None)
    configure_command.add_argument("--json", action="store_true")
    reset_command = subcommands.add_parser("reset-config")
    reset_command.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_runtime_config()
        if args.command == "config":
            payload = {
                "ok": True,
                "runtimeConfigPath": str(runtime_config_path()),
                "runtimeConfig": runtime_config_payload(config),
            }
        elif args.command == "configure":
            payload = configure_runtime(
                mode=args.mode,
                python=args.python,
                venv=args.venv,
                package=args.package,
                auto_install=args.auto_install,
            )
        elif args.command == "reset-config":
            payload = reset_runtime_config()
        else:
            profile = profile_by_name(args.profile)
            venv_path = Path(args.venv).expanduser() if args.venv else default_venv_path(config=config)
            payload = _runtime_command_payload(args, profile=profile, venv_path=venv_path)
    except Exception as exc:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"FAIL Culvia runtime: {exc}", file=sys.stderr)
        return 1
    print_payload(payload, as_json=bool(args.json))
    return 0 if payload.get("ok", True) else 1


def _runtime_command_payload(
    args: argparse.Namespace, *, profile: RuntimeProfile, venv_path: Path
) -> dict[str, object]:
    if args.command == "doctor":
        payload = doctor_payload(profile=profile, venv_path=venv_path)
    elif args.command == "create":
        payload = create_runtime(venv_path=venv_path)
        payload["ok"] = True
    elif args.command == "install":
        payload = install_runtime(
            profile=profile,
            venv_path=venv_path,
            package=args.package,
            editable_source=args.editable_source,
            upgrade_pip=not args.no_pip_upgrade,
        )
        payload["ok"] = not payload.get("modules", {}).get("missing")  # type: ignore[union-attr]
    elif args.command == "ensure":
        payload = ensure_runtime(
            profile=profile,
            venv_path=venv_path,
            package=args.package,
            editable_source=args.editable_source,
        )
    else:  # pragma: no cover - argparse guarantees the command set.
        raise ValueError(args.command)
    return payload


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
