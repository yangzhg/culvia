from __future__ import annotations

import io
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import check_desktop_readiness


ROOT = Path(__file__).resolve().parents[1]


class DesktopReadinessTests(unittest.TestCase):
    def test_current_repo_passes_static_checks_with_optional_toolchain_skips(self) -> None:
        with patch("tools.check_desktop_readiness.command_available", return_value=False):
            payload = check_desktop_readiness.result_payload(check_desktop_readiness.collect_checks(ROOT))

        self.assertTrue(payload["ok"], payload["failed"])
        self.assertIn("rust toolchain available", payload["skipped"])
        self.assertIn("node/npm available for desktop shell cli", payload["skipped"])

    def test_strict_toolchain_fails_when_rust_or_npm_are_missing(self) -> None:
        with patch("tools.check_desktop_readiness.command_available", return_value=False):
            payload = check_desktop_readiness.result_payload(
                check_desktop_readiness.collect_checks(ROOT, strict_toolchain=True)
            )

        self.assertFalse(payload["ok"])
        self.assertIn("rust toolchain available", payload["failed"])
        self.assertIn("node/npm available for desktop shell cli", payload["failed"])

    def test_main_outputs_json(self) -> None:
        with patch("tools.check_desktop_readiness.command_available", return_value=False):
            output = io.StringIO()
            with patch("sys.stdout", output):
                self.assertEqual(check_desktop_readiness.main(["--root", str(ROOT), "--json"]), 0)

        self.assertIn('"ok": true', output.getvalue())


if __name__ == "__main__":
    unittest.main()
