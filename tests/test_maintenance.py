from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from culvia.maintenance import (
    clear_history_cache,
    clear_local_data,
    clear_model_caches,
    remove_path_safely,
    resolve_history_cache_path,
)


class MaintenanceTests(unittest.TestCase):
    def test_remove_path_safely_handles_files_dirs_and_missing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file_path = root / "scores.sqlite"
            dir_path = root / "model"
            file_path.write_text("scores", encoding="utf-8")
            dir_path.mkdir()
            (dir_path / "model.bin").write_bytes(b"model")

            self.assertTrue(remove_path_safely(file_path))
            self.assertTrue(remove_path_safely(dir_path))
            self.assertFalse(remove_path_safely(root / "missing"))
            self.assertFalse(file_path.exists())
            self.assertFalse(dir_path.exists())

    def test_clear_history_cache_returns_payload_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            cache_path.write_text("scores", encoding="utf-8")

            result = clear_history_cache(cache_path)

            self.assertTrue(result.deleted)
            self.assertEqual(result.to_payload(), {"kind": "history", "deleted": True, "path": str(cache_path)})
            self.assertFalse(cache_path.exists())

    def test_clear_model_caches_removes_app_and_repo_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_model_dir = root / "app_models"
            repo_root = root / "hf"
            repo_dir = "models--unit--model"
            repo_path = repo_root / repo_dir
            lock_path = repo_root / ".locks" / repo_dir
            app_model_dir.mkdir()
            repo_path.mkdir(parents=True)
            lock_path.mkdir(parents=True)

            result = clear_model_caches(app_model_dir, [repo_dir], repo_root)

            self.assertTrue(result.deleted)
            self.assertEqual(result.to_payload()["kind"], "model")
            self.assertEqual(result.to_payload()["paths"], [str(app_model_dir), str(repo_path), str(lock_path)])
            self.assertFalse(app_model_dir.exists())
            self.assertFalse(repo_path.exists())
            self.assertFalse(lock_path.exists())

    def test_clear_local_data_removes_records_caches_models_and_locks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_path = root / "scores.sqlite"
            upload_dir = root / "uploads"
            thumb_dir = root / "thumbnails"
            analysis_dir = root / "analysis"
            app_model_dir = root / "app_models"
            repo_root = root / "hf"
            repo_dir = "models--unit--model"
            repo_path = repo_root / repo_dir
            lock_path = repo_root / ".locks" / repo_dir
            for path in (upload_dir, thumb_dir, analysis_dir, app_model_dir, repo_path, lock_path):
                path.mkdir(parents=True)
                (path / "file.bin").write_bytes(b"data")
            cache_path.write_text("scores", encoding="utf-8")

            result = clear_local_data(
                cache_path=cache_path,
                upload_cache_dir=upload_dir,
                thumbnail_cache_dir=thumb_dir,
                analysis_image_cache_dir=analysis_dir,
                app_model_cache_dir=app_model_dir,
                model_repo_cache_dirs=[repo_dir],
                huggingface_cache_root=repo_root,
            )

            payload = result.to_payload()
            self.assertTrue(payload["deleted"])
            self.assertEqual(payload["kind"], "localData")
            for path in (cache_path, upload_dir, thumb_dir, analysis_dir, app_model_dir, repo_path, lock_path):
                self.assertFalse(path.exists())

    def test_clear_model_caches_rejects_path_escape_repo_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            with self.assertRaisesRegex(ValueError, "模型缓存路径异常"):
                clear_model_caches(root / "app_models", ["../outside"], root / "hf")

    def test_resolve_history_cache_path_defaults_to_current_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            current = Path(tmp) / "scores.sqlite"

            path, error = resolve_history_cache_path(
                "",
                current_cache_path=current,
                default_cache_path=Path(tmp) / "default.sqlite",
                allowed_suffixes={".sqlite", ".db"},
            )

        self.assertEqual(path, current)
        self.assertIsNone(error)

    def test_resolve_history_cache_path_allows_current_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            current = Path(tmp) / "scores.sqlite"

            path, error = resolve_history_cache_path(
                str(current),
                current_cache_path=current,
                default_cache_path=Path(tmp) / "default.sqlite",
                allowed_suffixes={".sqlite", ".db"},
            )

        self.assertEqual(path, current)
        self.assertIsNone(error)

    def test_resolve_history_cache_path_rejects_non_current_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            current = Path(tmp) / "scores.sqlite"
            other = Path(tmp) / "other.sqlite"

            path, error = resolve_history_cache_path(
                str(other),
                current_cache_path=current,
                default_cache_path=Path(tmp) / "default.sqlite",
                allowed_suffixes={".sqlite", ".db"},
            )

        self.assertIsNone(path)
        self.assertEqual(error, {"key": "error.historyCacheNotCurrent"})

    def test_resolve_history_cache_path_rejects_unsupported_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            current = Path(tmp) / "scores.sqlite"
            requested = Path(tmp) / "notes.txt"

            path, error = resolve_history_cache_path(
                str(requested),
                current_cache_path=current,
                default_cache_path=Path(tmp) / "default.sqlite",
                allowed_suffixes={".sqlite", ".db"},
            )

        self.assertIsNone(path)
        self.assertEqual(error, {"key": "error.historyCacheNotSqlite"})

    def test_resolve_history_cache_path_rejects_existing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            current = Path(tmp) / "scores.sqlite"
            current.mkdir()

            path, error = resolve_history_cache_path(
                str(current),
                current_cache_path=current,
                default_cache_path=Path(tmp) / "default.sqlite",
                allowed_suffixes={".sqlite", ".db"},
            )

        self.assertIsNone(path)
        self.assertEqual(error, {"key": "error.historyCacheNotFile"})


if __name__ == "__main__":
    unittest.main()
