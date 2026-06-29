from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import tools.pre_commit_checks as checks


ROOT = Path(__file__).resolve().parents[1]


class PreCommitChecksTests(unittest.TestCase):
    def test_pre_commit_config_registers_project_checks(self) -> None:
        config = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")

        for hook_id in (
            "ruff-format",
            "ruff-high-signal-lint",
            "web-js-syntax",
            "shell-syntax",
            "makefile-smoke",
            "rust-format",
            "secret-scan",
        ):
            self.assertIn(f"id: {hook_id}", config)

        self.assertIn("detect-private-key", config)
        self.assertIn("pre-commit-hooks", config)

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

    def test_rust_format_command_targets_desktop_manifest(self) -> None:
        self.assertEqual(
            checks.rust_format_command(),
            (
                "cargo",
                "fmt",
                "--manifest-path",
                "desktop/tauri/src-tauri/Cargo.toml",
                "--all",
                "--",
                "--check",
            ),
        )
        self.assertEqual(
            checks.rust_format_command(fix=True),
            (
                "cargo",
                "fmt",
                "--manifest-path",
                "desktop/tauri/src-tauri/Cargo.toml",
                "--all",
            ),
        )


if __name__ == "__main__":
    unittest.main()
