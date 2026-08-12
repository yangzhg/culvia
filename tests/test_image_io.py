from __future__ import annotations

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

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

    def test_concurrent_cache_writers_publish_from_unique_temporary_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.jpg"
            source.write_bytes(b"source")
            cache_dir = root / "cache"
            barrier = threading.Barrier(2)
            temp_paths: list[Path] = []
            paths_lock = threading.Lock()

            class FakeImage:
                def thumbnail(self, _size: tuple[int, int]) -> None:
                    return None

                def save(self, path: Path, **_kwargs: object) -> None:
                    with paths_lock:
                        temp_paths.append(Path(path))
                    Path(path).write_bytes(b"jpeg")
                    barrier.wait(timeout=1)

            with (
                patch("culvia.image_io.open_image_rgb", side_effect=lambda *_args, **_kwargs: FakeImage()),
                ThreadPoolExecutor(max_workers=2) as executor,
            ):
                futures = [
                    executor.submit(ensure_resized_image_cache, source, cache_dir, 300, maximum_size=300)
                    for _ in range(2)
                ]
                results = [future.result(timeout=2) for future in futures]

            self.assertEqual(results[0], results[1])
            self.assertEqual(len(set(temp_paths)), 2)
            self.assertEqual(results[0].read_bytes(), b"jpeg")
            self.assertEqual(list(cache_dir.glob("*.tmp")), [])
            self.assertEqual(list(cache_dir.glob(".*.tmp")), [])

    def test_failed_cache_write_removes_its_temporary_file_and_can_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.jpg"
            Image.new("RGB", (80, 60), (96, 128, 180)).save(source)
            cache_dir = root / "cache"

            class FailingImage:
                def thumbnail(self, _size: tuple[int, int]) -> None:
                    return None

                def save(self, path: Path, **_kwargs: object) -> None:
                    Path(path).write_bytes(b"partial")
                    raise RuntimeError("encode failed")

            with patch("culvia.image_io.open_image_rgb", return_value=FailingImage()):
                with self.assertRaisesRegex(RuntimeError, "encode failed"):
                    ensure_resized_image_cache(source, cache_dir, 300, maximum_size=300)

            self.assertEqual(list(cache_dir.iterdir()), [])
            cached = ensure_resized_image_cache(source, cache_dir, 300, maximum_size=300)
            self.assertTrue(cached.exists())

    def test_concurrent_winner_is_used_when_atomic_replace_is_temporarily_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.jpg"
            Image.new("RGB", (80, 60), (96, 128, 180)).save(source)
            cache_dir = root / "cache"
            expected = resized_image_cache_path(source, cache_dir, 300)

            def blocked_replace(_source: Path, target: Path) -> None:
                Path(target).write_bytes(b"winner")
                raise PermissionError("target is in use")

            with patch("culvia.image_io.os.replace", side_effect=blocked_replace):
                cached = ensure_resized_image_cache(source, cache_dir, 300, maximum_size=300)

            self.assertEqual(cached, expected)
            self.assertEqual(cached.read_bytes(), b"winner")
            self.assertEqual(list(cache_dir.glob(".*.tmp")), [])

    def test_source_pixel_limit_is_checked_before_image_decode(self) -> None:
        class OversizedImage:
            size = (20_000, 10_000)

            def __enter__(self) -> OversizedImage:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def load(self) -> None:
                raise AssertionError("oversized image must not be decoded")

        with patch("culvia.image_io.Image.open", return_value=OversizedImage()):
            with self.assertRaisesRegex(RuntimeError, "image_too_large: 20000x10000"):
                open_image_rgb("oversized.jpg", max_decode_pixels=80_000_000)

    def test_jpeg_draft_reduces_decode_size_before_the_pixel_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.jpg"
            Image.new("RGB", (4000, 3000), (96, 128, 180)).save(path)

            decoded = open_image_rgb(path, max_size_hint=420, max_decode_pixels=1_000_000)

        self.assertLessEqual(decoded.width * decoded.height, 1_000_000)

    def test_formats_without_draft_are_rejected_before_large_decode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.png"
            Image.new("RGB", (1200, 1000), (96, 128, 180)).save(path)

            with self.assertRaisesRegex(RuntimeError, "image_too_large: 1200x1000"):
                open_image_rgb(path, max_size_hint=420, max_decode_pixels=1_000_000)

    def test_thumbnail_decode_resizes_before_returning_a_detached_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.png"
            Image.new("RGBA", (1600, 1200), (96, 128, 180, 255)).save(path)

            decoded = open_image_rgb(
                path,
                max_size_hint=420,
                max_decode_pixels=2_000_000,
                resize_before_copy=True,
            )

        self.assertEqual(decoded.mode, "RGB")
        self.assertLessEqual(max(decoded.size), 420)

    def test_legacy_pillow_resizes_16_bit_images_via_rgb_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.png"
            Image.new("I;16", (160, 120), 1024).save(path)
            original_thumbnail = Image.Image.thumbnail

            def legacy_thumbnail(image: Image.Image, *args: object, **kwargs: object) -> None:
                if image.mode.startswith("I;16"):
                    raise ValueError("image has wrong mode")
                original_thumbnail(image, *args, **kwargs)

            with patch.object(Image.Image, "thumbnail", legacy_thumbnail):
                decoded = open_image_rgb(
                    path,
                    max_size_hint=80,
                    max_decode_pixels=1_000_000,
                    resize_before_copy=True,
                )

        self.assertEqual(decoded.mode, "RGB")
        self.assertLessEqual(max(decoded.size), 80)

    def test_image_file_data_url_encodes_file_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "image.jpg"
            path.write_bytes(b"abc")

            self.assertEqual(image_file_data_url(path), "data:image/jpeg;base64,YWJj")
            self.assertEqual(image_file_data_url(path, mime_type="image/webp"), "data:image/webp;base64,YWJj")


if __name__ == "__main__":
    unittest.main()
