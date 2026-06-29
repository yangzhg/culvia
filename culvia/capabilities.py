from __future__ import annotations

import shutil
import sys
import os
from collections.abc import Callable, Mapping
from typing import Any


CommandResolver = Callable[[str], str | None]
DESKTOP_APP_ENV = "CULVIA_DESKTOP_APP"


def _command_available(command: str, which: CommandResolver | None = None) -> bool:
    resolver = which or shutil.which
    return bool(resolver(command))


def _platform_is_windows(platform_name: str) -> bool:
    return platform_name.startswith(("win32", "cygwin", "msys"))


def _platform_is_linux(platform_name: str) -> bool:
    return platform_name.startswith("linux")


def _any_command_available(commands: tuple[str, ...], which: CommandResolver | None = None) -> bool:
    return any(_command_available(command, which) for command in commands)


def native_folder_picker_available(platform: str | None = None, which: CommandResolver | None = None) -> bool:
    platform_name = platform or sys.platform
    if platform_name == "darwin":
        return _command_available("osascript", which)
    if _platform_is_windows(platform_name):
        return _any_command_available(("powershell", "pwsh"), which)
    if _platform_is_linux(platform_name):
        return _any_command_available(("zenity", "kdialog"), which)
    return False


def reveal_in_file_manager_available(platform: str | None = None, which: CommandResolver | None = None) -> bool:
    platform_name = platform or sys.platform
    if platform_name == "darwin":
        return _command_available("open", which)
    if _platform_is_windows(platform_name):
        return _command_available("explorer", which)
    if _platform_is_linux(platform_name):
        return _any_command_available(("xdg-open", "gio"), which)
    return False


def native_file_preview_available(platform: str | None = None, which: CommandResolver | None = None) -> bool:
    platform_name = platform or sys.platform
    if platform_name == "darwin":
        return _command_available("open", which)
    if _platform_is_windows(platform_name):
        return _any_command_available(("powershell", "pwsh"), which)
    if _platform_is_linux(platform_name):
        return _any_command_available(("xdg-open", "gio"), which)
    return False


def desktop_app_enabled(environ: Mapping[str, str] | None = None) -> bool:
    env = environ or os.environ
    return env.get(DESKTOP_APP_ENV) == "1"


def local_capabilities(
    platform: str | None = None,
    which: CommandResolver | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    platform_name = platform or sys.platform
    desktop_app = desktop_app_enabled(environ)
    return {
        "mode": "local",
        "platform": platform_name,
        "web": True,
        "desktopApp": desktop_app,
        "supervisor": True,
        "nativeFolderPicker": native_folder_picker_available(platform_name, which),
        "revealInFileManager": reveal_in_file_manager_available(platform_name, which),
        "nativeFilePreview": desktop_app and native_file_preview_available(platform_name, which),
        "directoryUpload": True,
        "llmVisionReview": True,
    }
