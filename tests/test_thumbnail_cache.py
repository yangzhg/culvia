from __future__ import annotations

import errno
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import culvia.thumbnail_cache as thumbnail_cache
from culvia.thumbnail_cache import (
    SWEEP_LOCK_FILENAME,
    ThumbnailCachePolicy,
    ThumbnailDeleteOutcome,
    publish_thumbnail_cache_entry,
    sweep_thumbnail_cache,
    thumbnail_cache_generation,
)


NOW = 2_000_000.0
HASH_NAMES = [f"{index:040x}.jpg" for index in range(20)]


def write_cache_file(
    root: Path,
    name: str,
    size: int,
    *,
    age: float,
    access_age: float | None = None,
) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    modified = NOW - age
    accessed = NOW - (age if access_age is None else access_age)
    os.utime(path, (accessed, modified))
    return path


class ThumbnailCachePolicyTests(unittest.TestCase):
    def test_defaults_match_runtime_policy(self) -> None:
        policy = ThumbnailCachePolicy()

        self.assertEqual(policy.max_bytes, 2 * 1024**3)
        self.assertEqual(policy.max_files, 20_000)
        self.assertEqual(policy.low_water_ratio, 0.8)
        self.assertEqual(policy.min_age_seconds, 3_600)
        self.assertEqual(policy.stale_temp_age_seconds, 86_400)


