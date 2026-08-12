from __future__ import annotations

import asyncio
import errno
import functools
import os
import threading
import time
from collections.abc import AsyncIterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TypeVar

from culvia.media_service import ensure_thumbnail_file, thumbnail_cache_path
from culvia.thumbnail_cache import (
    begin_thumbnail_cache_clear,
    end_thumbnail_cache_clear,
    ThumbnailCacheClearLease,
    ThumbnailCachePolicy,
    ThumbnailCacheSweepResult,
    ThumbnailDeleteOutcome,
    ThumbnailCacheUnavailableError,
    publish_thumbnail_cache_entry,
    sweep_thumbnail_cache,
    thumbnail_cache_generation,
)


MAX_THUMBNAIL_CONTENT_BYTES = 32 * 1024**2
T = TypeVar("T")


class ThumbnailGenerationCoordinator:
    def __init__(
        self,
        *,
        max_concurrency: int = 2,
        max_pending: int = 32,
        cache_policy: ThumbnailCachePolicy | None = None,
        sweep_interval_seconds: float = 300,
        touch_interval_seconds: float = 3_600,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("Thumbnail concurrency must be at least one")
        if max_pending < max_concurrency:
            raise ValueError("Thumbnail pending capacity cannot be smaller than concurrency")
        if sweep_interval_seconds < 0 or touch_interval_seconds < 0:
            raise ValueError("Thumbnail cache intervals cannot be negative")
        self._executor = ThreadPoolExecutor(
            max_workers=max_concurrency,
            thread_name_prefix="culvia-thumbnail",
        )
        self._janitor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="culvia-thumbnail-cache")
        self._lock = threading.Condition(threading.Lock())
        self._inflight: dict[Path, Future[Path]] = {}
        self._leased: dict[Path, int] = {}
        self._clearing: set[Path] = set()
        self._pending_capacity = threading.BoundedSemaphore(max_pending)
        self._cache_policy = cache_policy or ThumbnailCachePolicy()
        self._sweep_interval_seconds = float(sweep_interval_seconds)
        self._touch_interval_seconds = float(touch_interval_seconds)
        self._last_sweep_started: dict[Path, float] = {}
        self._emergency_sweeps: dict[Path, Future[ThumbnailCacheSweepResult]] = {}
        self._last_sweep_result: ThumbnailCacheSweepResult | None = None
        self._closed = False

    async def ensure(self, path: Path, cache_dir: Path, max_size: int) -> Path:
        try:
            cache_path = await self._ensure_once(path, cache_dir, max_size)
        except ThumbnailCacheUnavailableError as exc:
            raise ThumbnailQueueFullError(str(exc)) from exc
        except OSError as exc:
            if not _is_storage_full_error(exc):
                raise
            await self._emergency_sweep(cache_dir)
            try:
                cache_path = await self._ensure_once(path, cache_dir, max_size)
            except ThumbnailCacheUnavailableError as retry_exc:
                raise ThumbnailQueueFullError(str(retry_exc)) from retry_exc
            except OSError as retry_exc:
                if _is_storage_full_error(retry_exc):
                    raise ThumbnailStorageFullError("Thumbnail cache storage is full") from retry_exc
                raise
        self.maybe_schedule_sweep(cache_dir)
        return cache_path

    async def ensure_content(self, path: Path, cache_dir: Path, max_size: int) -> tuple[Path, bytes]:
        for attempt in range(2):
            cache_path = await self.ensure(path, cache_dir, max_size)
            try:
                return cache_path, await self._read_leased(cache_path, Path(cache_dir))
            except FileNotFoundError:
                if attempt:
                    raise
            except ThumbnailCacheEntryInvalidError:
                await asyncio.to_thread(_remove_oversized_cache_file, cache_path)
                if attempt:
                    raise
        raise FileNotFoundError(path)

    async def clear_cache(self, cache_dir: Path, *, timeout_seconds: float = 10) -> ThumbnailCacheSweepResult:
        async with self.clearing_cache(cache_dir, timeout_seconds=timeout_seconds) as result:
            return result

    @asynccontextmanager
    async def clearing_cache(
        self,
        cache_dir: Path,
        *,
        timeout_seconds: float = 10,
    ) -> AsyncIterator[ThumbnailCacheSweepResult]:
        normalized_dir = Path(cache_dir)
        clear_lease: ThumbnailCacheClearLease | None = None
        operation_error: BaseException | None = None
        begin_task: asyncio.Task[ThumbnailCacheClearLease] | None = None
        sweep_future: Future[ThumbnailCacheSweepResult] | None = None
        with self._lock:
            if self._closed:
                raise RuntimeError("Thumbnail coordinator is closed")
            if normalized_dir in self._clearing:
                raise ThumbnailQueueFullError("Thumbnail cache is already being cleared")
            self._clearing.add(normalized_dir)
        try:
            await asyncio.to_thread(self._wait_until_cache_idle, normalized_dir, timeout_seconds)
            begin_task = asyncio.create_task(asyncio.to_thread(begin_thumbnail_cache_clear, normalized_dir))
            try:
                clear_lease = await asyncio.shield(begin_task)
            except ThumbnailCacheUnavailableError as exc:
                raise ThumbnailQueueFullError(str(exc)) from exc
            clear_policy = ThumbnailCachePolicy(
                max_bytes=0,
                max_files=0,
                low_water_ratio=1,
                min_age_seconds=0,
                stale_temp_age_seconds=self._cache_policy.stale_temp_age_seconds,
            )
            sweep_future = self._schedule_sweep(
                normalized_dir,
                force=True,
                policy=clear_policy,
                reset_generation=False,
            )
            if sweep_future is None:
                raise RuntimeError("Thumbnail cache clear could not start")
            result = await asyncio.shield(asyncio.wrap_future(sweep_future))
            if (
                not result.completed
                or result.soft_limit_exceeded
                or result.failed_deletions
                or result.failed_temp_deletions
                or result.scan_errors
                or result.remaining_files
            ):
                raise OSError(result.lock_error or "Thumbnail cache is busy")
            yield result
        except BaseException as exc:
            operation_error = exc
            raise
        finally:
            cleanup_error: BaseException | None = None
            try:
                if clear_lease is None and begin_task is not None:
                    try:
                        clear_lease = await _await_task_uninterruptibly(begin_task)
                    except BaseException as exc:
                        cleanup_error = exc
                if sweep_future is not None:
                    try:
                        await _await_future_uninterruptibly(sweep_future)
                    except BaseException as exc:
                        cleanup_error = cleanup_error or exc
                if clear_lease is not None:
                    end_task = asyncio.create_task(
                        asyncio.to_thread(end_thumbnail_cache_clear, normalized_dir, clear_lease)
                    )
                    try:
                        await _await_task_uninterruptibly(end_task)
                    except BaseException as exc:
                        cleanup_error = cleanup_error or exc
            finally:
                with self._lock:
                    self._clearing.discard(normalized_dir)
                    self._lock.notify_all()
            if cleanup_error is not None and operation_error is None:
                raise cleanup_error

    def start(self, cache_dir: Path) -> None:
        self._schedule_sweep(cache_dir, force=True)

    def maybe_schedule_sweep(self, cache_dir: Path) -> None:
        self._schedule_sweep(cache_dir, force=False)

    @property
    def last_sweep_result(self) -> ThumbnailCacheSweepResult | None:
        with self._lock:
            return self._last_sweep_result

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._lock.notify_all()
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._janitor.shutdown(wait=True, cancel_futures=True)

    async def _ensure_once(self, path: Path, cache_dir: Path, max_size: int) -> Path:
        normalized_dir = Path(cache_dir)
        with self._lock:
            self._assert_available(normalized_dir)
        cache_path, cache_hit = await asyncio.to_thread(_thumbnail_cache_target, path, cache_dir, max_size)
        if cache_hit:
            generation = await asyncio.to_thread(thumbnail_cache_generation, normalized_dir)
            if generation.clearing:
                raise ThumbnailCacheUnavailableError("Thumbnail cache is being cleared")
            return cache_path

        creator_claimed = False
        with self._lock:
            self._assert_available(normalized_dir)
            future = self._inflight.get(cache_path)
            if future is None:
                if not self._pending_capacity.acquire(blocking=False):
                    raise ThumbnailQueueFullError("Thumbnail generation queue is full")
                future = Future()
                self._inflight[cache_path] = future
                creator_claimed = True
        if not creator_claimed:
            return await asyncio.shield(asyncio.wrap_future(future))

        initializer = asyncio.create_task(
            self._initialize_generation(
                path,
                cache_dir,
                normalized_dir,
                max_size,
                cache_path,
                future,
            )
        )
        initializer.add_done_callback(_consume_task_exception)
        return await asyncio.shield(asyncio.wrap_future(future))

    async def _initialize_generation(
        self,
        path: Path,
        cache_dir: Path,
        normalized_dir: Path,
        max_size: int,
        cache_path: Path,
        future: Future[Path],
    ) -> None:
        try:
            generation = await asyncio.to_thread(thumbnail_cache_generation, normalized_dir)
            if generation.clearing:
                raise ThumbnailCacheUnavailableError("Thumbnail cache is being cleared")
            publish_temp = functools.partial(
                publish_thumbnail_cache_entry,
                expected_generation=generation.token,
            )
            with self._lock:
                self._assert_available(normalized_dir)
            generation_future = self._executor.submit(
                ensure_thumbnail_file,
                path,
                cache_dir,
                max_size,
                cache_path=cache_path,
                publish_temp=publish_temp,
            )
            result = await asyncio.shield(asyncio.wrap_future(generation_future))
        except BaseException as exc:
            if not future.done():
                future.set_exception(exc)
        else:
            if not future.done():
                future.set_result(result)
        finally:
            self._finish_generation(cache_path, future)

    async def _read_leased(self, cache_path: Path, cache_dir: Path) -> bytes:
        with self._lock:
            self._assert_available(cache_dir)
            self._leased[cache_path] = self._leased.get(cache_path, 0) + 1
        try:
            return await asyncio.to_thread(_read_cache_file, cache_path, self._touch_interval_seconds)
        finally:
            with self._lock:
                remaining = self._leased.get(cache_path, 1) - 1
                if remaining > 0:
                    self._leased[cache_path] = remaining
                else:
                    self._leased.pop(cache_path, None)
                self._lock.notify_all()

    def _finish_generation(self, cache_path: Path, future: Future[Path]) -> None:
        with self._lock:
            if self._inflight.get(cache_path) is future:
                self._inflight.pop(cache_path, None)
                self._pending_capacity.release()
                self._lock.notify_all()

    def _schedule_sweep(
        self,
        cache_dir: Path,
        *,
        force: bool,
        policy: ThumbnailCachePolicy | None = None,
        reset_generation: bool = False,
    ) -> Future[ThumbnailCacheSweepResult] | None:
        normalized_dir = Path(cache_dir)
        now = time.monotonic()
        with self._lock:
            if self._closed:
                return None
            previous = self._last_sweep_started.get(normalized_dir)
            if not force and previous is not None and now - previous < self._sweep_interval_seconds:
                return None
            self._last_sweep_started[normalized_dir] = now
            future = self._janitor.submit(
                sweep_thumbnail_cache,
                normalized_dir,
                policy=policy or self._cache_policy,
                delete_candidate=self._delete_candidate,
                reset_generation=reset_generation,
            )
        future.add_done_callback(self._finish_sweep)
        return future

    def _finish_sweep(self, future: Future[ThumbnailCacheSweepResult]) -> None:
        try:
            result = future.result()
        except Exception:
            return
        with self._lock:
            self._last_sweep_result = result

    async def _emergency_sweep(self, cache_dir: Path) -> None:
        normalized_dir = Path(cache_dir)
        emergency_policy = ThumbnailCachePolicy(
            max_bytes=0,
            max_files=None,
            low_water_ratio=1,
            min_age_seconds=0,
            stale_temp_age_seconds=self._cache_policy.stale_temp_age_seconds,
        )
        created = False
        with self._lock:
            future = self._emergency_sweeps.get(normalized_dir)
            if future is None or future.done():
                future = self._janitor.submit(
                    sweep_thumbnail_cache,
                    normalized_dir,
                    policy=emergency_policy,
                    delete_candidate=self._delete_candidate,
                    wait_for_lock_seconds=10,
                )
                self._emergency_sweeps[normalized_dir] = future
                created = True
        if created:
            future.add_done_callback(self._finish_sweep)
            future.add_done_callback(lambda completed, key=normalized_dir: self._finish_emergency(key, completed))
        result = await asyncio.shield(asyncio.wrap_future(future))
        if not result.completed:
            raise ThumbnailStorageFullError(
                f"Thumbnail cache could not be reclaimed: {result.lock_error or 'cache is busy'}"
            )

    def _finish_emergency(self, cache_dir: Path, future: Future[ThumbnailCacheSweepResult]) -> None:
        with self._lock:
            if self._emergency_sweeps.get(cache_dir) is future:
                self._emergency_sweeps.pop(cache_dir, None)

    def _delete_candidate(self, path: Path) -> ThumbnailDeleteOutcome:
        with self._lock:
            if path in self._inflight or self._leased.get(path, 0) > 0:
                return ThumbnailDeleteOutcome.PROTECTED
            try:
                path.unlink()
            except FileNotFoundError:
                return ThumbnailDeleteOutcome.MISSING
            except OSError:
                return ThumbnailDeleteOutcome.FAILED
            return ThumbnailDeleteOutcome.DELETED

    def _assert_available(self, cache_dir: Path) -> None:
        if self._closed:
            raise RuntimeError("Thumbnail coordinator is closed")
        if cache_dir in self._clearing:
            raise ThumbnailQueueFullError("Thumbnail cache is being cleared")

    def _wait_until_cache_idle(self, cache_dir: Path, timeout_seconds: float) -> None:
        deadline = time.monotonic() + max(0, timeout_seconds)
        with self._lock:
            while self._cache_is_active(cache_dir):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Thumbnail cache is still active")
                self._lock.wait(timeout=remaining)

    def _cache_is_active(self, cache_dir: Path) -> bool:
        return any(path.parent == cache_dir for path in self._inflight) or any(
            path.parent == cache_dir and count > 0 for path, count in self._leased.items()
        )


