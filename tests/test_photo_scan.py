from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from culvia.photo_scan import SUPPORTED_EXTENSIONS, build_file_id, scan_image_paths


class PhotoScanTests(unittest.TestCase):
    def test_supported_extensions_include_common_photo_formats(self) -> None:
        self.assertIn(".jpg", SUPPORTED_EXTENSIONS)
        self.assertIn(".heic", SUPPORTED_EXTENSIONS)
        self.assertIn(".tiff", SUPPORTED_EXTENSIONS)

    def test_scan_image_paths_recurses_and_sorts_unique_supported_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "nested"
            nested.mkdir()
            first = root / "b.JPG"
            second = nested / "a.png"
            ignored = root / "notes.txt"
            first.write_bytes(b"jpg")
            second.write_bytes(b"png")
            ignored.write_text("not an image", encoding="utf-8")

            paths, warnings = scan_image_paths([root, first])

        expected = sorted({first.resolve(), second.resolve()}, key=lambda item: str(item).casefold())
        self.assertEqual(paths, expected)
        self.assertEqual(warnings, [])

    def test_scan_image_paths_deduplicates_nested_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "nested"
            nested.mkdir()
            image = nested / "photo.jpg"
            image.write_bytes(b"jpg")

            paths, warnings = scan_image_paths([root, nested, image])

        self.assertEqual(paths, [image.resolve()])
        self.assertEqual(warnings, [])

    def test_scan_image_paths_reports_missing_and_unsupported_single_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            unsupported = Path(tmp) / "notes.txt"
            unsupported.write_text("not an image", encoding="utf-8")
            missing = Path(tmp) / "missing.jpg"

            paths, warnings = scan_image_paths([unsupported, missing])

        self.assertEqual(paths, [])
        self.assertEqual(len(warnings), 2)
        self.assertIn("不是支持的图片格式", warnings[0])
        self.assertIn("目录不存在", warnings[1])

    def test_build_file_id_includes_path_size_and_mtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "image.jpg"
            path.write_bytes(b"abc")

            file_id = build_file_id(path)

        self.assertIn(str(path), file_id)
        self.assertIn("|3|", file_id)


if __name__ == "__main__":
    unittest.main()
