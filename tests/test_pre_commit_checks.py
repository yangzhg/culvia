from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tools.pre_commit_checks as checks


class PreCommitChecksTests(unittest.TestCase):
    def test_secret_scan_flags_openai_compatible_api_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "settings.txt"
            key = "sk-" + "1234567890abcdef123456"
            path.write_text(f"api_key={key}\n", encoding="utf-8")

            findings = checks.iter_secret_findings([path], root=root)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].label, "OpenAI-compatible API key")

    def test_secret_scan_ignores_short_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "test.txt"
            path.write_text("api_key=sk-test-key\n", encoding="utf-8")

            findings = checks.iter_secret_findings([path], root=root)

        self.assertEqual(findings, [])

    def test_secret_scan_reports_location_without_exposing_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "settings.txt"
            key = "sk-" + "1234567890abcdef123456"
            path.write_text(f"api_key={key}\n", encoding="utf-8")
            output = io.StringIO()

            with patch.object(checks, "git_tracked_files", return_value=[path]), patch("sys.stderr", output):
                status = checks.check_secret_scan(root=root)

        self.assertEqual(status, 1)
        self.assertIn("settings.txt:1: OpenAI-compatible API key", output.getvalue())
        self.assertNotIn(key, output.getvalue())


if __name__ == "__main__":
    unittest.main()
