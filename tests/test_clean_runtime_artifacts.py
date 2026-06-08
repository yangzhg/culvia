from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools import clean_runtime_artifacts


def paths(payload: dict, key: str = "candidates") -> set[str]:
    return {item["path"] for item in payload[key]}


class CleanRuntimeArtifactsTests(unittest.TestCase):
    def test_dry_run_reports_known_artifacts_without_deleting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "bin").mkdir()
            (root / "bin" / "culvia-web").write_text("source launcher", encoding="utf-8")
            (root / "build").mkdir()
            (root / "build" / "output.txt").write_text("build", encoding="utf-8")
            (root / "culvia.egg-info").mkdir()
            (root / "culvia.egg-info" / "PKG-INFO").write_text("meta", encoding="utf-8")
            (root / "desktop" / "tauri" / "src-tauri" / "target").mkdir(parents=True)
            (root / "desktop" / "tauri" / "src-tauri" / "target" / "artifact").write_text(
                "desktop-build", encoding="utf-8"
            )
            (root / "web").mkdir()
            (root / "web" / "app.js").write_text("source\n", encoding="utf-8")

            payload = clean_runtime_artifacts.run_cleanup(root=root, apply=False)

            self.assertFalse(payload["applied"])
            self.assertEqual(payload["removedCount"], 0)
            self.assertIn("build", paths(payload))
            self.assertIn("culvia.egg-info", paths(payload))
            self.assertIn("desktop/tauri/src-tauri/target", paths(payload))
            self.assertNotIn("bin", paths(payload))
            self.assertTrue((root / "bin" / "culvia-web").exists())
            self.assertTrue((root / "web" / "app.js").exists())

    def test_apply_deletes_candidates_and_keeps_source_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "analysis_cache").mkdir()
            (root / "analysis_cache" / "x").write_text("cache", encoding="utf-8")
            (root / "scores.sqlite").write_text("db", encoding="utf-8")
            (root / "culvia").mkdir()
            (root / "culvia" / "server.py").write_text("source\n", encoding="utf-8")

            payload = clean_runtime_artifacts.run_cleanup(root=root, apply=True)

            self.assertTrue(payload["applied"])
            self.assertIn("analysis_cache", paths(payload, "removed"))
            self.assertIn("scores.sqlite", paths(payload, "removed"))
            self.assertFalse((root / "analysis_cache").exists())
            self.assertFalse((root / "scores.sqlite").exists())
            self.assertTrue((root / "culvia" / "server.py").exists())

    def test_recursive_python_noise_is_removed_without_touching_git(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".git" / "objects").mkdir(parents=True)
            (root / ".git" / "objects" / "ignored.pyc").write_bytes(b"git")
            (root / "culvia" / "__pycache__").mkdir(parents=True)
            (root / "culvia" / "__pycache__" / "server.cpython-311.pyc").write_bytes(b"pyc")
            (root / "web").mkdir()
            (root / "web" / ".DS_Store").write_bytes(b"noise")

            payload = clean_runtime_artifacts.run_cleanup(root=root, apply=True)

            self.assertIn("culvia/__pycache__", paths(payload, "removed"))
            self.assertIn("web/.DS_Store", paths(payload, "removed"))
            self.assertFalse((root / "culvia" / "__pycache__").exists())
            self.assertFalse((root / "web" / ".DS_Store").exists())
            self.assertTrue((root / ".git" / "objects" / "ignored.pyc").exists())

    def test_apply_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "thumbnail_cache").mkdir()

            first = clean_runtime_artifacts.run_cleanup(root=root, apply=True)
            second = clean_runtime_artifacts.run_cleanup(root=root, apply=True)

            self.assertEqual(first["removedCount"], 1)
            self.assertEqual(second["candidateCount"], 0)
            self.assertEqual(second["removedCount"], 0)


if __name__ == "__main__":
    unittest.main()
