from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import culvia.media_catalog as media_catalog
from culvia.media_catalog import build_media_catalog, catalog_allows_path, resolve_catalog_media_path


class MediaCatalogTests(unittest.TestCase):
    def test_duplicate_file_ids_keep_first_path_and_known_empty_path_does_not_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.jpg"
            second = root / "second.jpg"
            fallback = root / "fallback.jpg"
            for path in (first, second, fallback):
                path.write_bytes(b"photo")
            catalog = build_media_catalog(
                pd.DataFrame(
                    [
                        {"file_id": "duplicate", "path": str(first)},
                        {"file_id": "duplicate", "path": str(second)},
                        {"file_id": "empty", "path": ""},
                    ]
                ),
                {"mode": "folders", "folders": [str(root)]},
                revision=1,
            )

            duplicate = resolve_catalog_media_path(
                catalog, file_id="duplicate", path_text="", upload_cache_dir=root / "uploads"
            )
            known_empty = resolve_catalog_media_path(
                catalog, file_id="empty", path_text=str(fallback), upload_cache_dir=root / "uploads"
            )
            unknown = resolve_catalog_media_path(
                catalog, file_id="unknown", path_text=str(fallback), upload_cache_dir=root / "uploads"
            )

            self.assertEqual(duplicate, (first.resolve(), 200))
            self.assertEqual(known_empty, (None, 404))
            self.assertEqual(unknown, (fallback.resolve(), 200))

    def test_bad_symlink_paths_are_isolated_from_valid_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good = root / "good.jpg"
            good.write_bytes(b"photo")
            loop = root / "loop"
            loop.symlink_to(loop)

            catalog = build_media_catalog(
                pd.DataFrame(
                    [
                        {"file_id": "bad", "path": str(loop)},
                        {"file_id": "good", "path": str(good)},
                    ]
                ),
                {"mode": "folders", "folders": [str(loop), str(root)]},
                revision=1,
            )

            good_path, good_status = resolve_catalog_media_path(
                catalog,
                file_id="good",
                path_text="",
                upload_cache_dir=root / "uploads",
            )
            bad_path, bad_status = resolve_catalog_media_path(
                catalog,
                file_id="bad",
                path_text="",
                upload_cache_dir=root / "uploads",
            )

            self.assertEqual((good_path, good_status), (good.resolve(), 200))
            self.assertEqual((bad_path, bad_status), (None, 404))

    def test_retargeted_folder_symlink_does_not_keep_old_target_authorized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            first_photo = first / "first.jpg"
            second_photo = second / "second.jpg"
            first_photo.write_bytes(b"first")
            second_photo.write_bytes(b"second")
            link = root / "current"
            link.symlink_to(first, target_is_directory=True)
            catalog = build_media_catalog([], {"mode": "folders", "folders": [str(link)]}, revision=1)

            link.unlink()
            link.symlink_to(second, target_is_directory=True)

            self.assertFalse(catalog_allows_path(catalog, first_photo, upload_cache_dir=root / "uploads"))
            self.assertTrue(catalog_allows_path(catalog, second_photo, upload_cache_dir=root / "uploads"))

    def test_retargeted_scored_symlink_does_not_keep_old_target_authorized_by_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.jpg"
            second = root / "second.jpg"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            link = root / "current.jpg"
            link.symlink_to(first)
            catalog = build_media_catalog(
                pd.DataFrame([{"file_id": "scored", "path": str(link)}]),
                {"mode": "folders", "folders": []},
                revision=1,
            )

            link.unlink()
            link.symlink_to(second)

            self.assertFalse(catalog_allows_path(catalog, first, upload_cache_dir=root / "uploads"))
            self.assertFalse(catalog_allows_path(catalog, second, upload_cache_dir=root / "uploads"))
            self.assertEqual(
                resolve_catalog_media_path(
                    catalog,
                    file_id="scored",
                    path_text="",
                    upload_cache_dir=root / "uploads",
                ),
                (second.resolve(), 200),
            )

    def test_uploaded_path_must_also_be_inside_the_runtime_upload_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            listed_outside = root / "listed.jpg"
            listed_outside.write_bytes(b"photo")
            upload_root = root / "uploads"
            upload_root.mkdir()
            catalog = build_media_catalog(
                [],
                {"mode": "uploads", "uploadedPaths": [str(listed_outside)]},
                revision=1,
            )

            self.assertFalse(catalog_allows_path(catalog, listed_outside, upload_cache_dir=upload_root))

    def test_duplicate_raw_paths_are_resolved_once_per_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photo = root / "photo.jpg"
            photo.write_bytes(b"photo")
            catalog = build_media_catalog(
                pd.DataFrame([{"file_id": str(index), "path": str(photo)} for index in range(100)]),
                {"mode": "folders", "folders": []},
                revision=1,
            )
            calls = 0
            real_key = media_catalog.path_identity_key

            def count_key(value: str | Path) -> str:
                nonlocal calls
                calls += 1
                return real_key(value)

            with patch.object(media_catalog, "path_identity_key", side_effect=count_key):
                allowed = catalog_allows_path(catalog, photo, upload_cache_dir=root / "uploads")

            self.assertTrue(allowed)
            self.assertEqual(calls, 2)


if __name__ == "__main__":
    unittest.main()