class ThumbnailCacheSweepTests(unittest.TestCase):
    def test_below_high_water_does_not_delete_final_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = write_cache_file(root, HASH_NAMES[0], 10, age=10_000)

            result = sweep_thumbnail_cache(
                root,
                policy=ThumbnailCachePolicy(max_bytes=20, max_files=2, min_age_seconds=0),
                now=NOW,
            )

            self.assertTrue(result.completed)
            self.assertFalse(result.high_water_exceeded)
            self.assertEqual(result.deleted_files, 0)
            self.assertEqual(result.remaining_files, 1)
            self.assertTrue(image.exists())

    def test_nested_directories_are_outside_the_flat_cache_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = write_cache_file(root, f"nested/{HASH_NAMES[0]}", 10, age=10_000)

            result = sweep_thumbnail_cache(
                root,
                policy=ThumbnailCachePolicy(max_bytes=0, max_files=0, min_age_seconds=0),
                now=NOW,
            )

            self.assertEqual(result.scanned_files, 0)
            self.assertTrue(nested.exists())

    def test_deletes_oldest_until_every_low_water_target_is_met(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            oldest = write_cache_file(root, HASH_NAMES[0], 10, age=500)
            second = write_cache_file(root, HASH_NAMES[1], 10, age=400)
            third = write_cache_file(root, HASH_NAMES[2], 10, age=300)
            newest = write_cache_file(root, HASH_NAMES[3], 10, age=200)

            result = sweep_thumbnail_cache(
                root,
                policy=ThumbnailCachePolicy(
                    max_bytes=35,
                    max_files=3,
                    low_water_ratio=0.5,
                    min_age_seconds=0,
                ),
                now=NOW,
            )

            self.assertTrue(result.high_water_exceeded)
            self.assertEqual(result.low_water_bytes, 17)
            self.assertEqual(result.low_water_files, 1)
            self.assertEqual(result.deleted_files, 3)
            self.assertEqual(result.deleted_bytes, 30)
            self.assertTrue(result.low_water_reached)
            self.assertFalse(result.soft_limit_exceeded)
            self.assertFalse(oldest.exists())
            self.assertFalse(second.exists())
            self.assertFalse(third.exists())
            self.assertTrue(newest.exists())

    def test_lru_order_uses_access_time_without_changing_etag_mtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recently_used = write_cache_file(root, HASH_NAMES[0], 10, age=500, access_age=10)
            least_recently_used = write_cache_file(root, HASH_NAMES[1], 10, age=100, access_age=500)
            recent_mtime = recently_used.stat().st_mtime_ns

            result = sweep_thumbnail_cache(
                root,
                policy=ThumbnailCachePolicy(max_bytes=None, max_files=1, low_water_ratio=1, min_age_seconds=0),
                now=NOW,
            )

            self.assertEqual(result.deleted_files, 1)
            self.assertTrue(recently_used.exists())
            self.assertFalse(least_recently_used.exists())
            self.assertEqual(recently_used.stat().st_mtime_ns, recent_mtime)

    def test_minimum_age_can_leave_a_soft_overage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            young = [write_cache_file(root, HASH_NAMES[index], 10, age=30) for index in range(3)]

            result = sweep_thumbnail_cache(
                root,
                policy=ThumbnailCachePolicy(
                    max_bytes=None,
                    max_files=2,
                    low_water_ratio=0.5,
                    min_age_seconds=60,
                ),
                now=NOW,
            )

            self.assertEqual(result.eligible_files, 0)
            self.assertEqual(result.deleted_files, 0)
            self.assertFalse(result.low_water_reached)
            self.assertTrue(result.soft_limit_exceeded)
            self.assertTrue(all(path.exists() for path in young))

    def test_protected_and_failed_candidates_do_not_abort_the_sweep(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            protected = write_cache_file(root, HASH_NAMES[0], 10, age=500)
            failed = write_cache_file(root, HASH_NAMES[1], 10, age=400)
            raced = write_cache_file(root, HASH_NAMES[2], 10, age=350)
            deletable = write_cache_file(root, HASH_NAMES[3], 10, age=300)
            newest = write_cache_file(root, HASH_NAMES[4], 10, age=200)

            def delete_candidate(path: Path) -> ThumbnailDeleteOutcome | bool:
                if path == protected:
                    return ThumbnailDeleteOutcome.PROTECTED
                if path == failed:
                    raise PermissionError("in use")
                if path == raced:
                    path.unlink()
                    raise FileNotFoundError(path)
                path.unlink()
                return True

            result = sweep_thumbnail_cache(
                root,
                policy=ThumbnailCachePolicy(max_bytes=None, max_files=4, low_water_ratio=0.4, min_age_seconds=0),
                delete_candidate=delete_candidate,
                now=NOW,
            )

            self.assertEqual(result.protected_files, 1)
            self.assertEqual(result.failed_deletions, 1)
            self.assertEqual(result.missing_files, 1)
            self.assertEqual(result.deleted_files, 2)
            self.assertTrue(result.soft_limit_exceeded)
            self.assertTrue(protected.exists())
            self.assertTrue(failed.exists())
            self.assertFalse(raced.exists())
            self.assertFalse(deletable.exists())
            self.assertFalse(newest.exists())

    def test_old_hidden_temp_files_are_cleaned_but_fresh_ones_are_kept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stale = write_cache_file(root, f".{HASH_NAMES[0]}.old.tmp", 5, age=200)
            fresh = write_cache_file(root, f".{HASH_NAMES[1]}.fresh.tmp", 5, age=20)
            visible = write_cache_file(root, "visible.tmp", 5, age=200)

            result = sweep_thumbnail_cache(
                root,
                policy=ThumbnailCachePolicy(stale_temp_age_seconds=100),
                now=NOW,
            )

            self.assertEqual(result.stale_temp_files, 1)
            self.assertEqual(result.deleted_temp_files, 1)
            self.assertFalse(stale.exists())
            self.assertTrue(fresh.exists())
            self.assertTrue(visible.exists())

    def test_temp_deletion_failures_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stale = write_cache_file(root, f".{HASH_NAMES[0]}.old.tmp", 5, age=200)
            original_unlink = Path.unlink

            def fail_stale(path: Path, *args, **kwargs):
                if path == stale:
                    raise PermissionError("in use")
                return original_unlink(path, *args, **kwargs)

            with patch.object(Path, "unlink", autospec=True, side_effect=fail_stale):
                result = sweep_thumbnail_cache(
                    root,
                    policy=ThumbnailCachePolicy(stale_temp_age_seconds=100),
                    now=NOW,
                )

            self.assertEqual(result.failed_temp_deletions, 1)
            self.assertTrue(stale.exists())

    def test_persistent_advisory_lock_file_is_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stale_temp = write_cache_file(root, f".{HASH_NAMES[0]}.work.tmp", 5, age=500)
            lock_path = root / SWEEP_LOCK_FILENAME
            lock_path.write_bytes(b"0")
            policy = ThumbnailCachePolicy(stale_temp_age_seconds=100)

            result = sweep_thumbnail_cache(root, policy=policy, now=NOW)

            self.assertTrue(result.completed)
            self.assertTrue(lock_path.exists())
            self.assertFalse(stale_temp.exists())

    def test_live_sweep_lock_is_not_reclaimed_when_the_sweep_runs_long(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_cache_file(root, HASH_NAMES[0], 10, age=500)
            started = threading.Event()
            release = threading.Event()
            results = []

            def blocked_delete(path: Path) -> ThumbnailDeleteOutcome:
                started.set()
                self.assertTrue(release.wait(timeout=1))
                path.unlink()
                return ThumbnailDeleteOutcome.DELETED

            def sweep_first() -> None:
                results.append(
                    sweep_thumbnail_cache(
                        root,
                        policy=ThumbnailCachePolicy(
                            max_bytes=0,
                            max_files=0,
                            min_age_seconds=0,
                        ),
                        delete_candidate=blocked_delete,
                        now=NOW,
                    )
                )

            thread = threading.Thread(target=sweep_first)
            thread.start()
            self.assertTrue(started.wait(timeout=1))
            skipped = sweep_thumbnail_cache(
                root,
                policy=ThumbnailCachePolicy(max_bytes=0, max_files=0, min_age_seconds=0),
                now=NOW,
            )
            release.set()
            thread.join(timeout=2)

            self.assertFalse(thread.is_alive())
            self.assertTrue(skipped.skipped_due_to_lock)
            self.assertFalse(skipped.lock_acquired)
            self.assertTrue(results[0].completed)

    def test_clear_generation_invalidates_a_publication_that_started_before_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_path = root / HASH_NAMES[0]
            first_temp = root / f".{HASH_NAMES[0]}.first.tmp"
            first_temp.write_bytes(b"first")
            before = thumbnail_cache_generation(root)

            result = sweep_thumbnail_cache(
                root,
                policy=ThumbnailCachePolicy(max_bytes=0, max_files=0, min_age_seconds=0),
                reset_generation=True,
                now=NOW,
            )

            self.assertTrue(result.completed)
            with self.assertRaisesRegex(RuntimeError, "cleared"):
                publish_thumbnail_cache_entry(
                    first_temp,
                    cache_path,
                    expected_generation=before.token,
                )
            self.assertFalse(cache_path.exists())

            second_temp = root / f".{HASH_NAMES[0]}.second.tmp"
            second_temp.write_bytes(b"second")
            after = thumbnail_cache_generation(root)
            self.assertNotEqual(after.token, before.token)
            publish_thumbnail_cache_entry(second_temp, cache_path, expected_generation=after.token)
            self.assertEqual(cache_path.read_bytes(), b"second")

    def test_clear_persists_the_new_generation_before_and_after_reclaiming_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cached = write_cache_file(root, HASH_NAMES[0], 10, age=500)
            real_write = thumbnail_cache._write_generation_state
            write_observations = []

            def observe_write(
                descriptor: int,
                *,
                token: str,
                clearing: bool,
            ) -> None:
                write_observations.append(cached.exists())
                real_write(descriptor, token=token, clearing=clearing)

            with patch.object(thumbnail_cache, "_write_generation_state", side_effect=observe_write):
                result = sweep_thumbnail_cache(
                    root,
                    policy=ThumbnailCachePolicy(max_bytes=0, max_files=0, min_age_seconds=0),
                    reset_generation=True,
                    now=NOW,
                )

            self.assertTrue(result.completed)
            self.assertEqual(write_observations, [True, False])

    def test_sweep_lock_preallocates_generation_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = sweep_thumbnail_cache(root)

            self.assertTrue(result.completed)
            self.assertEqual((root / SWEEP_LOCK_FILENAME).stat().st_size, 65)

    def test_partial_generation_state_files_are_extended_to_the_exact_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / SWEEP_LOCK_FILENAME
            for initial_size in range(1, 65):
                path.write_bytes(b"x" * initial_size)
                descriptor = os.open(path, os.O_RDWR)
                try:
                    thumbnail_cache._initialize_generation_slot(descriptor)
                finally:
                    os.close(descriptor)
                self.assertEqual(path.stat().st_size, 65)

    def test_generation_state_reader_accepts_short_reads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / SWEEP_LOCK_FILENAME
            descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                thumbnail_cache._write_generation_state(descriptor, token="generation", clearing=False)
                real_read = os.read

                def short_read(fd: int, size: int) -> bytes:
                    return real_read(fd, min(size, 3))

                with patch.object(thumbnail_cache.os, "read", side_effect=short_read):
                    generation = thumbnail_cache._read_generation_state(descriptor)
            finally:
                os.close(descriptor)

            self.assertEqual(generation.token, "generation")

    def test_generation_state_writer_retries_short_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / SWEEP_LOCK_FILENAME
            descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            real_write = os.write

            def short_write(fd: int, data) -> int:
                return real_write(fd, bytes(data[:2]))

            try:
                with patch.object(thumbnail_cache.os, "write", side_effect=short_write):
                    thumbnail_cache._write_generation_state(descriptor, token="generation", clearing=False)
                generation = thumbnail_cache._read_generation_state(descriptor)
            finally:
                os.close(descriptor)

            self.assertEqual(generation.token, "generation")

    def test_generation_state_reports_an_active_exclusive_sweep(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_cache_file(root, HASH_NAMES[0], 10, age=500)
            started = threading.Event()
            release = threading.Event()

            def blocked_delete(path: Path) -> ThumbnailDeleteOutcome:
                started.set()
                self.assertTrue(release.wait(timeout=1))
                path.unlink()
                return ThumbnailDeleteOutcome.DELETED

            thread = threading.Thread(
                target=sweep_thumbnail_cache,
                args=(root,),
                kwargs={
                    "policy": ThumbnailCachePolicy(max_bytes=0, max_files=0, min_age_seconds=0),
                    "delete_candidate": blocked_delete,
                    "reset_generation": True,
                    "now": NOW,
                },
            )
            thread.start()
            self.assertTrue(started.wait(timeout=1))
            generation = thumbnail_cache_generation(root)
            release.set()
            thread.join(timeout=2)

            self.assertFalse(thread.is_alive())
            self.assertTrue(generation.clearing)

    def test_generation_state_recovers_an_abandoned_clear_lease(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lock = thumbnail_cache._acquire_sweep_lock(root / SWEEP_LOCK_FILENAME, timeout_seconds=0)
            assert lock.descriptor is not None
            try:
                thumbnail_cache._write_generation_state(
                    lock.descriptor,
                    token="abandoned-generation",
                    clearing=True,
                )
            finally:
                thumbnail_cache._release_sweep_lock(lock.descriptor)

            recovered = thumbnail_cache_generation(root)

            self.assertFalse(recovered.clearing)
            self.assertEqual(recovered.token, "abandoned-generation")

    def test_abandoned_clear_lock_recovers_without_accepting_the_old_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_path = root / HASH_NAMES[0]
            temp_path = root / f".{HASH_NAMES[0]}.abandoned.tmp"
            temp_path.write_bytes(b"stale")
            before = thumbnail_cache_generation(root)
            lease = thumbnail_cache.begin_thumbnail_cache_clear(root)

            thumbnail_cache._release_clear_lease(lease)
            recovered = thumbnail_cache_generation(root)

            self.assertFalse(recovered.clearing)
            self.assertNotEqual(recovered.token, before.token)
            with self.assertRaisesRegex(RuntimeError, "cleared"):
                publish_thumbnail_cache_entry(
                    temp_path,
                    cache_path,
                    expected_generation=before.token,
                )

    def test_clear_lease_release_is_idempotent_across_threads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lease = thumbnail_cache.begin_thumbnail_cache_clear(root)
            released: list[int] = []
            real_release = thumbnail_cache._release_sweep_lock

            def observe_release(descriptor: int) -> None:
                released.append(descriptor)
                real_release(descriptor)

            with patch.object(thumbnail_cache, "_release_sweep_lock", side_effect=observe_release):
                threads = [
                    threading.Thread(target=thumbnail_cache._release_clear_lease, args=(lease,)) for _ in range(2)
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=1)

            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(len(released), 1)

    def test_lock_initialization_reclaims_one_cache_file_when_storage_is_full(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cached = write_cache_file(root, HASH_NAMES[0], 10, age=500)
            real_initialize = thumbnail_cache._initialize_lock_byte
            calls = 0

            def fail_once(descriptor: int) -> None:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise OSError(errno.ENOSPC, "disk full")
                real_initialize(descriptor)

            with patch.object(thumbnail_cache, "_initialize_lock_byte", side_effect=fail_once):
                lock = thumbnail_cache._acquire_sweep_lock(root / SWEEP_LOCK_FILENAME, timeout_seconds=0)
            try:
                self.assertIsNotNone(lock.descriptor)
                self.assertFalse(cached.exists())
                self.assertEqual(calls, 2)
            finally:
                if lock.descriptor is not None:
                    thumbnail_cache._release_sweep_lock(lock.descriptor)

    def test_lock_bootstrap_never_deletes_unmanaged_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unmanaged = root / "preview.jpg"
            unmanaged.write_bytes(b"keep")

            with patch.object(
                thumbnail_cache,
                "_initialize_lock_byte",
                side_effect=OSError(errno.ENOSPC, "disk full"),
            ):
                lock = thumbnail_cache._acquire_sweep_lock(root / SWEEP_LOCK_FILENAME, timeout_seconds=0)

            self.assertIsNone(lock.descriptor)
            self.assertEqual(lock.error_number, errno.ENOSPC)
            self.assertEqual(unmanaged.read_bytes(), b"keep")

    def test_partial_lock_state_can_reclaim_space_before_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lock_path = root / SWEEP_LOCK_FILENAME
            lock_path.write_bytes(b"\0")
            cached = write_cache_file(root, HASH_NAMES[0], 10, age=500)
            real_initialize = thumbnail_cache._initialize_generation_slot
            calls = 0

            def fail_once(descriptor: int) -> None:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise OSError(getattr(errno, "EDQUOT", errno.ENOSPC), "quota full")
                real_initialize(descriptor)

            with patch.object(thumbnail_cache, "_initialize_generation_slot", side_effect=fail_once):
                lock = thumbnail_cache._acquire_sweep_lock(lock_path, timeout_seconds=0)
            try:
                self.assertIsNotNone(lock.descriptor)
                self.assertFalse(cached.exists())
                self.assertEqual(lock_path.stat().st_size, 65)
            finally:
                if lock.descriptor is not None:
                    thumbnail_cache._release_sweep_lock(lock.descriptor)

    def test_windows_lock_contention_is_normalized_and_retried(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            descriptor = os.open(Path(tmp) / "lock", os.O_CREAT | os.O_RDWR, 0o600)
            fake_msvcrt = SimpleNamespace(
                LK_NBLCK=1,
                LK_UNLCK=2,
                locking=Mock(side_effect=[PermissionError(errno.EACCES, "busy"), None]),
            )
            try:
                with (
                    patch.object(thumbnail_cache.os, "name", "nt"),
                    patch.dict(sys.modules, {"msvcrt": fake_msvcrt}),
                    patch.object(thumbnail_cache.time, "sleep"),
                ):
                    thumbnail_cache._lock_descriptor(descriptor, timeout_seconds=1)
            finally:
                os.close(descriptor)

            self.assertEqual(fake_msvcrt.locking.call_count, 2)

    def test_windows_non_contention_lock_errors_are_not_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            descriptor = os.open(Path(tmp) / "lock", os.O_CREAT | os.O_RDWR, 0o600)
            fake_msvcrt = SimpleNamespace(
                LK_NBLCK=1,
                LK_UNLCK=2,
                locking=Mock(side_effect=PermissionError(errno.EPERM, "denied")),
            )
            try:
                with (
                    patch.object(thumbnail_cache.os, "name", "nt"),
                    patch.dict(sys.modules, {"msvcrt": fake_msvcrt}),
                ):
                    with self.assertRaises(PermissionError):
                        thumbnail_cache._try_lock_descriptor(descriptor)
            finally:
                os.close(descriptor)

    def test_windows_sharing_violation_is_classified_as_lock_contention(self) -> None:
        error = OSError("sharing violation")
        error.winerror = 33

        self.assertTrue(thumbnail_cache._is_windows_lock_contention(error))

    def test_symlinked_files_and_directories_are_not_scanned_or_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cache"
            outside = Path(tmp) / "outside"
            root.mkdir()
            outside.mkdir()
            target = write_cache_file(outside, HASH_NAMES[0], 10, age=500)
            linked_file = root / HASH_NAMES[1]
            linked_file.symlink_to(target)
            linked_dir = root / "linked-dir"
            linked_dir.symlink_to(outside, target_is_directory=True)

            result = sweep_thumbnail_cache(
                root,
                policy=ThumbnailCachePolicy(max_bytes=0, max_files=0, min_age_seconds=0),
                now=NOW,
            )

            self.assertEqual(result.scanned_files, 0)
            self.assertEqual(result.deleted_files, 0)
            self.assertTrue(target.exists())
            self.assertTrue(linked_file.is_symlink())
            self.assertTrue(linked_dir.is_symlink())

    def test_unrelated_jpegs_are_not_managed_by_the_cache_sweeper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unrelated = write_cache_file(root, "portrait.jpg", 10, age=500)
            managed = write_cache_file(root, HASH_NAMES[0], 10, age=500)

            result = sweep_thumbnail_cache(
                root,
                policy=ThumbnailCachePolicy(max_bytes=0, max_files=0, min_age_seconds=0),
                now=NOW,
            )

            self.assertEqual(result.scanned_files, 1)
            self.assertEqual(result.deleted_files, 1)
            self.assertTrue(unrelated.exists())
            self.assertFalse(managed.exists())


if __name__ == "__main__":
    unittest.main()
