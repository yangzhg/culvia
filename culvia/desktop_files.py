from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Protocol

from culvia.capabilities import native_folder_picker_available, reveal_in_file_manager_available


class CommandRunner(Protocol):
    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]: ...


class DesktopActionError(Exception):
    """Raised when a supported desktop action fails unexpectedly."""


class DesktopActionUnsupported(DesktopActionError):
    """Raised when the current platform cannot perform the desktop action."""


class DesktopActionCancelled(DesktopActionError):
    """Raised when the user cancels a desktop action."""


def _platform_name(platform: str | None) -> str:
    return platform or sys.platform


def _command_path(command: str, which: Any = None) -> str | None:
    resolver = which
    if resolver is None:
        from shutil import which as default_which

        resolver = default_which
    return resolver(command)


def _first_command(commands: tuple[str, ...], which: Any = None) -> str | None:
    for command in commands:
        if _command_path(command, which):
            return command
    return None


def _normalize_folder_output(value: object, platform: str) -> str:
    folder = str(value or "").strip()
    if platform == "darwin" or platform.startswith("linux"):
        folder = "/" if folder == "/" else folder.rstrip("/")
    if not folder:
        raise DesktopActionError("系统没有返回目录路径。")
    return folder


def _normalize_folder_outputs(value: object, platform: str) -> list[str]:
    folders: list[str] = []
    seen: set[str] = set()
    for line in str(value or "").splitlines():
        folder_text = line.strip()
        if not folder_text:
            continue
        folder = _normalize_folder_output(folder_text, platform)
        if folder in seen:
            continue
        folders.append(folder)
        seen.add(folder)
    if not folders:
        raise DesktopActionError("系统没有返回目录路径。")
    return folders


def _folder_picker_command(
    prompt: str,
    platform: str,
    which: Any = None,
    *,
    multiple: bool = False,
) -> tuple[list[str], dict[str, str] | None]:
    if platform == "darwin":
        prompt_json = json.dumps(prompt, ensure_ascii=False)
        if multiple:
            script = (
                f"set chosenFolders to choose folder with prompt {prompt_json} with multiple selections allowed\n"
                'set folderLines to ""\n'
                "repeat with folderAlias in chosenFolders\n"
                "set folderLines to folderLines & POSIX path of folderAlias & linefeed\n"
                "end repeat\n"
                "return folderLines"
            )
        else:
            script = f"POSIX path of (choose folder with prompt {prompt_json})"
        return ["osascript", "-e", script], None
    if platform.startswith(("win32", "cygwin", "msys")):
        shell = _first_command(("powershell", "pwsh"), which) or "powershell"
        script = (
            "$ErrorActionPreference = 'Stop'; "
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$dialog.Description = $env:CULVIA_DIALOG_PROMPT; "
            "$dialog.ShowNewFolderButton = $true; "
            "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) "
            "{ [Console]::Out.WriteLine($dialog.SelectedPath) } else { exit 1 }"
        )
        env = dict(os.environ)
        env["CULVIA_DIALOG_PROMPT"] = prompt
        return [shell, "-NoProfile", "-NonInteractive", "-STA", "-Command", script], env
    if platform.startswith("linux"):
        if _command_path("zenity", which):
            command = ["zenity", "--file-selection", "--directory", "--title", prompt]
            if multiple:
                command.insert(3, "--multiple")
                command.insert(4, "--separator=\n")
            return command, None
        if _command_path("kdialog", which):
            return ["kdialog", "--title", prompt, "--getexistingdirectory", str(Path.home())], None
    raise DesktopActionUnsupported("当前环境不支持原生目录选择。请直接输入目录路径。")


def choose_folder_path(
    prompt: str,
    *,
    platform: str | None = None,
    which: Any = None,
    runner: CommandRunner | None = None,
    timeout: float = 120,
) -> str:
    platform_name = _platform_name(platform)
    if not native_folder_picker_available(platform_name, which):
        raise DesktopActionUnsupported("当前环境不支持原生目录选择。请直接输入目录路径。")

    try:
        command_runner = runner or subprocess.run
        command, extra_env = _folder_picker_command(prompt, platform_name, which)
        run_kwargs: dict[str, Any] = {
            "check": False,
            "capture_output": True,
            "text": True,
            "timeout": timeout,
        }
        if extra_env is not None:
            run_kwargs["env"] = extra_env
        result = command_runner(
            command,
            **run_kwargs,
        )
    except Exception as exc:
        raise DesktopActionError(repr(exc)) from exc

    if result.returncode != 0:
        raise DesktopActionCancelled("用户取消了目录选择。")

    return _normalize_folder_output(result.stdout, platform_name)


def choose_folder_paths(
    prompt: str,
    *,
    platform: str | None = None,
    which: Any = None,
    runner: CommandRunner | None = None,
    timeout: float = 120,
) -> list[str]:
    platform_name = _platform_name(platform)
    if not native_folder_picker_available(platform_name, which):
        raise DesktopActionUnsupported("当前环境不支持原生目录选择。请直接输入目录路径。")

    try:
        command_runner = runner or subprocess.run
        command, extra_env = _folder_picker_command(prompt, platform_name, which, multiple=True)
        run_kwargs: dict[str, Any] = {
            "check": False,
            "capture_output": True,
            "text": True,
            "timeout": timeout,
        }
        if extra_env is not None:
            run_kwargs["env"] = extra_env
        result = command_runner(
            command,
            **run_kwargs,
        )
    except Exception as exc:
        raise DesktopActionError(repr(exc)) from exc

    if result.returncode != 0:
        raise DesktopActionCancelled("用户取消了目录选择。")

    return _normalize_folder_outputs(result.stdout, platform_name)


def _reveal_command(path: Path, platform: str, which: Any = None) -> list[str]:
    if platform == "darwin":
        return ["open", "-R", str(path)]
    if platform.startswith(("win32", "cygwin", "msys")):
        return ["explorer", f"/select,{path}"]
    if platform.startswith("linux"):
        target = path if path.is_dir() else path.parent
        if _command_path("xdg-open", which):
            return ["xdg-open", str(target)]
        if _command_path("gio", which):
            return ["gio", "open", str(target)]
    raise DesktopActionUnsupported("当前环境不支持在文件管理器中定位。")


def reveal_path_in_file_manager(
    path: str | Path,
    *,
    platform: str | None = None,
    which: Any = None,
    runner: CommandRunner | None = None,
) -> None:
    platform_name = _platform_name(platform)
    if not reveal_in_file_manager_available(platform_name, which):
        raise DesktopActionUnsupported("当前环境不支持在文件管理器中定位。")

    try:
        command_runner = runner or subprocess.run
        command_runner(_reveal_command(Path(path), platform_name, which), check=False)
    except Exception as exc:
        raise DesktopActionError(repr(exc)) from exc
