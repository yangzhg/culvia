from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd
from PIL import Image

from culvia.media_service import (
    image_url,
    is_inside_path,
    path_is_inside,
    resolve_media_path,
    safe_uploaded_relative_path,
    sanitize_uploaded_paths,
    save_uploaded_bytes,
    thumbnail_cache_path,
    thumbnail_url,
)


def make_image(path: Path) -> Path:
    image = Image.new("RGB", (32, 24), (120, 130, 140))
    image.save(path)
    return path


class MediaServiceTests(unittest.TestCase):
    def test_safe_uploaded_relative_path_strips_traversal_parts(self) -> None:
        self.assertEqual(safe_uploaded_relative_path("../nested/./photo.jpg"), Path("nested/photo.jpg"))
        self.assertEqual(safe_uploaded_relative_path(""), Path("uploaded_image"))

    def test_path_membership_uses_resolved_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "photos"
            root.mkdir()
            inside = root / "inside.jpg"
            outside = Path(tmp) / "outside.jpg"
            inside.write_bytes(b"inside")
            outside.write_bytes(b"outside")

            self.assertTrue(path_is_inside(str(inside), [str(root)]))
            self.assertFalse(path_is_inside(str(outside), [str(root)]))
            self.assertTrue(is_inside_path(inside, root))

    def test_resolve_media_path_allows_scored_files_and_rejects_unrelated_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "photos"
            root.mkdir()
            upload_root = Path(tmp) / "uploads"
            upload_root.mkdir()
            folder_image = make_image(root / "folder.jpg")
            scored_outside = make_image(Path(tmp) / "scored.jpg")
            denied = make_image(Path(tmp) / "denied.jpg")
            scores_df = pd.DataFrame([{"file_id": "scored", "path": str(scored_outside)}])

            by_folder, folder_status = resolve_media_path(
                file_id="",
                path_text=str(folder_image),
                source={"mode": "folders", "folders": [str(root)]},
                scores_df=scores_df,
                upload_cache_dir=upload_root,
            )
            by_file_id, file_id_status = resolve_media_path(
                file_id="scored",
                path_text="",
                source={"mode": "folders", "folders": [str(root)]},
                scores_df=scores_df,
                upload_cache_dir=upload_root,
            )
            denied_path, denied_status = resolve_media_path(
                file_id="",
                path_text=str(denied),
                source={"mode": "folders", "folders": [str(root)]},
                scores_df=pd.DataFrame(columns=["file_id", "path"]),
                upload_cache_dir=upload_root,
            )

        self.assertEqual(by_folder, folder_image.resolve())
        self.assertEqual(folder_status, 200)
        self.assertEqual(by_file_id, scored_outside.resolve())
        self.assertEqual(file_id_status, 200)
        self.assertIsNone(denied_path)
        self.assertEqual(denied_status, 403)

    def test_upload_mode_only_allows_files_inside_upload_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            upload_root = Path(tmp) / "uploads"
            upload_root.mkdir()
            inside = make_image(upload_root / "inside.jpg")
            outside = make_image(Path(tmp) / "outside.jpg")

            sanitized = sanitize_uploaded_paths([inside, outside, inside], upload_cache_dir=upload_root)
            resolved, status = resolve_media_path(
                file_id="",
                path_text=str(inside),
                source={"mode": "uploads", "uploadedPaths": [str(inside), str(outside)]},
                scores_df=pd.DataFrame(columns=["file_id", "path"]),
                upload_cache_dir=upload_root,
            )
            denied, denied_status = resolve_media_path(
                file_id="",
                path_text=str(outside),
                source={"mode": "uploads", "uploadedPaths": [str(outside)]},
                scores_df=pd.DataFrame(columns=["file_id", "path"]),
                upload_cache_dir=upload_root,
            )

        self.assertEqual(sanitized, [inside.resolve()])
        self.assertEqual(resolved, inside.resolve())
        self.assertEqual(status, 200)
        self.assertIsNone(denied)
        self.assertEqual(denied_status, 403)

    def test_save_uploaded_bytes_hashes_content_and_filters_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            upload_root = Path(tmp) / "uploads"
            saved = save_uploaded_bytes(
                filename="../Album/Photo.JPG",
                data=b"jpeg-ish",
                upload_cache_dir=upload_root,
                supported_extensions={".jpg", ".jpeg"},
            )
            ignored = save_uploaded_bytes(
                filename="notes.txt",
                data=b"text",
                upload_cache_dir=upload_root,
                supported_extensions={".jpg", ".jpeg"},
            )

            self.assertIsNotNone(saved)
            assert saved is not None
            self.assertTrue(saved.exists())
            self.assertTrue(is_inside_path(saved, upload_root))
            self.assertEqual(saved.name, "Photo.JPG")
            self.assertIsNone(ignored)

    def test_thumbnail_cache_path_is_stable_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = make_image(Path(tmp) / "source.jpg")
            cache_dir = Path(tmp) / "thumbs"

            first = thumbnail_cache_path(source, cache_dir, 1200)
            second = thumbnail_cache_path(source, cache_dir, 900)

        self.assertEqual(first, second)
        self.assertEqual(first.suffix, ".jpg")

    def test_media_urls_include_file_id_when_available(self) -> None:
        self.assertEqual(
            image_url("/photos/a.jpg", 1200, file_id="photo-1"),
            "/api/image?path=%2Fphotos%2Fa.jpg&max=1200&file_id=photo-1",
        )
        self.assertEqual(
            thumbnail_url("/photos/a.jpg", 420, file_id="photo-1"),
            "/api/thumbnail?path=%2Fphotos%2Fa.jpg&max=420&file_id=photo-1",
        )


if __name__ == "__main__":
    unittest.main()
