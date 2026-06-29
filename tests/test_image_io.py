from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from culvia.image_io import (
    bounded_image_cache_size,
    ensure_resized_image_cache,
    image_file_data_url,
    open_image_rgb,
    resized_image_cache_path,
)


class ImageIOTests(unittest.TestCase):
    def test_bounded_image_cache_size_clamps_to_minimum_and_maximum(self) -> None:
        self.assertEqual(bounded_image_cache_size(None, minimum=80, maximum=900), 900)
        self.assertEqual(bounded_image_cache_size(20, minimum=80, maximum=900), 80)
        self.assertEqual(bounded_image_cache_size(1200, minimum=80, maximum=900), 900)
        self.assertEqual(bounded_image_cache_size(420, minimum=80, maximum=900), 420)

    def test_open_image_rgb_returns_transposed_rgb_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.png"
            Image.new("RGBA", (32, 24), (20, 40, 60, 128)).save(path)

            image = open_image_rgb(path)

        self.assertEqual(image.mode, "RGB")
        self.assertEqual(image.size, (32, 24))

    def test_resized_image_cache_is_stable_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.jpg"
            cache_dir = root / "cache"
            Image.new("RGB", (800, 500), (96, 128, 180)).save(source)

            expected_path = resized_image_cache_path(source, cache_dir, 300)
            cached = ensure_resized_image_cache(source, cache_dir, 300, maximum_size=300)
            cached_again = ensure_resized_image_cache(source, cache_dir, 300, maximum_size=300)

            self.assertEqual(cached, expected_path)
            self.assertEqual(cached_again, cached)
            self.assertTrue(cached.exists())
            with Image.open(cached) as image:
                self.assertLessEqual(max(image.size), 300)

    def test_image_file_data_url_encodes_file_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "image.jpg"
            path.write_bytes(b"abc")

            self.assertEqual(image_file_data_url(path), "data:image/jpeg;base64,YWJj")
            self.assertEqual(image_file_data_url(path, mime_type="image/webp"), "data:image/webp;base64,YWJj")


if __name__ == "__main__":
    unittest.main()
