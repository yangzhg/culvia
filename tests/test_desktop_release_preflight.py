from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import check_desktop_release_preflight


ROOT = Path(__file__).resolve().parents[1]


def copy_preflight_fixture(target: Path) -> None:
    for relative in (
        "desktop/tauri/src-tauri/tauri.conf.json",
        "desktop/tauri/src-tauri/icons/32x32.png",
        "desktop/tauri/src-tauri/icons/128x128.png",
        "desktop/tauri/src-tauri/icons/128x128@2x.png",
        "desktop/tauri/src-tauri/icons/icon.icns",
        "desktop/tauri/src-tauri/icons/icon.ico",
        "desktop/tauri/src-tauri/icons/icon.png",
    ):
        source = ROOT / relative
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())


class DesktopReleasePreflightTests(unittest.TestCase):
    def test_current_repo_passes_with_missing_signing_inputs_as_optional(self) -> None:
        payload = check_desktop_release_preflight.result_payload(
            check_desktop_release_preflight.collect_checks(root=ROOT, env={})
        )

        self.assertTrue(payload["ok"])
        self.assertIn("macos signing inputs are configured", payload["skipped"])
        self.assertIn("macos notarization inputs are configured", payload["skipped"])

    def test_strict_signing_fails_without_signing_and_notarization_inputs(self) -> None:
        payload = check_desktop_release_preflight.result_payload(
            check_desktop_release_preflight.collect_checks(root=ROOT, env={}, strict_signing=True)
        )

        self.assertFalse(payload["ok"])
        self.assertIn("macos signing inputs are configured", payload["failed"])
        self.assertIn("macos notarization inputs are configured", payload["failed"])

    def test_ad_hoc_identity_does_not_satisfy_strict_signing(self) -> None:
        env = {
            "APPLE_SIGNING_IDENTITY": "-",
            "APPLE_ID": "release@example.com",
            "APPLE_PASSWORD": "app-specific-password",
            "APPLE_TEAM_ID": "TEAMID",
        }
        payload = check_desktop_release_preflight.result_payload(
            check_desktop_release_preflight.collect_checks(root=ROOT, env=env, strict_signing=True)
        )

        self.assertFalse(payload["ok"])
        self.assertIn("macos signing inputs are configured", payload["failed"])
        self.assertNotIn("macos notarization inputs are configured", payload["failed"])

    def test_apple_development_identity_does_not_satisfy_release_signing(self) -> None:
        env = {
            "APPLE_SIGNING_IDENTITY": "Apple Development: Example (TEAMID)",
            "APPLE_ID": "release@example.com",
            "APPLE_PASSWORD": "app-specific-password",
            "APPLE_TEAM_ID": "TEAMID",
        }
        payload = check_desktop_release_preflight.result_payload(
            check_desktop_release_preflight.collect_checks(root=ROOT, env=env, strict_signing=True)
        )

        self.assertFalse(payload["ok"])
        self.assertIn("macos signing inputs are configured", payload["failed"])
        self.assertNotIn("macos notarization inputs are configured", payload["failed"])

    def test_developer_id_identity_passes_strict_signing_with_notarization_inputs(self) -> None:
        env = {
            "APPLE_SIGNING_IDENTITY": "Developer ID Application: Example (TEAMID)",
            "APPLE_ID": "release@example.com",
            "APPLE_PASSWORD": "app-specific-password",
            "APPLE_TEAM_ID": "TEAMID",
        }
        with patch("tools.check_desktop_release_preflight.codesign_identity_visible", return_value=True):
            payload = check_desktop_release_preflight.result_payload(
                check_desktop_release_preflight.collect_checks(root=ROOT, env=env, strict_signing=True)
            )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["failed"], [])

    def test_ci_certificate_and_apple_id_notarization_inputs_pass_strict_signing(self) -> None:
        env = {
            "APPLE_CERTIFICATE": "base64-p12",
            "APPLE_CERTIFICATE_PASSWORD": "password",
            "APPLE_ID": "release@example.com",
            "APPLE_PASSWORD": "app-specific-password",
            "APPLE_TEAM_ID": "TEAMID",
        }
        payload = check_desktop_release_preflight.result_payload(
            check_desktop_release_preflight.collect_checks(root=ROOT, env=env, strict_signing=True)
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["failed"], [])

    def test_api_key_notarization_inputs_pass_strict_signing(self) -> None:
        env = {
            "APPLE_CERTIFICATE": "base64-p12",
            "APPLE_CERTIFICATE_PASSWORD": "password",
            "APPLE_API_KEY": "KEYID",
            "APPLE_API_ISSUER": "ISSUERID",
            "APPLE_API_KEY_PATH": "/private/key/AuthKey_KEYID.p8",
        }
        payload = check_desktop_release_preflight.result_payload(
            check_desktop_release_preflight.collect_checks(root=ROOT, env=env, strict_signing=True)
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["failed"], [])

    def test_missing_icon_fails_static_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_preflight_fixture(root)
            config_path = root / "desktop/tauri/src-tauri/tauri.conf.json"
            data = json.loads(config_path.read_text(encoding="utf-8"))
            data["bundle"]["icon"] = ["icons/missing.png"]
            config_path.write_text(json.dumps(data), encoding="utf-8")

            payload = check_desktop_release_preflight.result_payload(
                check_desktop_release_preflight.collect_checks(root=root, env={})
            )

        self.assertFalse(payload["ok"])
        self.assertIn("app icon is configured", payload["failed"])

    def test_missing_platform_icon_coverage_fails_static_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_preflight_fixture(root)
            config_path = root / "desktop/tauri/src-tauri/tauri.conf.json"
            data = json.loads(config_path.read_text(encoding="utf-8"))
            data["bundle"]["icon"] = ["icons/icon.png"]
            config_path.write_text(json.dumps(data), encoding="utf-8")

            payload = check_desktop_release_preflight.result_payload(
                check_desktop_release_preflight.collect_checks(root=root, env={})
            )

        self.assertFalse(payload["ok"])
        self.assertIn("app icons cover desktop platforms", payload["failed"])

    def test_backend_binary_check_requires_executable_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            backend = Path(tmp) / "culvia-server"
            backend.write_text("#!/bin/sh\n", encoding="utf-8")
            backend.chmod(backend.stat().st_mode | stat.S_IXUSR)

            payload = check_desktop_release_preflight.result_payload(
                check_desktop_release_preflight.collect_checks(root=ROOT, env={}, backend_binary=backend)
            )

        self.assertTrue(payload["ok"])

    def test_missing_backend_binary_fails_when_requested(self) -> None:
        payload = check_desktop_release_preflight.result_payload(
            check_desktop_release_preflight.collect_checks(
                root=ROOT,
                env={},
                backend_binary=Path("/definitely/missing/culvia-server"),
            )
        )

        self.assertFalse(payload["ok"])
        self.assertIn("backend binary is executable", payload["failed"])


if __name__ == "__main__":
    unittest.main()
