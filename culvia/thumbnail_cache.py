from __future__ import annotations

import errno
import math
import os
import re
import stat
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


SWEEP_LOCK_FILENAME = ".thumbnail-cache-sweep.lock"
CLEAR_LOCK_FILENAME = ".thumbnail-cache-clear.lock"
THUMBNAIL_CACHE_FILENAME = re.compile(r"^[0-9a-f]{40}\.jpg$")
THUMBNAIL_TEMP_FILENAME = re.compile(r"^\.[0-9a-f]{40}\.jpg\.[^.]+\.tmp$")


class ThumbnailDeleteOutcome(str, Enum):
    DELETED = "deleted"
    PROTECTED = "protected"
    MISSING = "missing"
    FAILED = "failed"


DeleteCandidate = Callable[[Path], ThumbnailDeleteOutcome | bool]


class ThumbnailCacheUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class ThumbnailCacheGeneration:
    token: str
    clearing: bool = False


@dataclass
class ThumbnailCacheClearLease:
    cache_dir: Path
    token: str
    descriptor: int
    local_key: str
    release_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


_LOCAL_CLEAR_LEASE_LOCK = threading.Lock()
_LOCAL_CLEAR_LEASES: set[str] = set()


@dataclass(frozen=True)
class ThumbnailCachePolicy:
    max_bytes: int | None = 2 * 1024**3
    max_files: int | None = 20_000
    low_water_ratio: float = 0.8
    min_age_seconds: float = 3_600
    stale_temp_age_seconds: float = 86_400

    def __post_init__(self) -> None:
        for name in ("max_bytes", "max_files"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or value < 0):
                raise ValueError(f"{name} must be a non-negative integer or None")
        if isinstance(self.low_water_ratio, bool) or not math.isfinite(self.low_water_ratio):
            raise ValueError("low_water_ratio must be finite")
        if not 0 < self.low_water_ratio <= 1:
            raise ValueError("low_water_ratio must be greater than zero and at most one")
        for name in ("min_age_seconds", "stale_temp_age_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a non-negative finite number")


@dataclass(frozen=True)
class ThumbnailCacheSweepResult:
    completed: bool = False
    lock_acquired: bool = False
    skipped_due_to_lock: bool = False
    lock_error: str = ""
    scanned_files: int = 0
    scanned_bytes: int = 0
    eligible_files: int = 0
    high_water_exceeded: bool = False
    low_water_files: int | None = None
    low_water_bytes: int | None = None
    deleted_files: int = 0
    deleted_bytes: int = 0
    missing_files: int = 0
    protected_files: int = 0
    failed_deletions: int = 0
    stale_temp_files: int = 0
    deleted_temp_files: int = 0
    failed_temp_deletions: int = 0
    scan_errors: int = 0
    remaining_files: int = 0
    remaining_bytes: int = 0
    low_water_reached: bool = True
    soft_limit_exceeded: bool = False


@dataclass(frozen=True)
class _CacheFile:
    path: Path
    size: int
    accessed_at_ns: int
    modified_at: float
    mtime_ns: int
    device: int
    inode: int


def sweep_thumbnail_cache(
    cache_dir: str | Path,
    *,
    policy: ThumbnailCachePolicy | None = None,
    delete_candidate: DeleteCandidate | None = None,
    now: float | None = None,
    wait_for_lock_seconds: float = 0,
    reset_generation: bool = False,
) -> ThumbnailCacheSweepResult:
    """Synchronously sweep a cache; a false delete callback result means the path is protected."""
    active_policy = policy or ThumbnailCachePolicy()
    current_time = time.time() if now is None else float(now)
    root = Path(cache_dir)
    lock_path = root / SWEEP_LOCK_FILENAME

    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return ThumbnailCacheSweepResult(lock_error=repr(exc))

    clear_lease: ThumbnailCacheClearLease | None = None
    if reset_generation:
        try:
            clear_lease = begin_thumbnail_cache_clear(root)
        except (OSError, ThumbnailCacheUnavailableError) as exc:
            return ThumbnailCacheSweepResult(lock_error=repr(exc))

    lock = _acquire_sweep_lock(lock_path, timeout_seconds=wait_for_lock_seconds)
    if lock.descriptor is None:
        if clear_lease is not None:
            end_thumbnail_cache_clear(root, clear_lease)
        return ThumbnailCacheSweepResult(
            skipped_due_to_lock=lock.locked,
            lock_error=lock.error,
        )

    try:
        return _sweep_locked(
            root,
            active_policy,
            delete_candidate or _delete_candidate,
            current_time,
        )
    finally:
        _release_sweep_lock(lock.descriptor)
        if clear_lease is not None:
            end_thumbnail_cache_clear(root, clear_lease)


