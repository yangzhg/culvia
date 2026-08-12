from __future__ import annotations

import asyncio
import tempfile
import threading
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

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
    thumbnail_cache_size,
    thumbnail_url,
)
from culvia.thumbnail_service import ThumbnailGenerationCoordinator, ThumbnailQueueFullError


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

    def test_thumbnail_sizes_use_a_small_stable_bucket_set(self) -> None:
        self.assertEqual(thumbnail_cache_size(20), 80)
        self.assertEqual(thumbnail_cache_size(96), 80)
        self.assertEqual(thumbnail_cache_size(121), 120)
        self.assertEqual(thumbnail_cache_size(420), 420)
        self.assertEqual(thumbnail_cache_size(1200), 900)

    def test_media_urls_include_file_id_when_available(self) -> None:
        self.assertEqual(
            image_url("/photos/a.jpg", 1200, file_id="photo-1"),
            "/api/image?path=%2Fphotos%2Fa.jpg&max=1200&file_id=photo-1",
        )
        self.assertEqual(
            thumbnail_url("/photos/a.jpg", 420, file_id="photo-1"),
            "/api/thumbnail?path=%2Fphotos%2Fa.jpg&max=420&file_id=photo-1",
        )


class ThumbnailCoordinatorTests(unittest.TestCase):
    def test_different_thumbnails_run_in_parallel_with_a_hard_capacity(self) -> None:
        async def scenario(root: Path) -> tuple[int, list[Path]]:
            sources = [root / f"source-{index}.jpg" for index in range(4)]
            for source in sources:
                source.write_bytes(source.name.encode("utf-8"))
            cache_dir = root / "thumbs"
            coordinator = ThumbnailGenerationCoordinator(max_concurrency=2)
            active = 0
            max_active = 0
            active_lock = threading.Lock()
            two_started = threading.Event()
            release = threading.Event()

            def generate(
                _path: Path,
                _cache_dir: Path,
                _max_size: int,
                *,
                cache_path: Path | None = None,
            ) -> Path:
                nonlocal active, max_active
                assert cache_path is not None
                with active_lock:
                    active += 1
                    max_active = max(max_active, active)
                    if active == 2:
                        two_started.set()
                try:
                    if not release.wait(timeout=1):
                        raise AssertionError("thumbnail generation did not resume")
                    return cache_path
                finally:
                    with active_lock:
                        active -= 1

            with patch("culvia.thumbnail_service.ensure_thumbnail_file", side_effect=generate):
                tasks = [asyncio.create_task(coordinator.ensure(source, cache_dir, 420)) for source in sources]
                self.assertTrue(await asyncio.to_thread(two_started.wait, 1))
                await asyncio.sleep(0.05)
                with active_lock:
                    self.assertEqual(active, 2)
                    self.assertEqual(max_active, 2)
                release.set()
                results = await asyncio.gather(*tasks)
            coordinator.close()
            return max_active, results

        with tempfile.TemporaryDirectory() as tmp:
            max_active, results = asyncio.run(scenario(Path(tmp)))

        self.assertEqual(max_active, 2)
        self.assertEqual(len(results), 4)

    def test_same_thumbnail_is_generated_once_and_survives_one_waiter_cancelling(self) -> None:
        async def scenario(root: Path) -> int:
            source = root / "source.jpg"
            source.write_bytes(b"source")
            cache_dir = root / "thumbs"
            coordinator = ThumbnailGenerationCoordinator(max_concurrency=2)
            started = threading.Event()
            release = threading.Event()
            calls = 0

            def generate(
                _path: Path,
                _cache_dir: Path,
                _max_size: int,
                *,
                cache_path: Path | None = None,
            ) -> Path:
                nonlocal calls
                assert cache_path is not None
                calls += 1
                started.set()
                if not release.wait(timeout=1):
                    raise AssertionError("thumbnail generation did not resume")
                return cache_path

            with patch("culvia.thumbnail_service.ensure_thumbnail_file", side_effect=generate):
                first = asyncio.create_task(coordinator.ensure(source, cache_dir, 420))
                second = asyncio.create_task(coordinator.ensure(source, cache_dir, 420))
                self.assertTrue(await asyncio.to_thread(started.wait, 1))
                first.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await first
                release.set()
                await second
            coordinator.close()
            return calls

        with tempfile.TemporaryDirectory() as tmp:
            calls = asyncio.run(scenario(Path(tmp)))

        self.assertEqual(calls, 1)

    def test_failed_generation_is_removed_from_singleflight_and_can_retry(self) -> None:
        async def scenario(root: Path) -> int:
            source = root / "source.jpg"
            source.write_bytes(b"source")
            cache_dir = root / "thumbs"
            coordinator = ThumbnailGenerationCoordinator(max_concurrency=2)
            calls = 0

            def generate(
                _path: Path,
                _cache_dir: Path,
                _max_size: int,
                *,
                cache_path: Path | None = None,
            ) -> Path:
                nonlocal calls
                assert cache_path is not None
                calls += 1
                if calls == 1:
                    raise RuntimeError("encode failed")
                return cache_path

            with patch("culvia.thumbnail_service.ensure_thumbnail_file", side_effect=generate):
                with self.assertRaisesRegex(RuntimeError, "encode failed"):
                    await coordinator.ensure(source, cache_dir, 420)
                await coordinator.ensure(source, cache_dir, 420)
            coordinator.close()
            return calls

        with tempfile.TemporaryDirectory() as tmp:
            calls = asyncio.run(scenario(Path(tmp)))

        self.assertEqual(calls, 2)

    def test_immediately_completed_future_does_not_deadlock_singleflight_cleanup(self) -> None:
        async def scenario(root: Path) -> Path:
            source = root / "source.jpg"
            source.write_bytes(b"source")
            cache_dir = root / "thumbs"
            coordinator = ThumbnailGenerationCoordinator(max_concurrency=1)

            def submit_immediately(_function, *_args, **kwargs) -> Future[Path]:
                completed: Future[Path] = Future()
                completed.set_result(kwargs["cache_path"])
                return completed

            with patch.object(coordinator._executor, "submit", side_effect=submit_immediately):
                result = await asyncio.wait_for(coordinator.ensure(source, cache_dir, 420), timeout=1)
            coordinator.close()
            return result

        with tempfile.TemporaryDirectory() as tmp:
            result = asyncio.run(scenario(Path(tmp)))

        self.assertEqual(result.suffix, ".jpg")

    def test_singleflight_and_capacity_are_shared_across_event_loops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.jpg"
            source.write_bytes(b"source")
            cache_dir = root / "thumbs"
            coordinator = ThumbnailGenerationCoordinator(max_concurrency=1)
            first_started = threading.Event()
            both_targets_resolved = threading.Event()
            second_joined = threading.Event()
            release = threading.Event()
            calls = 0
            target_calls = 0
            wrap_calls = 0
            active = 0
            max_active = 0
            calls_lock = threading.Lock()

            def generate(
                _path: Path,
                _cache_dir: Path,
                _max_size: int,
                *,
                cache_path: Path | None = None,
            ) -> Path:
                nonlocal calls, active, max_active
                assert cache_path is not None
                with calls_lock:
                    calls += 1
                    active += 1
                    max_active = max(max_active, active)
                first_started.set()
                try:
                    if not release.wait(timeout=1):
                        raise AssertionError("thumbnail generation did not resume")
                    return cache_path
                finally:
                    with calls_lock:
                        active -= 1

            def wait_on_separate_loop() -> None:
                asyncio.run(coordinator.ensure(source, cache_dir, 420))

            original_wrap_future = asyncio.wrap_future

            def observe_join(future, *, loop=None):
                nonlocal wrap_calls
                with calls_lock:
                    wrap_calls += 1
                    if wrap_calls == 2:
                        second_joined.set()
                return original_wrap_future(future, loop=loop)

            def resolve_target(_path: Path, _cache_dir: Path, _max_size: int) -> tuple[Path, bool]:
                nonlocal target_calls
                with calls_lock:
                    target_calls += 1
                    if target_calls == 2:
                        both_targets_resolved.set()
                return cache_dir / "shared.jpg", False

            with (
                patch("culvia.thumbnail_service.ensure_thumbnail_file", side_effect=generate),
                patch("culvia.thumbnail_service._thumbnail_cache_target", side_effect=resolve_target),
                patch("culvia.thumbnail_service.asyncio.wrap_future", side_effect=observe_join),
            ):
                threads = [threading.Thread(target=wait_on_separate_loop) for _ in range(2)]
                for thread in threads:
                    thread.start()
                self.assertTrue(first_started.wait(timeout=1))
                self.assertTrue(both_targets_resolved.wait(timeout=1))
                self.assertTrue(second_joined.wait(timeout=1))
                release.set()
                for thread in threads:
                    thread.join(timeout=2)
                    self.assertFalse(thread.is_alive())
            coordinator.close()

        self.assertEqual(calls, 1)
        self.assertEqual(max_active, 1)

    def test_pending_capacity_rejects_new_keys_but_keeps_singleflight_and_recovers(self) -> None:
        async def scenario(root: Path) -> tuple[int, Path]:
            cache_dir = root / "thumbs"
            sources = [root / f"source-{index}.jpg" for index in range(3)]
            for source in sources:
                source.write_bytes(source.name.encode("utf-8"))
            coordinator = ThumbnailGenerationCoordinator(max_concurrency=1, max_pending=1)
            started = threading.Event()
            release = threading.Event()
            calls = 0

            def generate(
                _path: Path,
                _cache_dir: Path,
                _max_size: int,
                *,
                cache_path: Path | None = None,
            ) -> Path:
                nonlocal calls
                assert cache_path is not None
                calls += 1
                started.set()
                if not release.wait(timeout=1):
                    raise AssertionError("thumbnail generation did not resume")
                return cache_path

            with patch("culvia.thumbnail_service.ensure_thumbnail_file", side_effect=generate):
                first = asyncio.create_task(coordinator.ensure(sources[0], cache_dir, 420))
                same_key = asyncio.create_task(coordinator.ensure(sources[0], cache_dir, 420))
                self.assertTrue(await asyncio.to_thread(started.wait, 1))
                with self.assertRaises(ThumbnailQueueFullError):
                    await coordinator.ensure(sources[1], cache_dir, 420)
                release.set()
                first_result, same_result = await asyncio.gather(first, same_key)
                self.assertEqual(first_result, same_result)
                recovered = await coordinator.ensure(sources[2], cache_dir, 420)
            coordinator.close()
            return calls, recovered

        with tempfile.TemporaryDirectory() as tmp:
            calls, recovered = asyncio.run(scenario(Path(tmp)))

        self.assertEqual(calls, 2)
        self.assertEqual(recovered.suffix, ".jpg")


if __name__ == "__main__":
    unittest.main()
