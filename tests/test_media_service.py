from __future__ import annotations

import asyncio
import errno
import os
import tempfile
import threading
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from PIL import Image

import culvia.thumbnail_service as thumbnail_service
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
from culvia.thumbnail_cache import ThumbnailCachePolicy, ThumbnailCacheSweepResult, ThumbnailDeleteOutcome
from culvia.thumbnail_service import (
    ThumbnailGenerationCoordinator,
    ThumbnailCacheEntryInvalidError,
    ThumbnailQueueFullError,
    ThumbnailStorageFullError,
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
                publish_temp=None,
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
            source = make_image(root / "source.jpg")
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
                publish_temp=None,
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

    def test_creator_cancellation_during_generation_lookup_does_not_cancel_waiters(self) -> None:
        async def scenario(root: Path) -> tuple[int, bool]:
            source = make_image(root / "source.jpg")
            cache_dir = root / "thumbs"
            coordinator = ThumbnailGenerationCoordinator(max_concurrency=1)
            lookup_started = threading.Event()
            release_lookup = threading.Event()
            calls = 0
            real_lookup = thumbnail_service.thumbnail_cache_generation

            def blocked_lookup(path: Path):
                lookup_started.set()
                if not release_lookup.wait(timeout=1):
                    raise AssertionError("generation lookup did not resume")
                return real_lookup(path)

            def generate(
                _path: Path,
                _cache_dir: Path,
                _max_size: int,
                *,
                cache_path: Path | None = None,
                publish_temp=None,
            ) -> Path:
                nonlocal calls
                calls += 1
                assert cache_path is not None
                assert publish_temp is not None
                temp_path = cache_path.parent / f".{cache_path.name}.worker.tmp"
                temp_path.parent.mkdir(parents=True, exist_ok=True)
                temp_path.write_bytes(b"jpeg")
                publish_temp(temp_path, cache_path)
                return cache_path

            with (
                patch("culvia.thumbnail_service.thumbnail_cache_generation", side_effect=blocked_lookup),
                patch("culvia.thumbnail_service.ensure_thumbnail_file", side_effect=generate),
            ):
                first = asyncio.create_task(coordinator.ensure(source, cache_dir, 420))
                self.assertTrue(await asyncio.to_thread(lookup_started.wait, 1))
                second = asyncio.create_task(coordinator.ensure(source, cache_dir, 420))
                await asyncio.sleep(0)
                first.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await first
                release_lookup.set()
                result = await second
            coordinator.close()
            return calls, result.exists()

        with tempfile.TemporaryDirectory() as tmp:
            calls, exists = asyncio.run(scenario(Path(tmp)))

        self.assertEqual(calls, 1)
        self.assertTrue(exists)

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
                publish_temp=None,
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
                publish_temp=None,
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
        async def scenario(root: Path) -> tuple[int, bool]:
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
                publish_temp=None,
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

    def test_cache_sweep_runs_out_of_band_and_enforces_the_soft_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "thumbs"
            cache_dir.mkdir()
            for index in range(3):
                path = cache_dir / f"{index:040x}.jpg"
                path.write_bytes(b"jpeg")
                os.utime(path, (100 + index, 100 + index))
            coordinator = ThumbnailGenerationCoordinator(
                cache_policy=ThumbnailCachePolicy(
                    max_bytes=None,
                    max_files=2,
                    low_water_ratio=0.5,
                    min_age_seconds=0,
                )
            )

            coordinator.start(cache_dir)
            coordinator.close()

            self.assertEqual(len(list(cache_dir.glob("*.jpg"))), 1)
            self.assertIsNotNone(coordinator.last_sweep_result)
            assert coordinator.last_sweep_result is not None
            self.assertEqual(coordinator.last_sweep_result.deleted_files, 2)

    def test_active_content_read_is_protected_from_local_eviction(self) -> None:
        async def scenario(root: Path) -> tuple[ThumbnailDeleteOutcome, bytes, bool]:
            source = root / "source.jpg"
            source.write_bytes(b"source")
            cache_dir = root / "thumbs"
            cache_path = thumbnail_cache_path(source, cache_dir, 420)
            cache_path.parent.mkdir(parents=True)
            cache_path.write_bytes(b"jpeg")
            coordinator = ThumbnailGenerationCoordinator()
            started = threading.Event()
            release = threading.Event()

            def blocked_read(_path: Path, _touch_interval: float) -> bytes:
                started.set()
                if not release.wait(timeout=1):
                    raise AssertionError("thumbnail read did not resume")
                return b"jpeg"

            with patch("culvia.thumbnail_service._read_cache_file", side_effect=blocked_read):
                task = asyncio.create_task(coordinator.ensure_content(source, cache_dir, 420))
                self.assertTrue(await asyncio.to_thread(started.wait, 1))
                outcome = coordinator._delete_candidate(cache_path)
                release.set()
                _path, content = await task
            exists = cache_path.exists()
            coordinator.close()
            return outcome, content, exists

        with tempfile.TemporaryDirectory() as tmp:
            outcome, content, exists = asyncio.run(scenario(Path(tmp)))

        self.assertIs(outcome, ThumbnailDeleteOutcome.PROTECTED)
        self.assertEqual(content, b"jpeg")
        self.assertTrue(exists)

    def test_cache_clear_waits_for_active_read_and_blocks_new_requests(self) -> None:
        async def scenario(root: Path) -> tuple[bool, bytes, int, bool]:
            source = root / "source.jpg"
            source.write_bytes(b"source")
            cache_dir = root / "thumbs"
            cache_path = thumbnail_cache_path(source, cache_dir, 420)
            cache_path.parent.mkdir(parents=True)
            cache_path.write_bytes(b"jpeg")
            coordinator = ThumbnailGenerationCoordinator()
            started = threading.Event()
            release = threading.Event()

            def blocked_read(_path: Path, _touch_interval: float) -> bytes:
                started.set()
                if not release.wait(timeout=1):
                    raise AssertionError("thumbnail read did not resume")
                return b"jpeg"

            with patch("culvia.thumbnail_service._read_cache_file", side_effect=blocked_read):
                read_task = asyncio.create_task(coordinator.ensure_content(source, cache_dir, 420))
                self.assertTrue(await asyncio.to_thread(started.wait, 1))
                clear_task = asyncio.create_task(coordinator.clear_cache(cache_dir))
                await asyncio.sleep(0)
                with self.assertRaises(ThumbnailQueueFullError):
                    await coordinator.ensure(source, cache_dir, 420)
                clear_waited = not clear_task.done()
                release.set()
                _path, content = await read_task
                result = await clear_task
            exists = cache_path.exists()
            coordinator.close()
            return clear_waited, content, result.deleted_files, exists

        with tempfile.TemporaryDirectory() as tmp:
            clear_waited, content, deleted_files, exists = asyncio.run(scenario(Path(tmp)))

        self.assertTrue(clear_waited)
        self.assertEqual(content, b"jpeg")
        self.assertEqual(deleted_files, 1)
        self.assertFalse(exists)

    def test_content_read_recovers_when_another_process_evicts_before_open(self) -> None:
        async def scenario(root: Path) -> tuple[int, bytes]:
            source = make_image(root / "source.jpg")
            cache_dir = root / "thumbs"
            coordinator = ThumbnailGenerationCoordinator()
            from culvia.thumbnail_service import _read_cache_file as real_read_cache_file

            reads = 0

            def evict_once(path: Path, touch_interval: float) -> bytes:
                nonlocal reads
                reads += 1
                if reads == 1:
                    path.unlink()
                    raise FileNotFoundError(path)
                return real_read_cache_file(path, touch_interval)

            with patch("culvia.thumbnail_service._read_cache_file", side_effect=evict_once):
                _path, content = await coordinator.ensure_content(source, cache_dir, 420)
            coordinator.close()
            return reads, content

        with tempfile.TemporaryDirectory() as tmp:
            reads, content = asyncio.run(scenario(Path(tmp)))

        self.assertEqual(reads, 2)
        self.assertTrue(content.startswith(b"\xff\xd8"))

    def test_oversized_cache_entry_is_removed_and_regenerated_once(self) -> None:
        async def scenario(root: Path) -> tuple[bytes, bool]:
            source = make_image(root / "source.jpg")
            cache_dir = root / "thumbs"
            cache_path = thumbnail_cache_path(source, cache_dir, 420)
            cache_path.parent.mkdir(parents=True)
            cache_path.write_bytes(b"x" * 2_048)
            coordinator = ThumbnailGenerationCoordinator()
            with patch.object(thumbnail_service, "MAX_THUMBNAIL_CONTENT_BYTES", 1_024):
                _path, content = await coordinator.ensure_content(source, cache_dir, 420)
            coordinator.close()
            return content, cache_path.stat().st_size <= 1_024

        with tempfile.TemporaryDirectory() as tmp:
            content, bounded = asyncio.run(scenario(Path(tmp)))

        self.assertTrue(content.startswith(b"\xff\xd8"))
        self.assertTrue(bounded)

    def test_repeated_oversized_generation_fails_after_one_retry(self) -> None:
        async def scenario(root: Path) -> int:
            source = root / "source.jpg"
            source.write_bytes(b"source")
            cache_dir = root / "thumbs"
            coordinator = ThumbnailGenerationCoordinator()
            calls = 0

            def generate(
                _path: Path,
                _cache_dir: Path,
                _max_size: int,
                *,
                cache_path: Path | None = None,
                publish_temp=None,
            ) -> Path:
                nonlocal calls
                calls += 1
                assert cache_path is not None
                assert publish_temp is not None
                temp_path = cache_path.parent / f".{cache_path.name}.{calls}.tmp"
                temp_path.parent.mkdir(parents=True, exist_ok=True)
                temp_path.write_bytes(b"oversized")
                publish_temp(temp_path, cache_path)
                return cache_path

            with (
                patch("culvia.thumbnail_service.ensure_thumbnail_file", side_effect=generate),
                patch.object(thumbnail_service, "MAX_THUMBNAIL_CONTENT_BYTES", 4),
            ):
                with self.assertRaises(ThumbnailCacheEntryInvalidError):
                    await coordinator.ensure_content(source, cache_dir, 420)
            coordinator.close()
            return calls

        with tempfile.TemporaryDirectory() as tmp:
            calls = asyncio.run(scenario(Path(tmp)))

        self.assertEqual(calls, 2)

    def test_explicit_clear_keeps_fresh_cross_process_temp_files(self) -> None:
        async def scenario(root: Path) -> tuple[bool, bool]:
            cache_dir = root / "thumbs"
            cache_dir.mkdir()
            final_path = cache_dir / f"{1:040x}.jpg"
            temp_path = cache_dir / f".{2:040x}.jpg.worker.tmp"
            final_path.write_bytes(b"jpeg")
            temp_path.write_bytes(b"in-progress")
            coordinator = ThumbnailGenerationCoordinator()
            await coordinator.clear_cache(cache_dir)
            coordinator.close()
            return final_path.exists(), temp_path.exists()

        with tempfile.TemporaryDirectory() as tmp:
            final_exists, temp_exists = asyncio.run(scenario(Path(tmp)))

        self.assertFalse(final_exists)
        self.assertTrue(temp_exists)

    def test_cross_coordinator_clear_invalidates_an_in_progress_publication(self) -> None:
        async def scenario(root: Path) -> tuple[bool, bool]:
            source = root / "source.jpg"
            source.write_bytes(b"source")
            cache_dir = root / "thumbs"
            generator = ThumbnailGenerationCoordinator()
            clearer = ThumbnailGenerationCoordinator()
            ready_to_publish = threading.Event()
            release = threading.Event()

            def generate(
                _path: Path,
                _cache_dir: Path,
                _max_size: int,
                *,
                cache_path: Path | None = None,
                publish_temp=None,
            ) -> Path:
                assert cache_path is not None
                assert publish_temp is not None
                temp_path = cache_path.parent / f".{cache_path.name}.worker.tmp"
                temp_path.parent.mkdir(parents=True, exist_ok=True)
                temp_path.write_bytes(b"jpeg")
                ready_to_publish.set()
                if not release.wait(timeout=1):
                    raise AssertionError("thumbnail publication did not resume")
                try:
                    publish_temp(temp_path, cache_path)
                finally:
                    temp_path.unlink(missing_ok=True)
                return cache_path

            with patch("culvia.thumbnail_service.ensure_thumbnail_file", side_effect=generate):
                generation_task = asyncio.create_task(generator.ensure(source, cache_dir, 420))
                self.assertTrue(await asyncio.to_thread(ready_to_publish.wait, 1))
                await clearer.clear_cache(cache_dir)
                release.set()
                with self.assertRaises(ThumbnailQueueFullError):
                    await generation_task
            generator.close()
            clearer.close()
            return any(cache_dir.glob("*.jpg")), any(cache_dir.glob(".*.tmp"))

        with tempfile.TemporaryDirectory() as tmp:
            has_final, has_temp = asyncio.run(scenario(Path(tmp)))

        self.assertFalse(has_final)
        self.assertFalse(has_temp)

    def test_cross_coordinator_cache_hit_is_rejected_while_clear_is_active(self) -> None:
        async def scenario(root: Path) -> bool:
            source = root / "source.jpg"
            source.write_bytes(b"source")
            cache_dir = root / "thumbs"
            cache_path = thumbnail_cache_path(source, cache_dir, 420)
            cache_path.parent.mkdir(parents=True)
            cache_path.write_bytes(b"jpeg")
            generator = ThumbnailGenerationCoordinator()
            clearer = ThumbnailGenerationCoordinator()
            started = threading.Event()
            release = threading.Event()
            original_delete = clearer._delete_candidate

            def blocked_delete(path: Path) -> ThumbnailDeleteOutcome:
                started.set()
                if not release.wait(timeout=1):
                    raise AssertionError("cache clear did not resume")
                return original_delete(path)

            with patch.object(clearer, "_delete_candidate", side_effect=blocked_delete):
                clear_task = asyncio.create_task(clearer.clear_cache(cache_dir))
                self.assertTrue(await asyncio.to_thread(started.wait, 1))
                with self.assertRaises(ThumbnailQueueFullError):
                    await generator.ensure_content(source, cache_dir, 420)
                rejected = True
                release.set()
                await clear_task
            generator.close()
            clearer.close()
            return rejected

        with tempfile.TemporaryDirectory() as tmp:
            rejected = asyncio.run(scenario(Path(tmp)))

        self.assertTrue(rejected)

    def test_explicit_clear_rejects_incomplete_scans(self) -> None:
        async def scenario(root: Path) -> None:
            coordinator = ThumbnailGenerationCoordinator()
            incomplete = ThumbnailCacheSweepResult(
                completed=True,
                lock_acquired=True,
                scan_errors=1,
            )
            with patch("culvia.thumbnail_service.sweep_thumbnail_cache", return_value=incomplete):
                with self.assertRaises(OSError):
                    await coordinator.clear_cache(root / "thumbs")
            coordinator.close()

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(scenario(Path(tmp)))

    def test_cross_coordinator_requests_are_rejected_for_the_entire_clear_context(self) -> None:
        async def scenario(root: Path) -> bool:
            cache_dir = root / "thumbs"
            cache_dir.mkdir()
            clearer = ThumbnailGenerationCoordinator()
            requester = ThumbnailGenerationCoordinator()
            source = make_image(root / "source.jpg")

            async with clearer.clearing_cache(cache_dir):
                with self.assertRaises(ThumbnailQueueFullError):
                    await requester.ensure(source, cache_dir, 420)
                rejected = True

            requester.close()
            clearer.close()
            return rejected

        with tempfile.TemporaryDirectory() as tmp:
            rejected = asyncio.run(scenario(Path(tmp)))

        self.assertTrue(rejected)

    def test_cancelling_clear_during_fence_setup_releases_the_fence(self) -> None:
        async def scenario(root: Path) -> bool:
            cache_dir = root / "thumbs"
            cache_dir.mkdir()
            coordinator = ThumbnailGenerationCoordinator()
            begin_started = threading.Event()
            release_begin = threading.Event()
            real_begin = thumbnail_service.begin_thumbnail_cache_clear

            def blocked_begin(path: Path) -> str:
                begin_started.set()
                if not release_begin.wait(timeout=1):
                    raise AssertionError("clear fence setup did not resume")
                return real_begin(path)

            with patch("culvia.thumbnail_service.begin_thumbnail_cache_clear", side_effect=blocked_begin):
                clear_task = asyncio.create_task(coordinator.clear_cache(cache_dir))
                self.assertTrue(await asyncio.to_thread(begin_started.wait, 1))
                clear_task.cancel()
                release_begin.set()
                with self.assertRaises(asyncio.CancelledError):
                    await clear_task
            generation = thumbnail_service.thumbnail_cache_generation(cache_dir)
            coordinator.close()
            return generation.clearing

        with tempfile.TemporaryDirectory() as tmp:
            clearing = asyncio.run(scenario(Path(tmp)))

        self.assertFalse(clearing)

    def test_cancelling_clear_waits_for_the_running_sweep_before_releasing_the_fence(self) -> None:
        async def scenario(root: Path) -> tuple[bool, bool]:
            cache_dir = root / "thumbs"
            cache_dir.mkdir()
            coordinator = ThumbnailGenerationCoordinator()
            requester = ThumbnailGenerationCoordinator()
            source = make_image(root / "source.jpg")
            sweep_started = threading.Event()
            release_sweep = threading.Event()

            def blocked_sweep(*_args, **_kwargs) -> ThumbnailCacheSweepResult:
                sweep_started.set()
                if not release_sweep.wait(timeout=2):
                    raise AssertionError("cache sweep did not resume")
                return ThumbnailCacheSweepResult(completed=True, lock_acquired=True)

            with patch("culvia.thumbnail_service.sweep_thumbnail_cache", side_effect=blocked_sweep):
                clear_task = asyncio.create_task(coordinator.clear_cache(cache_dir))
                self.assertTrue(await asyncio.to_thread(sweep_started.wait, 1))
                clear_task.cancel()
                clear_task.cancel()
                await asyncio.sleep(0)
                still_cleaning = not clear_task.done()
                with self.assertRaises(ThumbnailQueueFullError):
                    await requester.ensure(source, cache_dir, 420)
                release_sweep.set()
                with self.assertRaises(asyncio.CancelledError):
                    await clear_task

            generation = thumbnail_service.thumbnail_cache_generation(cache_dir)
            requester.close()
            coordinator.close()
            return still_cleaning, generation.clearing

        with tempfile.TemporaryDirectory() as tmp:
            still_cleaning, clearing = asyncio.run(scenario(Path(tmp)))

        self.assertTrue(still_cleaning)
        self.assertFalse(clearing)

    def test_two_coordinators_cannot_enter_clear_context_together(self) -> None:
        async def scenario(root: Path) -> tuple[bool, bool]:
            cache_dir = root / "thumbs"
            cache_dir.mkdir()
            first = ThumbnailGenerationCoordinator()
            second = ThumbnailGenerationCoordinator()
            requester = ThumbnailGenerationCoordinator()
            source = make_image(root / "source.jpg")

            async with first.clearing_cache(cache_dir):
                with self.assertRaises(ThumbnailQueueFullError):
                    await second.clear_cache(cache_dir)
                with self.assertRaises(ThumbnailQueueFullError):
                    await requester.ensure(source, cache_dir, 420)
                clear_rejected = True
                request_rejected = True

            requester.close()
            second.close()
            first.close()
            return clear_rejected, request_rejected

        with tempfile.TemporaryDirectory() as tmp:
            clear_rejected, request_rejected = asyncio.run(scenario(Path(tmp)))

        self.assertTrue(clear_rejected)
        self.assertTrue(request_rejected)

    def test_disk_full_runs_one_emergency_sweep_and_retries_generation(self) -> None:
        async def scenario(root: Path) -> tuple[int, Path]:
            source = root / "source.jpg"
            source.write_bytes(b"source")
            cache_dir = root / "thumbs"
            coordinator = ThumbnailGenerationCoordinator()
            calls = 0

            def generate(
                _path: Path,
                _cache_dir: Path,
                _max_size: int,
                *,
                cache_path: Path | None = None,
                publish_temp=None,
            ) -> Path:
                nonlocal calls
                calls += 1
                assert cache_path is not None
                if calls == 1:
                    raise OSError(errno.ENOSPC, "disk full")
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_bytes(b"jpeg")
                return cache_path

            with patch("culvia.thumbnail_service.ensure_thumbnail_file", side_effect=generate):
                result = await coordinator.ensure(source, cache_dir, 420)
            coordinator.close()
            return calls, result.exists()

        with tempfile.TemporaryDirectory() as tmp:
            calls, result_exists = asyncio.run(scenario(Path(tmp)))

        self.assertEqual(calls, 2)
        self.assertTrue(result_exists)

    def test_repeated_disk_full_becomes_a_stable_storage_error(self) -> None:
        async def scenario(root: Path) -> int:
            source = root / "source.jpg"
            source.write_bytes(b"source")
            cache_dir = root / "thumbs"
            coordinator = ThumbnailGenerationCoordinator()
            calls = 0

            def fail(*_args, **_kwargs) -> Path:
                nonlocal calls
                calls += 1
                raise OSError(errno.ENOSPC, "disk full")

            with patch("culvia.thumbnail_service.ensure_thumbnail_file", side_effect=fail):
                with self.assertRaises(ThumbnailStorageFullError):
                    await coordinator.ensure(source, cache_dir, 420)
            coordinator.close()
            return calls

        with tempfile.TemporaryDirectory() as tmp:
            calls = asyncio.run(scenario(Path(tmp)))

        self.assertEqual(calls, 2)

    def test_immediately_completed_emergency_sweep_does_not_deadlock(self) -> None:
        async def scenario(root: Path) -> None:
            coordinator = ThumbnailGenerationCoordinator()
            completed: Future[ThumbnailCacheSweepResult] = Future()
            completed.set_result(ThumbnailCacheSweepResult(completed=True, lock_acquired=True))

            with patch.object(coordinator._janitor, "submit", return_value=completed):
                await asyncio.wait_for(coordinator._emergency_sweep(root / "thumbs"), timeout=1)
            coordinator.close()

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(scenario(Path(tmp)))

    def test_concurrent_emergency_waiters_share_one_sweep(self) -> None:
        async def scenario(root: Path) -> int:
            coordinator = ThumbnailGenerationCoordinator()
            release = threading.Event()
            started = threading.Event()
            submissions = 0

            def sweep(*_args, **_kwargs) -> ThumbnailCacheSweepResult:
                nonlocal submissions
                submissions += 1
                started.set()
                self.assertTrue(release.wait(timeout=1))
                return ThumbnailCacheSweepResult(completed=True, lock_acquired=True)

            with patch("culvia.thumbnail_service.sweep_thumbnail_cache", side_effect=sweep):
                first = asyncio.create_task(coordinator._emergency_sweep(root / "thumbs"))
                self.assertTrue(await asyncio.to_thread(started.wait, 1))
                second = asyncio.create_task(coordinator._emergency_sweep(root / "thumbs"))
                await asyncio.sleep(0)
                release.set()
                await asyncio.gather(first, second)
            coordinator.close()
            return submissions

        with tempfile.TemporaryDirectory() as tmp:
            submissions = asyncio.run(scenario(Path(tmp)))

        self.assertEqual(submissions, 1)


if __name__ == "__main__":
    unittest.main()
