from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools import clean_macos_app_artifacts


def paths(payload: dict, key: str = "candidates") -> set[str]:
    return {item["path"] for item in payload[key]}


class CleanMacosAppArtifactsTests(unittest.TestCase):
    def test_dry_run_reports_only_desktop_app_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "build").mkdir()
            (root / "scores.sqlite").write_text("db", encoding="utf-8")
            (root / "desktop" / "tauri" / "node_modules").mkdir(parents=True)
            (root / "desktop" / "tauri" / "src-tauri" / "gen").mkdir(parents=True)
            runtime_root = root / "desktop" / "tauri" / "src-tauri" / "runtime" / "backend"
            (runtime_root / "aarch64-apple-darwin").mkdir(parents=True)
            (runtime_root / ".gitkeep").write_text("", encoding="utf-8")
            (root / "desktop" / "tauri" / "src-tauri" / "target").mkdir(parents=True)

            payload = clean_macos_app_artifacts.run_cleanup(root=root, apply=False)

            self.assertEqual(
                paths(payload),
                {
                    "desktop/tauri/src-tauri/gen",
                    "desktop/tauri/src-tauri/runtime/backend/aarch64-apple-darwin",
                    "desktop/tauri/src-tauri/target",
                },
            )
            self.assertTrue((root / "build").exists())
            self.assertTrue((root / "scores.sqlite").exists())
            self.assertTrue((root / "desktop" / "tauri" / "node_modules").exists())
            self.assertTrue((runtime_root / ".gitkeep").exists())

    def test_apply_deletes_app_outputs_and_keeps_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "desktop" / "tauri" / "node_modules").mkdir(parents=True)
            (root / "desktop" / "tauri" / "src-tauri" / "target").mkdir(parents=True)
            (root / "desktop" / "tauri" / "src-tauri" / "target" / "release").mkdir()
            (root / "desktop" / "tauri" / "src-tauri" / "target" / "release" / "app").write_text(
                "bundle",
                encoding="utf-8",
            )

            payload = clean_macos_app_artifacts.run_cleanup(root=root, apply=True)

            self.assertEqual(paths(payload, "removed"), {"desktop/tauri/src-tauri/target"})
            self.assertFalse((root / "desktop" / "tauri" / "src-tauri" / "target").exists())
            self.assertTrue((root / "desktop" / "tauri" / "node_modules").exists())

    def test_apply_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "desktop" / "tauri" / "src-tauri" / "gen").mkdir(parents=True)

            first = clean_macos_app_artifacts.run_cleanup(root=root, apply=True)
            second = clean_macos_app_artifacts.run_cleanup(root=root, apply=True)

            self.assertEqual(first["removedCount"], 1)
            self.assertEqual(second["candidateCount"], 0)
            self.assertEqual(second["removedCount"], 0)


if __name__ == "__main__":
    unittest.main()
