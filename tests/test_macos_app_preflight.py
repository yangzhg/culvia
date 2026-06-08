from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import check_macos_app_preflight


ROOT = Path(__file__).resolve().parents[1]


def copy_app_fixture(target: Path) -> None:
    source = ROOT / "desktop/tauri/src-tauri/tauri.conf.json"
    destination = target / "desktop/tauri/src-tauri/tauri.conf.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


class MacosAppPreflightTests(unittest.TestCase):
    def test_command_available_checks_known_toolchain_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            cargo = bin_dir / "cargo"
            bin_dir.mkdir()
            cargo.write_text("#!/bin/sh\n", encoding="utf-8")

            with (
                patch("tools.check_macos_app_preflight.shutil.which", return_value=None),
                patch("tools.check_macos_app_preflight.EXTRA_TOOLCHAIN_DIRECTORIES", (bin_dir,)),
            ):
                available = check_macos_app_preflight.command_available("cargo")

        self.assertTrue(available)

    def test_ad_hoc_identity_is_local_build_compatible_without_apple_development_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_app_fixture(root)
            with (
                patch("tools.check_macos_app_preflight.command_available", return_value=True),
                patch("tools.check_macos_app_preflight.xcode_license_check", return_value=(True, "accepted")),
                patch("tools.check_macos_app_preflight.codesigning_identities", return_value=([], "none")),
            ):
                checks, meta = check_macos_app_preflight.collect_checks(root=root, env={}, system="darwin")
                payload = check_macos_app_preflight.result_payload(checks, meta)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["selectedIdentity"], "-")
        self.assertIn("apple development identity is visible", payload["skipped"])

    def test_require_apple_development_fails_when_identity_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_app_fixture(root)
            with (
                patch("tools.check_macos_app_preflight.command_available", return_value=True),
                patch("tools.check_macos_app_preflight.xcode_license_check", return_value=(True, "accepted")),
                patch("tools.check_macos_app_preflight.codesigning_identities", return_value=([], "none")),
            ):
                checks, meta = check_macos_app_preflight.collect_checks(
                    root=root,
                    env={},
                    system="darwin",
                    require_apple_development=True,
                )
                payload = check_macos_app_preflight.result_payload(checks, meta)

        self.assertFalse(payload["ok"])
        self.assertIn("apple development identity is visible", payload["failed"])

    def test_visible_apple_development_identity_is_selected_and_used_in_next_commands(self) -> None:
        identity = "Apple Development: Example (TEAMID)"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_app_fixture(root)
            with (
                patch("tools.check_macos_app_preflight.command_available", return_value=True),
                patch("tools.check_macos_app_preflight.xcode_license_check", return_value=(True, "accepted")),
                patch("tools.check_macos_app_preflight.codesigning_identities", return_value=([identity], identity)),
            ):
                checks, meta = check_macos_app_preflight.collect_checks(root=root, env={}, system="darwin")
                payload = check_macos_app_preflight.result_payload(checks, meta)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["selectedIdentity"], identity)
        self.assertIn(identity, payload["nextCommands"][1])
        self.assertIn("CULVIA_MACOS_BACKEND_CODESIGN_IDENTITY", payload["nextCommands"][1])

    def test_explicit_identity_must_be_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_app_fixture(root)
            env = {"APPLE_SIGNING_IDENTITY": "Apple Development: Missing (TEAMID)"}
            with (
                patch("tools.check_macos_app_preflight.command_available", return_value=True),
                patch("tools.check_macos_app_preflight.xcode_license_check", return_value=(True, "accepted")),
                patch("tools.check_macos_app_preflight.codesigning_identities", return_value=([], "none")),
            ):
                checks, meta = check_macos_app_preflight.collect_checks(root=root, env=env, system="darwin")
                payload = check_macos_app_preflight.result_payload(checks, meta)

        self.assertFalse(payload["ok"])
        self.assertIn("selected signing identity is visible", payload["failed"])

    def test_xcode_license_failure_is_a_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_app_fixture(root)
            with (
                patch("tools.check_macos_app_preflight.command_available", return_value=True),
                patch(
                    "tools.check_macos_app_preflight.xcode_license_check",
                    return_value=(False, "You have not agreed to the Xcode license"),
                ),
                patch("tools.check_macos_app_preflight.codesigning_identities", return_value=([], "none")),
            ):
                checks, meta = check_macos_app_preflight.collect_checks(root=root, env={}, system="darwin")
                payload = check_macos_app_preflight.result_payload(checks, meta)

        self.assertFalse(payload["ok"])
        self.assertIn("xcode license is accepted", payload["failed"])

    def test_app_cleanup_candidates_fail_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_app_fixture(root)
            (root / "desktop" / "tauri" / "src-tauri" / "target").mkdir(parents=True)
            with (
                patch("tools.check_macos_app_preflight.command_available", return_value=True),
                patch("tools.check_macos_app_preflight.xcode_license_check", return_value=(True, "accepted")),
                patch("tools.check_macos_app_preflight.codesigning_identities", return_value=([], "none")),
            ):
                checks, meta = check_macos_app_preflight.collect_checks(root=root, env={}, system="darwin")
                payload = check_macos_app_preflight.result_payload(checks, meta)

        self.assertFalse(payload["ok"])
        self.assertIn("macos app artifact cleanup state is clean", payload["failed"])

    def test_general_runtime_artifacts_do_not_block_app_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_app_fixture(root)
            (root / "build").mkdir()
            (root / "scores.sqlite").write_text("db", encoding="utf-8")
            with (
                patch("tools.check_macos_app_preflight.command_available", return_value=True),
                patch("tools.check_macos_app_preflight.xcode_license_check", return_value=(True, "accepted")),
                patch("tools.check_macos_app_preflight.codesigning_identities", return_value=([], "none")),
            ):
                checks, meta = check_macos_app_preflight.collect_checks(root=root, env={}, system="darwin")
                payload = check_macos_app_preflight.result_payload(checks, meta)

        self.assertTrue(payload["ok"])
        self.assertIn("macos app artifact cleanup state is clean", payload["passed"])

    def test_existing_artifacts_can_be_informational_after_app_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_app_fixture(root)
            (root / "desktop" / "tauri" / "src-tauri" / "target").mkdir(parents=True)
            with (
                patch("tools.check_macos_app_preflight.command_available", return_value=True),
                patch("tools.check_macos_app_preflight.xcode_license_check", return_value=(True, "accepted")),
                patch("tools.check_macos_app_preflight.codesigning_identities", return_value=([], "none")),
            ):
                checks, meta = check_macos_app_preflight.collect_checks(
                    root=root,
                    env={},
                    system="darwin",
                    require_clean=False,
                )
                payload = check_macos_app_preflight.result_payload(checks, meta)

        self.assertTrue(payload["ok"])
        self.assertIn("macos app artifact cleanup state is clean", payload["skipped"])

    def test_invalid_config_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "desktop/tauri/src-tauri/tauri.conf.json"
            config.parent.mkdir(parents=True)
            config.write_text("{bad", encoding="utf-8")
            with (
                patch("tools.check_macos_app_preflight.command_available", return_value=True),
                patch("tools.check_macos_app_preflight.xcode_license_check", return_value=(True, "accepted")),
                patch("tools.check_macos_app_preflight.codesigning_identities", return_value=([], "none")),
            ):
                checks, meta = check_macos_app_preflight.collect_checks(root=root, env={}, system="darwin")
                payload = check_macos_app_preflight.result_payload(checks, meta)

        self.assertFalse(payload["ok"])
        self.assertIn("desktop shell config is valid json", payload["failed"])

    def test_json_main_reports_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_app_fixture(root)
            with (
                patch("tools.check_macos_app_preflight.command_available", return_value=True),
                patch("tools.check_macos_app_preflight.xcode_license_check", return_value=(True, "accepted")),
                patch("tools.check_macos_app_preflight.codesigning_identities", return_value=([], "none")),
                patch("sys.stdout") as stdout,
            ):
                chunks: list[str] = []
                stdout.write.side_effect = chunks.append
                result = check_macos_app_preflight.main(["--root", str(root), "--system", "darwin", "--json"])

        self.assertEqual(result, 0)
        payload = json.loads("".join(chunks))
        self.assertTrue(payload["ok"])
        self.assertIn("xcode license is accepted", payload["passed"])
        self.assertIn("nextCommands", payload)


if __name__ == "__main__":
    unittest.main()