class ThumbnailQueueFullError(RuntimeError):
    pass


class ThumbnailStorageFullError(RuntimeError):
    pass


class ThumbnailCacheEntryInvalidError(RuntimeError):
    pass


def _thumbnail_cache_target(path: Path, cache_dir: Path, max_size: int) -> tuple[Path, bool]:
    cache_path = thumbnail_cache_path(path, cache_dir, max_size)
    try:
        return cache_path, cache_path.is_file() and cache_path.stat().st_size > 0
    except OSError:
        return cache_path, False


def _read_cache_file(path: Path, touch_interval_seconds: float) -> bytes:
    with path.open("rb") as handle:
        file_stat = os.fstat(handle.fileno())
        if file_stat.st_size > MAX_THUMBNAIL_CONTENT_BYTES:
            raise ThumbnailCacheEntryInvalidError("Thumbnail cache entry is too large")
        content = handle.read(MAX_THUMBNAIL_CONTENT_BYTES + 1)
        if len(content) > MAX_THUMBNAIL_CONTENT_BYTES:
            raise ThumbnailCacheEntryInvalidError("Thumbnail cache entry grew beyond the read limit")
    now_ns = time.time_ns()
    if now_ns - file_stat.st_atime_ns >= int(touch_interval_seconds * 1_000_000_000):
        try:
            os.utime(path, ns=(now_ns, file_stat.st_mtime_ns), follow_symlinks=False)
        except OSError:
            pass
    return content


def _remove_oversized_cache_file(path: Path) -> None:
    try:
        if path.stat().st_size <= MAX_THUMBNAIL_CONTENT_BYTES:
            return
        path.unlink()
    except OSError:
        pass


def _is_storage_full_error(exc: OSError) -> bool:
    return exc.errno in {errno.ENOSPC, getattr(errno, "EDQUOT", -1)} or getattr(exc, "winerror", None) in {
        39,
        112,
    }


def _consume_task_exception(task: asyncio.Task[None]) -> None:
    try:
        task.exception()
    except BaseException:
        pass


async def _await_task_uninterruptibly(task: asyncio.Task[T]) -> T:
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    return task.result()


async def _await_future_uninterruptibly(future: Future[T]) -> T:
    wrapped = asyncio.wrap_future(future)
    while not future.done():
        try:
            await asyncio.shield(wrapped)
        except asyncio.CancelledError:
            continue
    return future.result()
