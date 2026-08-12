from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from culvia.media_service import ensure_thumbnail_file, thumbnail_cache_path


class ThumbnailGenerationCoordinator:
    def __init__(self, *, max_concurrency: int = 2, max_pending: int = 32) -> None:
        if max_concurrency < 1:
            raise ValueError("Thumbnail concurrency must be at least one")
        if max_pending < max_concurrency:
            raise ValueError("Thumbnail pending capacity cannot be smaller than concurrency")
        self._executor = ThreadPoolExecutor(
            max_workers=max_concurrency,
            thread_name_prefix="culvia-thumbnail",
        )
        self._lock = threading.Lock()
        self._inflight: dict[Path, Future[Path]] = {}
        self._pending_capacity = threading.BoundedSemaphore(max_pending)
        self._closed = False

    async def ensure(self, path: Path, cache_dir: Path, max_size: int) -> Path:
        cache_path, cache_hit = await asyncio.to_thread(_thumbnail_cache_target, path, cache_dir, max_size)
        if cache_hit:
            return cache_path

        created = False
        with self._lock:
            if self._closed:
                raise RuntimeError("Thumbnail coordinator is closed")
            future = self._inflight.get(cache_path)
            if future is None:
                if not self._pending_capacity.acquire(blocking=False):
                    raise ThumbnailQueueFullError("Thumbnail generation queue is full")
                try:
                    future = self._executor.submit(
                        ensure_thumbnail_file,
                        path,
                        cache_dir,
                        max_size,
                        cache_path=cache_path,
                    )
                except Exception:
                    self._pending_capacity.release()
                    raise
                self._inflight[cache_path] = future
                created = True
        if created:
            future.add_done_callback(lambda completed, key=cache_path: self._finish(key, completed))
        return await asyncio.shield(asyncio.wrap_future(future))

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=True)

    def _finish(self, cache_path: Path, future: Future[Path]) -> None:
        with self._lock:
            if self._inflight.get(cache_path) is future:
                self._inflight.pop(cache_path, None)
                self._pending_capacity.release()


class ThumbnailQueueFullError(RuntimeError):
    pass


def _thumbnail_cache_target(path: Path, cache_dir: Path, max_size: int) -> tuple[Path, bool]:
    cache_path = thumbnail_cache_path(path, cache_dir, max_size)
    try:
        return cache_path, cache_path.is_file() and cache_path.stat().st_size > 0
    except OSError:
        return cache_path, False