def thumbnail_cache_generation(cache_dir: str | Path) -> ThumbnailCacheGeneration:
    lock_path = Path(cache_dir) / SWEEP_LOCK_FILENAME
    try:
        descriptor = os.open(lock_path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    except FileNotFoundError:
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ThumbnailCacheUnavailableError(repr(exc)) from exc
        lock = _acquire_sweep_lock(lock_path, timeout_seconds=0)
        if lock.descriptor is None:
            if lock.locked:
                try:
                    descriptor = os.open(lock_path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
                except OSError:
                    return ThumbnailCacheGeneration(token="0", clearing=True)
                try:
                    locked_generation = _read_generation_state(descriptor)
                finally:
                    os.close(descriptor)
                return ThumbnailCacheGeneration(
                    token=locked_generation.token,
                    clearing=locked_generation.clearing,
                )
            _raise_lock_unavailable(lock)
        try:
            return _read_generation_state(lock.descriptor)
        finally:
            _release_sweep_lock(lock.descriptor)
    try:
        generation = _read_generation_state(descriptor)
    finally:
        os.close(descriptor)
    if not generation.clearing:
        return generation

    if _local_clear_lease_is_active(Path(cache_dir)):
        return generation
    clear_lock = _acquire_sweep_lock(Path(cache_dir) / CLEAR_LOCK_FILENAME, timeout_seconds=0)
    if clear_lock.descriptor is None:
        if clear_lock.locked:
            return generation
        _raise_lock_unavailable(clear_lock)
    clear_descriptor = clear_lock.descriptor
    lock = _acquire_sweep_lock(lock_path, timeout_seconds=10)
    if lock.descriptor is None:
        _release_sweep_lock(clear_descriptor)
        _raise_lock_unavailable(lock)
    try:
        current = _read_generation_state(lock.descriptor)
        if current.clearing:
            _write_generation_state(lock.descriptor, token=current.token, clearing=False)
            return ThumbnailCacheGeneration(token=current.token)
        return current
    finally:
        _release_sweep_lock(lock.descriptor)
        _release_sweep_lock(clear_descriptor)


def _raise_lock_unavailable(lock: _LockAttempt) -> None:
    if lock.error_number is not None and _is_storage_full_number(lock.error_number):
        raise OSError(lock.error_number, lock.error or "Thumbnail cache storage is full")
    raise ThumbnailCacheUnavailableError(lock.error or "Thumbnail cache is busy")


def publish_thumbnail_cache_entry(
    temp_path: Path,
    cache_path: Path,
    *,
    expected_generation: str,
    wait_for_lock_seconds: float = 10,
) -> None:
    lock = _acquire_sweep_lock(
        cache_path.parent / SWEEP_LOCK_FILENAME,
        timeout_seconds=wait_for_lock_seconds,
    )
    if lock.descriptor is None:
        _raise_lock_unavailable(lock)
    try:
        generation = _read_generation_state(lock.descriptor)
        if generation.clearing or generation.token != expected_generation:
            raise ThumbnailCacheUnavailableError("Thumbnail cache was cleared while the image was generated")
        os.replace(temp_path, cache_path)
    finally:
        _release_sweep_lock(lock.descriptor)


def begin_thumbnail_cache_clear(cache_dir: str | Path) -> ThumbnailCacheClearLease:
    root = Path(cache_dir)
    root.mkdir(parents=True, exist_ok=True)
    local_key = _claim_local_clear_lease(root)
    clear_lock = _acquire_sweep_lock(root / CLEAR_LOCK_FILENAME, timeout_seconds=0)
    if clear_lock.descriptor is None:
        _release_local_clear_lease(local_key)
        _raise_lock_unavailable(clear_lock)
    lease = ThumbnailCacheClearLease(root, uuid.uuid4().hex, clear_lock.descriptor, local_key)
    lock = _acquire_sweep_lock(root / SWEEP_LOCK_FILENAME, timeout_seconds=10)
    if lock.descriptor is None:
        _release_clear_lease(lease)
        _raise_lock_unavailable(lock)
    try:
        _write_generation_state(lock.descriptor, token=lease.token, clearing=True)
    except BaseException:
        _release_clear_lease(lease)
        raise
    finally:
        _release_sweep_lock(lock.descriptor)
    return lease


def end_thumbnail_cache_clear(cache_dir: str | Path, lease: ThumbnailCacheClearLease) -> None:
    root = Path(cache_dir)
    try:
        if root != lease.cache_dir:
            raise ThumbnailCacheUnavailableError("Thumbnail cache clear lease belongs to another cache")
        lock = _acquire_sweep_lock(root / SWEEP_LOCK_FILENAME, timeout_seconds=10)
        if lock.descriptor is None:
            _raise_lock_unavailable(lock)
        try:
            generation = _read_generation_state(lock.descriptor)
            if generation.token != lease.token:
                raise ThumbnailCacheUnavailableError("Thumbnail cache clear generation changed unexpectedly")
            _write_generation_state(lock.descriptor, token=lease.token, clearing=False)
        finally:
            _release_sweep_lock(lock.descriptor)
    finally:
        _release_clear_lease(lease)


def _release_clear_lease(lease: ThumbnailCacheClearLease) -> None:
    with lease.release_lock:
        if lease.descriptor < 0:
            return
        descriptor = lease.descriptor
        lease.descriptor = -1
    try:
        _release_sweep_lock(descriptor)
    finally:
        _release_local_clear_lease(lease.local_key)


def _local_clear_key(root: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(root)))


def _claim_local_clear_lease(root: Path) -> str:
    key = _local_clear_key(root)
    with _LOCAL_CLEAR_LEASE_LOCK:
        if key in _LOCAL_CLEAR_LEASES:
            raise ThumbnailCacheUnavailableError("Thumbnail cache is already being cleared")
        _LOCAL_CLEAR_LEASES.add(key)
    return key


def _release_local_clear_lease(key: str) -> None:
    with _LOCAL_CLEAR_LEASE_LOCK:
        _LOCAL_CLEAR_LEASES.discard(key)


def _local_clear_lease_is_active(root: Path) -> bool:
    key = _local_clear_key(root)
    with _LOCAL_CLEAR_LEASE_LOCK:
        return key in _LOCAL_CLEAR_LEASES


def _sweep_locked(
    root: Path,
    policy: ThumbnailCachePolicy,
    delete_candidate: DeleteCandidate,
    now: float,
) -> ThumbnailCacheSweepResult:
    files, stale_temps, scan_errors = _scan_cache(root, policy, now)
    deleted_temp_files, failed_temp_deletions = _delete_stale_temps(stale_temps)

    scanned_files = len(files)
    scanned_bytes = sum(item.size for item in files)
    low_water_files = _low_water(policy.max_files, policy.low_water_ratio)
    low_water_bytes = _low_water(policy.max_bytes, policy.low_water_ratio)
    high_water_exceeded = _over_limits(
        scanned_files,
        scanned_bytes,
        max_files=policy.max_files,
        max_bytes=policy.max_bytes,
    )
    eligible = [item for item in files if item.modified_at <= now - policy.min_age_seconds]
    eligible.sort(key=lambda item: (item.accessed_at_ns, item.mtime_ns, os.fspath(item.path)))

    remaining_files = scanned_files
    remaining_bytes = scanned_bytes
    deleted_files = 0
    deleted_bytes = 0
    missing_files = 0
    protected_files = 0
    failed_deletions = 0

    if high_water_exceeded:
        for candidate in eligible:
            if not _over_limits(
                remaining_files,
                remaining_bytes,
                max_files=low_water_files,
                max_bytes=low_water_bytes,
            ):
                break

            unchanged = _candidate_is_unchanged(candidate)
            if unchanged is ThumbnailDeleteOutcome.MISSING:
                missing_files += 1
                remaining_files -= 1
                remaining_bytes = max(0, remaining_bytes - candidate.size)
                continue
            if unchanged is ThumbnailDeleteOutcome.FAILED:
                failed_deletions += 1
                continue
            if unchanged is ThumbnailDeleteOutcome.PROTECTED:
                protected_files += 1
                continue

            outcome = _call_delete_candidate(delete_candidate, candidate.path)
            if outcome is ThumbnailDeleteOutcome.DELETED:
                deleted_files += 1
                deleted_bytes += candidate.size
                remaining_files -= 1
                remaining_bytes = max(0, remaining_bytes - candidate.size)
            elif outcome is ThumbnailDeleteOutcome.MISSING:
                missing_files += 1
                remaining_files -= 1
                remaining_bytes = max(0, remaining_bytes - candidate.size)
            elif outcome is ThumbnailDeleteOutcome.PROTECTED:
                protected_files += 1
            else:
                failed_deletions += 1

    low_water_reached = not high_water_exceeded or not _over_limits(
        remaining_files,
        remaining_bytes,
        max_files=low_water_files,
        max_bytes=low_water_bytes,
    )
    return ThumbnailCacheSweepResult(
        completed=True,
        lock_acquired=True,
        scanned_files=scanned_files,
        scanned_bytes=scanned_bytes,
        eligible_files=len(eligible),
        high_water_exceeded=high_water_exceeded,
        low_water_files=low_water_files,
        low_water_bytes=low_water_bytes,
        deleted_files=deleted_files,
        deleted_bytes=deleted_bytes,
        missing_files=missing_files,
        protected_files=protected_files,
        failed_deletions=failed_deletions,
        stale_temp_files=len(stale_temps),
        deleted_temp_files=deleted_temp_files,
        failed_temp_deletions=failed_temp_deletions,
        scan_errors=scan_errors,
        remaining_files=remaining_files,
        remaining_bytes=remaining_bytes,
        low_water_reached=low_water_reached,
        soft_limit_exceeded=high_water_exceeded and not low_water_reached,
    )


def _scan_cache(root: Path, policy: ThumbnailCachePolicy, now: float) -> tuple[list[_CacheFile], list[_CacheFile], int]:
    files: list[_CacheFile] = []
    stale_temps: list[_CacheFile] = []
    scan_errors = 0

    try:
        entries = list(os.scandir(root))
    except OSError:
        return files, stale_temps, 1

    for entry in entries:
        filename = entry.name
        try:
            if not entry.is_file(follow_symlinks=False):
                continue
        except OSError:
            scan_errors += 1
            continue
        try:
            is_thumbnail = bool(THUMBNAIL_CACHE_FILENAME.fullmatch(filename))
            is_hidden_temp = bool(THUMBNAIL_TEMP_FILENAME.fullmatch(filename))
            if not is_thumbnail and not is_hidden_temp:
                continue
            path = root / filename
            try:
                file_stat = os.stat(path, follow_symlinks=False)
            except OSError:
                scan_errors += 1
                continue
            if not stat.S_ISREG(file_stat.st_mode):
                continue
            item = _CacheFile(
                path=path,
                size=max(0, file_stat.st_size),
                accessed_at_ns=file_stat.st_atime_ns,
                modified_at=file_stat.st_mtime,
                mtime_ns=file_stat.st_mtime_ns,
                device=file_stat.st_dev,
                inode=file_stat.st_ino,
            )
            if is_thumbnail:
                files.append(item)
            elif item.modified_at <= now - policy.stale_temp_age_seconds:
                stale_temps.append(item)
        except OSError:
            scan_errors += 1

    return files, stale_temps, scan_errors


def _delete_stale_temps(stale_temps: list[_CacheFile]) -> tuple[int, int]:
    deleted = 0
    failed = 0
    for item in stale_temps:
        unchanged = _candidate_is_unchanged(item)
        if unchanged is ThumbnailDeleteOutcome.MISSING:
            continue
        if unchanged is not ThumbnailDeleteOutcome.DELETED:
            failed += 1
            continue
        try:
            item.path.unlink()
            deleted += 1
        except FileNotFoundError:
            continue
        except OSError:
            failed += 1
    return deleted, failed


def _candidate_is_unchanged(candidate: _CacheFile) -> ThumbnailDeleteOutcome:
    try:
        current = os.stat(candidate.path, follow_symlinks=False)
    except FileNotFoundError:
        return ThumbnailDeleteOutcome.MISSING
    except OSError:
        return ThumbnailDeleteOutcome.FAILED
    if not stat.S_ISREG(current.st_mode):
        return ThumbnailDeleteOutcome.PROTECTED
    identity = (current.st_dev, current.st_ino, current.st_size, current.st_atime_ns, current.st_mtime_ns)
    expected = (
        candidate.device,
        candidate.inode,
        candidate.size,
        candidate.accessed_at_ns,
        candidate.mtime_ns,
    )
    return ThumbnailDeleteOutcome.DELETED if identity == expected else ThumbnailDeleteOutcome.PROTECTED


def _call_delete_candidate(delete_candidate: DeleteCandidate, path: Path) -> ThumbnailDeleteOutcome:
    try:
        outcome = delete_candidate(path)
    except FileNotFoundError:
        return ThumbnailDeleteOutcome.MISSING
    except Exception:
        return ThumbnailDeleteOutcome.FAILED
    if isinstance(outcome, bool):
        return ThumbnailDeleteOutcome.DELETED if outcome else ThumbnailDeleteOutcome.PROTECTED
    if isinstance(outcome, ThumbnailDeleteOutcome):
        return outcome
    return ThumbnailDeleteOutcome.FAILED


def _delete_candidate(path: Path) -> ThumbnailDeleteOutcome:
    try:
        path.unlink()
    except FileNotFoundError:
        return ThumbnailDeleteOutcome.MISSING
    except OSError:
        return ThumbnailDeleteOutcome.FAILED
    return ThumbnailDeleteOutcome.DELETED


def _low_water(limit: int | None, ratio: float) -> int | None:
    return None if limit is None else int(limit * ratio)


def _over_limits(
    file_count: int,
    byte_count: int,
    *,
    max_files: int | None,
    max_bytes: int | None,
) -> bool:
    return (max_files is not None and file_count > max_files) or (max_bytes is not None and byte_count > max_bytes)


@dataclass(frozen=True)
class _LockAttempt:
    descriptor: int | None = None
    locked: bool = False
    error: str = ""
    error_number: int | None = None


def _acquire_sweep_lock(lock_path: Path, *, timeout_seconds: float) -> _LockAttempt:
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
    for attempt in range(2):
        descriptor: int | None = None
        try:
            descriptor = os.open(lock_path, flags, 0o600)
            _initialize_lock_byte(descriptor)
            _lock_descriptor(descriptor, timeout_seconds=timeout_seconds)
            _initialize_generation_slot(descriptor)
        except BlockingIOError:
            if descriptor is not None:
                os.close(descriptor)
            return _LockAttempt(locked=True)
        except OSError as exc:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if attempt == 0 and _is_storage_full_error(exc) and _reclaim_one_cache_file(lock_path.parent):
                continue
            return _LockAttempt(error=repr(exc), error_number=exc.errno)
        return _LockAttempt(descriptor=descriptor)
    raise AssertionError("thumbnail cache lock retry exhausted")


def _reclaim_one_cache_file(root: Path) -> bool:
    candidates: list[tuple[int, int, str, Path]] = []
    try:
        entries = list(os.scandir(root))
    except OSError:
        return False
    for entry in entries:
        if not THUMBNAIL_CACHE_FILENAME.fullmatch(entry.name):
            continue
        try:
            if not entry.is_file(follow_symlinks=False):
                continue
            file_stat = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        if not stat.S_ISREG(file_stat.st_mode):
            continue
        candidates.append((file_stat.st_atime_ns, file_stat.st_mtime_ns, entry.name, root / entry.name))
    for _atime, _mtime, _name, path in sorted(candidates):
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            continue
        return True
    return False


def _is_storage_full_error(exc: OSError) -> bool:
    return _is_storage_full_number(exc.errno) or getattr(exc, "winerror", None) in {39, 112}


def _is_storage_full_number(error_number: int | None) -> bool:
    return error_number in {errno.ENOSPC, getattr(errno, "EDQUOT", -1)}


def _lock_descriptor(descriptor: int, *, timeout_seconds: float) -> None:
    deadline = time.monotonic() + max(0, timeout_seconds)
    while True:
        try:
            _try_lock_descriptor(descriptor)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))


