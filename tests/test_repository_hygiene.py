from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RepositoryHygieneTests(unittest.TestCase):
    def test_gitignore_excludes_runtime_data_and_secrets(self) -> None:
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

        for pattern in (
            "__pycache__/",
            "model_cache/",
            "analysis_cache/",
            "thumbnail_cache/",
            "upload_cache/",
            "culvia_uploads/",
            "*.sqlite",
            "*.sqlite-*",
            "*.sqlite3",
            "*.sqlite3-*",
            "*.db",
            "*.db-*",
            "*.csv",
            "node_modules/",
            "target/",
            "desktop/tauri/src-tauri/gen/",
            "desktop/tauri/src-tauri/runtime/*",
            "!desktop/tauri/src-tauri/runtime/backend/.gitkeep",
            ".env",
            ".env.*",
            ".codex/",
            ".agents/",
            "*.pem",
            "*.key",
            "*.token",
        ):
            self.assertIn(pattern, gitignore)

    def test_tracked_files_do_not_contain_local_private_paths(self) -> None:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        forbidden = {
            "local photography practice folder": "\u6444\u5f71" + "\u7ec3\u4e60",
            "local shoot date 1": "2026" + "-05" + "-31",
            "local shoot date 2": "2026" + "-05" + "-24",
            "local home path": "/Users/" + "byte" + "dance",
            "corporate email domain": "byte" + "dance" + ".com",
            "old local author name": "yang" + "zhengguo",
        }
        binary_suffixes = {".icns", ".ico", ".jpg", ".jpeg", ".png", ".webp"}
        matches: list[str] = []
        for relative_path in result.stdout.splitlines():
            path = ROOT / relative_path
            if path.suffix.lower() in binary_suffixes:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for label, needle in forbidden.items():
                if needle in text:
                    matches.append(f"{relative_path}: {label}")

        self.assertEqual([], matches)


if __name__ == "__main__":
    unittest.main()
