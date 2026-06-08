from __future__ import annotations

import unittest

from culvia.capabilities import (
    local_capabilities,
    native_folder_picker_available,
    reveal_in_file_manager_available,
)


class CapabilityTests(unittest.TestCase):
    def test_macos_reports_native_folder_picker_when_osascript_exists(self) -> None:
        self.assertTrue(native_folder_picker_available("darwin", lambda command: f"/usr/bin/{command}"))

    def test_non_macos_disables_native_folder_picker(self) -> None:
        self.assertFalse(native_folder_picker_available("linux", lambda _: None))

    def test_windows_reports_native_folder_picker_when_powershell_exists(self) -> None:
        self.assertTrue(
            native_folder_picker_available(
                "win32",
                lambda command: (
                    "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe" if command == "powershell" else None
                ),
            )
        )

    def test_linux_reports_native_folder_picker_when_zenity_exists(self) -> None:
        self.assertTrue(
            native_folder_picker_available("linux", lambda command: "/usr/bin/zenity" if command == "zenity" else None)
        )

    def test_reveal_requires_macos_open_command(self) -> None:
        self.assertTrue(
            reveal_in_file_manager_available("darwin", lambda command: "/usr/bin/open" if command == "open" else None)
        )
        self.assertFalse(reveal_in_file_manager_available("darwin", lambda _: None))

    def test_reveal_supports_windows_and_linux_file_managers(self) -> None:
        self.assertTrue(
            reveal_in_file_manager_available("win32", lambda command: "explorer.exe" if command == "explorer" else None)
        )
        self.assertTrue(
            reveal_in_file_manager_available(
                "linux", lambda command: "/usr/bin/xdg-open" if command == "xdg-open" else None
            )
        )
        self.assertTrue(
            reveal_in_file_manager_available("linux", lambda command: "/usr/bin/gio" if command == "gio" else None)
        )

    def test_local_capabilities_are_web_and_platform_aware(self) -> None:
        payload = local_capabilities("linux", lambda _: None)

        self.assertEqual(payload["mode"], "local")
        self.assertEqual(payload["platform"], "linux")
        self.assertTrue(payload["web"])
        self.assertTrue(payload["supervisor"])
        self.assertTrue(payload["directoryUpload"])
        self.assertTrue(payload["llmVisionReview"])
        self.assertFalse(payload["nativeFolderPicker"])
        self.assertFalse(payload["revealInFileManager"])

    def test_local_capabilities_enable_linux_native_actions_when_commands_exist(self) -> None:
        def resolver(command: str) -> str | None:
            return f"/usr/bin/{command}" if command in {"zenity", "xdg-open"} else None

        payload = local_capabilities("linux", resolver)

        self.assertTrue(payload["nativeFolderPicker"])
        self.assertTrue(payload["revealInFileManager"])


if __name__ == "__main__":
    unittest.main()