def _initialize_lock_byte(descriptor: int) -> None:
    if os.fstat(descriptor).st_size > 0:
        return
    os.lseek(descriptor, 0, os.SEEK_SET)
    if os.write(descriptor, b"\0") != 1:
        raise OSError(errno.EIO, "Thumbnail cache lock initialization did not make progress")
    os.fsync(descriptor)


def _initialize_generation_slot(descriptor: int) -> None:
    expected_size = 1 + _GENERATION_STATE_BYTES
    current_size = os.fstat(descriptor).st_size
    if current_size >= expected_size:
        return
    os.lseek(descriptor, current_size, os.SEEK_SET)
    remaining = expected_size - current_size
    while remaining:
        written = os.write(descriptor, b"\0" * remaining)
        if written <= 0:
            raise OSError(errno.EIO, "Thumbnail cache lock initialization did not make progress")
        remaining -= written
    os.fsync(descriptor)


def _try_lock_descriptor(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"0")
            os.fsync(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if _is_windows_lock_contention(exc):
                raise BlockingIOError(errno.EWOULDBLOCK, "Thumbnail cache lock is busy") from exc
            raise
        return

    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _is_windows_lock_contention(exc: OSError) -> bool:
    contention_errnos = {errno.EACCES, errno.EAGAIN}
    for name in ("EDEADLK", "EDEADLOCK"):
        value = getattr(errno, name, None)
        if value is not None:
            contention_errnos.add(value)
    return exc.errno in contention_errnos or getattr(exc, "winerror", None) in {32, 33}


_GENERATION_STATE_BYTES = 64


def _read_generation_state(descriptor: int) -> ThumbnailCacheGeneration:
    os.lseek(descriptor, 1, os.SEEK_SET)
    chunks: list[bytes] = []
    remaining = _GENERATION_STATE_BYTES
    while remaining:
        chunk = os.read(descriptor, remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    payload = b"".join(chunks).rstrip(b"\0").decode("ascii", errors="ignore")
    if payload.startswith("C:") and len(payload) > 2:
        token = payload[2:]
        owner_text, separator, legacy_token = token.partition(":")
        if separator and owner_text.isdigit() and legacy_token:
            token = legacy_token
        return ThumbnailCacheGeneration(token=token, clearing=True)
    if payload.startswith("R:") and len(payload) > 2:
        return ThumbnailCacheGeneration(token=payload[2:])
    return ThumbnailCacheGeneration(token="0")


def _write_generation_state(
    descriptor: int,
    *,
    token: str,
    clearing: bool,
) -> None:
    prefix = "C:" if clearing else "R:"
    payload = f"{prefix}{token}".encode("ascii")
    if len(payload) > _GENERATION_STATE_BYTES:
        raise ValueError("Thumbnail cache generation token is too long")
    os.lseek(descriptor, 1, os.SEEK_SET)
    remaining = memoryview(payload.ljust(_GENERATION_STATE_BYTES, b"\0"))
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError(errno.EIO, "Thumbnail cache generation state write did not make progress")
        remaining = remaining[written:]
    os.fsync(descriptor)


def _release_sweep_lock(descriptor: int) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
