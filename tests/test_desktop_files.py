from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock

from culvia.desktop_files import (
    DesktopActionCancelled,
    DesktopActionUnsupported,
    choose_folder_path,
    choose_folder_paths,
    reveal_path_in_file_manager,
)


class DesktopFilesTests(unittest.TestCase):
    def test_choose_folder_rejects_unsupported_platform_without_running_command(self) -> None:
        runner = Mock()

        with self.assertRaises(DesktopActionUnsupported):
            choose_folder_path("选择照片目录", platform="linux", which=lambda _: None, runner=runner)

        runner.assert_not_called()

    def test_choose_folder_returns_normalized_posix_path(self) -> None:
        runner = Mock(
            return_value=subprocess.CompletedProcess(["osascript"], 0, stdout="/Users/me/Pictures/\n", stderr="")
        )

        folder = choose_folder_path(
            '选择"照片"目录',
            platform="darwin",
            which=lambda command: f"/usr/bin/{command}",
            runner=runner,
        )

        self.assertEqual(folder, "/Users/me/Pictures")
        command = runner.call_args.args[0]
        self.assertEqual(command[0], "osascript")
        self.assertIn('\\"照片\\"', command[2])

    def test_choose_folder_paths_returns_multiple_normalized_macos_paths(self) -> None:
        runner = Mock(
            return_value=subprocess.CompletedProcess(
                ["osascript"], 0, stdout="/Users/me/Pictures/\n/Users/me/Archive/\n", stderr=""
            )
        )

        folders = choose_folder_paths(
            "Pick photos",
            platform="darwin",
            which=lambda command: f"/usr/bin/{command}",
            runner=runner,
        )

        self.assertEqual(folders, ["/Users/me/Pictures", "/Users/me/Archive"])
        command = runner.call_args.args[0]
        self.assertEqual(command[0], "osascript")
        self.assertIn("multiple selections allowed", command[2])

    def test_choose_folder_uses_windows_folder_browser_dialog(self) -> None:
        runner = Mock(return_value=subprocess.CompletedProcess(["powershell"], 0, stdout="C:\\Photos\r\n", stderr=""))

        folder = choose_folder_path(
            "Pick photos",
            platform="win32",
            which=lambda command: (
                "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe" if command == "powershell" else None
            ),
            runner=runner,
        )

        self.assertEqual(folder, "C:\\Photos")
        command = runner.call_args.args[0]
        kwargs = runner.call_args.kwargs
        self.assertEqual(command[0], "powershell")
        self.assertIn("System.Windows.Forms.FolderBrowserDialog", command[-1])
        self.assertEqual(kwargs["env"]["CULVIA_DIALOG_PROMPT"], "Pick photos")

    def test_choose_folder_uses_linux_zenity_dialog(self) -> None:
        runner = Mock(return_value=subprocess.CompletedProcess(["zenity"], 0, stdout="/home/me/Pictures/\n", stderr=""))

        folder = choose_folder_path(
            "Pick photos",
            platform="linux",
            which=lambda command: "/usr/bin/zenity" if command == "zenity" else None,
            runner=runner,
        )

        self.assertEqual(folder, "/home/me/Pictures")
        runner.assert_called_once_with(
            ["zenity", "--file-selection", "--directory", "--title", "Pick photos"],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_choose_folder_paths_uses_linux_zenity_multiple_dialog(self) -> None:
        runner = Mock(
            return_value=subprocess.CompletedProcess(
                ["zenity"], 0, stdout="/home/me/Pictures\n/home/me/Archive\n", stderr=""
            )
        )

        folders = choose_folder_paths(
            "Pick photos",
            platform="linux",
            which=lambda command: "/usr/bin/zenity" if command == "zenity" else None,
            runner=runner,
        )

        self.assertEqual(folders, ["/home/me/Pictures", "/home/me/Archive"])
        runner.assert_called_once_with(
            ["zenity", "--file-selection", "--directory", "--multiple", "--separator=\n", "--title", "Pick photos"],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_choose_folder_nonzero_result_is_cancelled(self) -> None:
        runner = Mock(return_value=subprocess.CompletedProcess(["osascript"], 1, stdout="", stderr="cancelled"))

        with self.assertRaises(DesktopActionCancelled):
            choose_folder_path(
                "选择照片目录", platform="darwin", which=lambda command: f"/usr/bin/{command}", runner=runner
            )

    def test_reveal_rejects_unsupported_platform_without_running_command(self) -> None:
        runner = Mock()

        with self.assertRaises(DesktopActionUnsupported):
            reveal_path_in_file_manager("/tmp/a.jpg", platform="linux", which=lambda _: None, runner=runner)

        runner.assert_not_called()

    def test_reveal_uses_macos_open_reveal_command(self) -> None:
        runner = Mock(return_value=subprocess.CompletedProcess(["open"], 0))

        reveal_path_in_file_manager(
            Path("/Users/me/Pictures/a.jpg"),
            platform="darwin",
            which=lambda command: "/usr/bin/open" if command == "open" else None,
            runner=runner,
        )

        runner.assert_called_once_with(["open", "-R", "/Users/me/Pictures/a.jpg"], check=False)

    def test_reveal_uses_windows_explorer_select_command(self) -> None:
        runner = Mock(return_value=subprocess.CompletedProcess(["explorer"], 0))

        reveal_path_in_file_manager(
            Path("C:/Users/me/Pictures/a.jpg"),
            platform="win32",
            which=lambda command: "explorer.exe" if command == "explorer" else None,
            runner=runner,
        )

        runner.assert_called_once_with(["explorer", "/select,C:/Users/me/Pictures/a.jpg"], check=False)

    def test_reveal_uses_linux_xdg_open_parent_for_files(self) -> None:
        runner = Mock(return_value=subprocess.CompletedProcess(["xdg-open"], 0))

        reveal_path_in_file_manager(
            Path("/home/me/Pictures/a.jpg"),
            platform="linux",
            which=lambda command: "/usr/bin/xdg-open" if command == "xdg-open" else None,
            runner=runner,
        )

        runner.assert_called_once_with(["xdg-open", "/home/me/Pictures"], check=False)


if __name__ == "__main__":
    unittest.main()
