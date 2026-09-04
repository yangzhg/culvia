from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

import requests
from huggingface_hub import hf_hub_download, hf_hub_url

from culvia.job_text import TranslatableRuntimeError
from culvia.settings import rsinema_model_cache_dir


MODEL_ID = "rsinema/aesthetic-scorer"
# Audited pins and update procedure: docs/en/developer/model-supply-chain.md.
MODEL_REVISION = "2e93f809b484701a79ecc046ae2057c9084e1d38"
MODEL_PT_SHA256 = "59853d88e95c287d101bd692c876232f5cd4a860299060d370258ad68b36042d"
MODEL_CACHE_REPO_DIR = "models--rsinema--aesthetic-scorer"
APP_MODEL_CACHE_DIR = rsinema_model_cache_dir()
MODEL_REQUIRED_CACHE_FILES = [
    "preprocessor_config.json",
    "tokenizer_config.json",
    "vocab.json",
    "merges.txt",
    "model.pt",
]
CLIP_REFERENCE_MODEL_ID = "openai/clip-vit-base-patch32"
# This verified conversion commit is intentionally not the repository's moving main branch.
CLIP_REFERENCE_MODEL_REVISION = "eaee4c876b93e66f7fac584b529025a96d71ad66"
CLIP_REFERENCE_WEIGHT_FILENAME = "model.safetensors"
CLIP_REFERENCE_WEIGHT_SHA256 = "99d28a652e6ec46629ab7047a0ac82c69b1fe11e0ce672c43af65d3a9a3fc05d"
CLIP_REFERENCE_MODEL_REPO_DIR = "models--openai--clip-vit-base-patch32"
CLIP_REFERENCE_REQUIRED_CACHE_FILES = [
    "config.json",
    "preprocessor_config.json",
    "tokenizer_config.json",
    "vocab.json",
    "merges.txt",
    CLIP_REFERENCE_WEIGHT_FILENAME,
]

ModelDownloadCallback = Callable[[str, int, int, str, dict[str, object]], None]

INTEGRITY_STATE_MISSING = "missing"
INTEGRITY_STATE_VERIFIED = "verified"
INTEGRITY_STATE_MISMATCH = "mismatch"
INTEGRITY_STATE_UNREADABLE = "unreadable"
INTEGRITY_STATE_NOT_CHECKED = "not_checked"

_FILE_SHA256_CACHE_MAX_ENTRIES = 16
_FILE_SHA256_CACHE: dict[tuple[str, int, int, int, int], tuple[str, str, str]] = {}
_FILE_SHA256_CACHE_LOCK = threading.Lock()
_INTEGRITY_MARKER_SCHEMA_VERSION = 1


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_fingerprint(path: Path) -> tuple[str, int, int, int, int]:
    stat = path.stat()
    return (
        str(path.absolute()),
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
        getattr(stat, "st_ino", 0),
    )


def _remember_file_sha256(
    fingerprint: tuple[str, int, int, int, int],
    digest: str,
    *,
    revision: str,
    filename: str,
) -> None:
    with _FILE_SHA256_CACHE_LOCK:
        stale = [key for key in _FILE_SHA256_CACHE if key[0] == fingerprint[0]]
        for key in stale:
            _FILE_SHA256_CACHE.pop(key, None)
        while len(_FILE_SHA256_CACHE) >= _FILE_SHA256_CACHE_MAX_ENTRIES:
            _FILE_SHA256_CACHE.pop(next(iter(_FILE_SHA256_CACHE)))
        _FILE_SHA256_CACHE[fingerprint] = (digest, revision, filename)


def _integrity_marker_path(path: Path) -> Path:
    path_key = hashlib.sha256(os.fsencode(str(path.absolute()))).hexdigest()
    return APP_MODEL_CACHE_DIR / ".integrity" / f"{path_key}.json"


def _fingerprint_payload(fingerprint: tuple[str, int, int, int, int]) -> dict[str, int]:
    return {
        "size": fingerprint[1],
        "mtimeNs": fingerprint[2],
        "ctimeNs": fingerprint[3],
        "inode": fingerprint[4],
    }


def _write_integrity_marker(
    path: Path,
    fingerprint: tuple[str, int, int, int, int],
    expected_sha256: str,
    *,
    revision: str,
    filename: str,
) -> None:
    marker_path = _integrity_marker_path(path)
    temp_path = marker_path.with_name(f".{marker_path.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp")
    payload = {
        "schemaVersion": _INTEGRITY_MARKER_SCHEMA_VERSION,
        "algorithm": "sha256",
        "expectedSha256": expected_sha256.lower(),
        "revision": revision,
        "filename": filename,
        "fingerprint": _fingerprint_payload(fingerprint),
    }
    try:
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        os.replace(temp_path, marker_path)
    except OSError:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _remove_integrity_marker(path: Path) -> None:
    try:
        _integrity_marker_path(path).unlink(missing_ok=True)
    except OSError:
        pass


def _record_verified_file_sha256(
    path: Path,
    digest: str,
    *,
    revision: str,
    filename: str,
) -> None:
    fingerprint = _file_fingerprint(path)
    _remember_file_sha256(
        fingerprint,
        digest,
        revision=revision,
        filename=filename,
    )
    _write_integrity_marker(
        path,
        fingerprint,
        digest,
        revision=revision,
        filename=filename,
    )


def _marker_verifies_fingerprint(
    path: Path,
    fingerprint: tuple[str, int, int, int, int],
    expected_sha256: str,
    *,
    revision: str,
    filename: str,
) -> bool:
    try:
        marker_path = _integrity_marker_path(path)
        if marker_path.stat().st_size > 4096:
            return False
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return bool(
        isinstance(payload, dict)
        and payload.get("schemaVersion") == _INTEGRITY_MARKER_SCHEMA_VERSION
        and payload.get("algorithm") == "sha256"
        and payload.get("expectedSha256") == expected_sha256.lower()
        and payload.get("revision") == revision
        and payload.get("filename") == filename
        and payload.get("fingerprint") == _fingerprint_payload(fingerprint)
    )


def cached_file_integrity_state(
    path: str | Path,
    expected_sha256: str,
    *,
    revision: str = "",
    filename: str | None = None,
) -> str:
    model_path = Path(path)
    label = filename or model_path.name
    try:
        if not model_path.exists():
            return INTEGRITY_STATE_MISSING
        if not model_path.is_file():
            return INTEGRITY_STATE_UNREADABLE
        fingerprint = _file_fingerprint(model_path)
    except OSError:
        return INTEGRITY_STATE_UNREADABLE
    with _FILE_SHA256_CACHE_LOCK:
        cached = _FILE_SHA256_CACHE.get(fingerprint)
    actual_sha256 = None
    if cached is not None and cached[1:] == (revision, label):
        actual_sha256 = cached[0]
    if actual_sha256 is None:
        if not _marker_verifies_fingerprint(
            model_path,
            fingerprint,
            expected_sha256,
            revision=revision,
            filename=label,
        ):
            return INTEGRITY_STATE_NOT_CHECKED
        actual_sha256 = expected_sha256.lower()
        _remember_file_sha256(
            fingerprint,
            actual_sha256,
            revision=revision,
            filename=label,
        )
    return (
        INTEGRITY_STATE_VERIFIED
        if hmac.compare_digest(actual_sha256, expected_sha256.lower())
        else INTEGRITY_STATE_MISMATCH
    )


def verify_file_sha256(
    path: str | Path,
    expected_sha256: str,
    *,
    filename: str | None = None,
    revision: str = "",
) -> Path:
    model_path = Path(path)
    label = filename or model_path.name
    try:
        before = _file_fingerprint(model_path)
        actual_sha256 = file_sha256(model_path)
        after = _file_fingerprint(model_path)
    except OSError as exc:
        raise TranslatableRuntimeError(
            "error.modelIntegrityFailed",
            fallback=f"模型文件完整性校验失败：{label}",
            filename=label,
        ) from exc
    if before != after:
        raise TranslatableRuntimeError(
            "error.modelIntegrityFailed",
            fallback=f"模型文件完整性校验失败：{label}",
            filename=label,
        )
    _remember_file_sha256(
        after,
        actual_sha256,
        revision=revision,
        filename=label,
    )
    if not hmac.compare_digest(actual_sha256, expected_sha256.lower()):
        _remove_integrity_marker(model_path)
        raise TranslatableRuntimeError(
            "error.modelIntegrityFailed",
            fallback=f"模型文件完整性校验失败：{label}",
            filename=label,
        )
    _write_integrity_marker(model_path, after, expected_sha256, revision=revision, filename=label)
    return model_path


def sanitize_proxy_env_for_httpx() -> None:
    """Avoid httpx URL parsing failures from CIDR/IPv6 entries in NO_PROXY."""

    for key in ("NO_PROXY", "no_proxy"):
        value = os.environ.get(key)
        if not value:
            continue
        keep = []
        for part in value.split(","):
            item = part.strip()
            if not item or "/" in item or ":" in item:
                continue
            keep.append(item)
        os.environ[key] = ",".join(keep or ["localhost", "127.0.0.1"])


def format_bytes(size: int | float | None) -> str:
    # Unknown sizes render as empty so the web UI can fall back to its own localized label.
    if size is None:
        return ""
    size = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def format_duration(seconds: int | float | None) -> str:
    if seconds is None:
        return "计算中"
    seconds = max(0, int(seconds))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}小时{minutes:02d}分"
    if minutes:
        return f"{minutes}分{sec:02d}秒"
    return f"{sec}秒"


def get_huggingface_cache_root() -> Path:
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        return Path(hf_home).expanduser() / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def get_hf_repo_cache_dir(repo_dir: str) -> Path:
    return get_huggingface_cache_root() / repo_dir


def get_app_model_path() -> Path:
    return APP_MODEL_CACHE_DIR / "model.pt"


def get_app_model_part_path() -> Path:
    return APP_MODEL_CACHE_DIR / "model.pt.part"


def _snapshot_candidates(snapshots_dir: Path, revision: str | None) -> list[Path]:
    if revision:
        snapshot = snapshots_dir / revision
        return [snapshot] if snapshot.is_dir() else []
    return sorted(
        [path for path in snapshots_dir.iterdir() if path.is_dir()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def get_model_cache_status() -> dict[str, object]:
    repo_cache = get_hf_repo_cache_dir(MODEL_CACHE_REPO_DIR)
    snapshots_dir = repo_cache / "snapshots"
    app_model_path = get_app_model_path()
    app_part_path = get_app_model_part_path()
    app_integrity_state = cached_file_integrity_state(
        app_model_path,
        MODEL_PT_SHA256,
        revision=MODEL_REVISION,
        filename="model.pt",
    )
    app_model_present = app_integrity_state != INTEGRITY_STATE_MISSING
    app_model_size = app_model_path.stat().st_size if app_model_path.is_file() else None
    active_download_size = app_part_path.stat().st_size if app_part_path.exists() else 0
    status: dict[str, object] = {
        "model_id": MODEL_ID,
        "revision": MODEL_REVISION,
        "cache_root": str(repo_cache),
        "app_cache_root": str(APP_MODEL_CACHE_DIR),
        "snapshot_path": "",
        "downloaded": False,
        "partial": app_model_present or active_download_size > 0,
        "model_file": str(app_model_path) if app_model_present else "",
        "model_size": app_model_size,
        "model_size_label": format_bytes(app_model_size),
        "integrity_algorithm": "sha256",
        "integrity_state": app_integrity_state,
        "active_download_size": active_download_size,
        "active_download_size_label": format_bytes(active_download_size),
        "missing_files": MODEL_REQUIRED_CACHE_FILES.copy(),
    }

    if not snapshots_dir.exists():
        return status

    snapshots = _snapshot_candidates(snapshots_dir, MODEL_REVISION)
    for snapshot in snapshots:
        snapshot_model_file = snapshot / "model.pt"
        snapshot_integrity_state = cached_file_integrity_state(
            snapshot_model_file,
            MODEL_PT_SHA256,
            revision=MODEL_REVISION,
            filename="model.pt",
        )
        candidates = (
            (app_model_path, app_integrity_state, app_model_size),
            (
                snapshot_model_file,
                snapshot_integrity_state,
                snapshot_model_file.stat().st_size if snapshot_model_file.is_file() else None,
            ),
        )
        selected = next(
            (
                candidate
                for state in (
                    INTEGRITY_STATE_VERIFIED,
                    INTEGRITY_STATE_NOT_CHECKED,
                    INTEGRITY_STATE_MISMATCH,
                    INTEGRITY_STATE_UNREADABLE,
                )
                for candidate in candidates
                if candidate[1] == state
            ),
            None,
        )
        selected_path = selected[0] if selected is not None else None
        integrity_state = selected[1] if selected is not None else INTEGRITY_STATE_MISSING
        model_size = selected[2] if selected is not None else None
        missing = [name for name in MODEL_REQUIRED_CACHE_FILES if name != "model.pt" and not (snapshot / name).exists()]
        if integrity_state != INTEGRITY_STATE_VERIFIED:
            missing.append("model.pt")

        status.update(
            {
                "snapshot_path": str(snapshot),
                "partial": bool(missing) or active_download_size > 0,
                "downloaded": not missing,
                "model_file": str(selected_path) if selected_path is not None else "",
                "model_size": model_size,
                "model_size_label": format_bytes(model_size),
                "integrity_state": integrity_state,
                "missing_files": missing,
            }
        )
        return status
    return status


def get_hf_snapshot_status(
    model_id: str,
    repo_dir: str,
    required_files: list[str],
    *,
    revision: str | None = None,
    weight_filename: str | None = None,
    weight_sha256: str | None = None,
) -> dict[str, object]:
    repo_cache = get_hf_repo_cache_dir(repo_dir)
    snapshots_dir = repo_cache / "snapshots"
    active_download_size = get_active_hf_download_size(repo_dir)
    status: dict[str, object] = {
        "model_id": model_id,
        "revision": revision or "",
        "cache_root": str(repo_cache),
        "snapshot_path": "",
        "downloaded": False,
        "partial": False,
        "integrity_algorithm": "sha256" if weight_sha256 else "",
        "integrity_state": INTEGRITY_STATE_MISSING if weight_sha256 else INTEGRITY_STATE_NOT_CHECKED,
        "model_size": None,
        "model_size_label": format_bytes(None),
        "active_download_size": active_download_size,
        "active_download_size_label": format_bytes(active_download_size),
        "missing_files": required_files.copy(),
    }
    if not snapshots_dir.exists():
        return status

    snapshots = _snapshot_candidates(snapshots_dir, revision)
    for snapshot in snapshots:
        missing = [name for name in required_files if not (snapshot / name).exists()]
        if weight_filename is not None:
            model_file = snapshot / weight_filename
        else:
            model_file = next(
                (
                    path
                    for path in (
                        snapshot / "model.safetensors",
                        snapshot / "pytorch_model.bin",
                    )
                    if path.exists()
                ),
                None,
            )
        integrity_state = INTEGRITY_STATE_NOT_CHECKED
        if weight_sha256 is not None and weight_filename is not None:
            integrity_state = cached_file_integrity_state(
                snapshot / weight_filename,
                weight_sha256,
                revision=revision or "",
                filename=weight_filename,
            )
            if integrity_state != INTEGRITY_STATE_VERIFIED and weight_filename not in missing:
                missing.append(weight_filename)
        if model_file is not None and not model_file.is_file():
            model_file = None
        size = model_file.stat().st_size if model_file is not None else None
        status.update(
            {
                "snapshot_path": str(snapshot),
                "downloaded": not missing,
                "partial": bool(missing) or bool(status["active_download_size"]),
                "integrity_state": integrity_state,
                "model_file": str(model_file) if model_file is not None else "",
                "model_size": size,
                "model_size_label": format_bytes(size),
                "missing_files": missing,
            }
        )
        return status
    return status


def get_clip_reference_cache_status() -> dict[str, object]:
    return get_hf_snapshot_status(
        CLIP_REFERENCE_MODEL_ID,
        CLIP_REFERENCE_MODEL_REPO_DIR,
        CLIP_REFERENCE_REQUIRED_CACHE_FILES,
        revision=CLIP_REFERENCE_MODEL_REVISION,
        weight_filename=CLIP_REFERENCE_WEIGHT_FILENAME,
        weight_sha256=CLIP_REFERENCE_WEIGHT_SHA256,
    )


def get_model_assets_dir() -> Path:
    status = get_model_cache_status()
    snapshot_path = str(status.get("snapshot_path") or "")
    if not snapshot_path:
        raise TranslatableRuntimeError("error.modelAssetsNotReady", fallback="模型配置文件未准备好，请先完成模型准备。")
    path = Path(snapshot_path)
    if not path.exists():
        raise TranslatableRuntimeError(
            "error.modelAssetsDirMissing", fallback=f"模型配置目录不存在：{path}", path=str(path)
        )
    return path


def get_active_model_download_size() -> int:
    app_part_path = get_app_model_part_path()
    if app_part_path.exists():
        return app_part_path.stat().st_size

    return get_active_hf_download_size(MODEL_CACHE_REPO_DIR)


def get_active_hf_download_size(repo_dir: str) -> int:
    repo_cache = get_hf_repo_cache_dir(repo_dir)
    blobs_dir = repo_cache / "blobs"
    if not blobs_dir.exists():
        return 0

    sizes = []
    for path in blobs_dir.glob("*.incomplete"):
        try:
            sizes.append(path.stat().st_size)
        except OSError:
            continue
    return max(sizes, default=0)


def request_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"User-Agent": "culvia-local/1.0"}
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra:
        headers.update(extra)
    return headers


def download_model_pt_with_progress(
    stage: int,
    total: int,
    progress_callback: ModelDownloadCallback | None = None,
) -> str:
    model_path = get_app_model_path()
    part_path = get_app_model_part_path()
    model_path.parent.mkdir(parents=True, exist_ok=True)

    if model_path.exists() and model_path.stat().st_size > 0:
        try:
            verify_file_sha256(
                model_path,
                MODEL_PT_SHA256,
                filename="model.pt",
                revision=MODEL_REVISION,
            )
        except TranslatableRuntimeError:
            model_path.unlink(missing_ok=True)
        else:
            if progress_callback is not None:
                status = get_model_cache_status()
                progress_callback("model.pt", stage, total, "cached", status)
            return str(model_path)

    url = hf_hub_url(repo_id=MODEL_ID, filename="model.pt", revision=MODEL_REVISION)
    resume_from = part_path.stat().st_size if part_path.exists() else 0
    headers = request_headers({"Range": f"bytes={resume_from}-"} if resume_from else None)

    if progress_callback is not None:
        status = get_model_cache_status()
        progress_callback("model.pt", stage, total, "connecting", status)

    response = requests.get(url, headers=headers, stream=True, timeout=(15, 120), allow_redirects=True)
    if response.status_code == 416:
        part_path.unlink(missing_ok=True)
        _remove_integrity_marker(part_path)
        resume_from = 0
        response = requests.get(url, headers=request_headers(), stream=True, timeout=(15, 120), allow_redirects=True)
    elif response.status_code != 206 and resume_from:
        part_path.unlink(missing_ok=True)
        _remove_integrity_marker(part_path)
        resume_from = 0
        response = requests.get(url, headers=request_headers(), stream=True, timeout=(15, 120), allow_redirects=True)

    response.raise_for_status()
    content_length = int(response.headers.get("content-length") or 0)
    expected_size = resume_from + content_length if content_length else None
    downloaded = resume_from
    last_update = 0.0
    started_at = time.monotonic()

    if progress_callback is not None:
        status = get_model_cache_status()
        status["active_download_size"] = downloaded
        status["active_download_size_label"] = format_bytes(downloaded)
        status["expected_size"] = expected_size
        status["expected_size_label"] = format_bytes(expected_size)
        status["download_fraction"] = (downloaded / expected_size) if expected_size else None
        status["download_percent_label"] = f"{(downloaded / expected_size) * 100:.1f}%" if expected_size else "准备中"
        status["speed_bps"] = 0
        status["speed_label"] = "等待数据"
        status["eta_seconds"] = None
        status["eta_label"] = "计算中"
        progress_callback("model.pt", stage, total, "connected", status)

    with part_path.open("ab" if resume_from else "wb") as file:
        for chunk in response.iter_content(chunk_size=512 * 1024):
            if not chunk:
                continue
            file.write(chunk)
            downloaded += len(chunk)
            now = time.monotonic()
            if progress_callback is not None and now - last_update >= 0.2:
                elapsed = max(now - started_at, 0.001)
                speed_bps = max((downloaded - resume_from) / elapsed, 0)
                eta_seconds = None
                if expected_size and speed_bps > 0:
                    eta_seconds = (expected_size - downloaded) / speed_bps
                status = get_model_cache_status()
                status["active_download_size"] = downloaded
                status["active_download_size_label"] = format_bytes(downloaded)
                status["expected_size"] = expected_size
                status["expected_size_label"] = format_bytes(expected_size)
                status["download_fraction"] = (downloaded / expected_size) if expected_size else None
                status["download_percent_label"] = (
                    f"{(downloaded / expected_size) * 100:.1f}%" if expected_size else "准备中"
                )
                status["speed_bps"] = speed_bps
                status["speed_label"] = f"{format_bytes(speed_bps)}/s"
                status["eta_seconds"] = eta_seconds
                status["eta_label"] = format_duration(eta_seconds)
                progress_callback("model.pt", stage, total, "downloading", status)
                last_update = now

    try:
        verify_file_sha256(
            part_path,
            MODEL_PT_SHA256,
            filename="model.pt",
            revision=MODEL_REVISION,
        )
    except TranslatableRuntimeError:
        part_path.unlink(missing_ok=True)
        if resume_from:
            return download_model_pt_with_progress(stage, total, progress_callback)
        raise
    part_path.replace(model_path)
    _remove_integrity_marker(part_path)
    _record_verified_file_sha256(
        model_path,
        MODEL_PT_SHA256,
        revision=MODEL_REVISION,
        filename="model.pt",
    )
    if progress_callback is not None:
        status = get_model_cache_status()
        status["expected_size"] = expected_size
        status["expected_size_label"] = format_bytes(expected_size)
        status["download_fraction"] = 1.0
        status["download_percent_label"] = "100.0%"
        status["speed_label"] = "完成"
        status["eta_label"] = "0秒"
        progress_callback("model.pt", stage, total, "ready", status)
    return str(model_path)


def download_hf_file(
    filename: str,
    stage: int,
    total: int,
    progress_callback: ModelDownloadCallback | None = None,
) -> str:
    if filename == "model.pt":
        return download_model_pt_with_progress(stage, total, progress_callback)

    if progress_callback is None:
        return hf_hub_download(repo_id=MODEL_ID, filename=filename, revision=MODEL_REVISION)

    result: dict[str, str] = {}
    error: dict[str, BaseException] = {}

    def worker() -> None:
        try:
            result["path"] = hf_hub_download(repo_id=MODEL_ID, filename=filename, revision=MODEL_REVISION)
        except BaseException as exc:
            error["exc"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    while thread.is_alive():
        status = get_model_cache_status()
        active_size = get_active_model_download_size()
        status["active_download_size"] = active_size
        status["active_download_size_label"] = format_bytes(active_size)
        progress_callback(filename, stage, total, "downloading", status)
        time.sleep(1.0)

    thread.join()
    if error:
        raise error["exc"]

    status = get_model_cache_status()
    status["active_download_size"] = get_active_model_download_size()
    status["active_download_size_label"] = format_bytes(status["active_download_size"])
    progress_callback(filename, stage, total, "ready", status)
    return result["path"]


def download_hf_repo_file(
    model_id: str,
    repo_dir: str,
    required_files: list[str],
    filename: str,
    stage: int,
    total: int,
    progress_callback: ModelDownloadCallback | None = None,
    *,
    revision: str,
    force_download: bool = False,
) -> str:
    if progress_callback is None:
        return hf_hub_download(
            repo_id=model_id,
            filename=filename,
            revision=revision,
            force_download=force_download,
        )

    result: dict[str, str] = {}
    error: dict[str, BaseException] = {}

    def worker() -> None:
        try:
            result["path"] = hf_hub_download(
                repo_id=model_id,
                filename=filename,
                revision=revision,
                force_download=force_download,
            )
        except BaseException as exc:
            error["exc"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    while thread.is_alive():
        status = get_hf_snapshot_status(model_id, repo_dir, required_files, revision=revision)
        progress_callback(filename, stage, total, "downloading", status)
        time.sleep(1.0)

    thread.join()
    if error:
        raise error["exc"]

    status = get_hf_snapshot_status(model_id, repo_dir, required_files, revision=revision)
    progress_callback(filename, stage, total, "ready", status)
    return result["path"]


def ensure_model_files(progress_callback: ModelDownloadCallback | None = None) -> None:
    sanitize_proxy_env_for_httpx()
    total = len(MODEL_REQUIRED_CACHE_FILES)

    for stage, filename in enumerate(MODEL_REQUIRED_CACHE_FILES, start=1):
        status = get_model_cache_status()
        missing = set(status.get("missing_files") or [])
        verified_cached_model = False
        if filename == "model.pt":
            for _candidate in range(2):
                if status.get("integrity_state") != INTEGRITY_STATE_NOT_CHECKED or not status.get("model_file"):
                    break
                try:
                    verify_file_sha256(
                        str(status["model_file"]),
                        MODEL_PT_SHA256,
                        filename=filename,
                        revision=MODEL_REVISION,
                    )
                except TranslatableRuntimeError:
                    status = get_model_cache_status()
                    missing = set(status.get("missing_files") or [])
                else:
                    verified_cached_model = True
                    if progress_callback is not None:
                        progress_callback(filename, stage, total, "cached", get_model_cache_status())
                    break
        if verified_cached_model:
            continue
        if filename not in missing:
            if progress_callback is not None:
                progress_callback(filename, stage, total, "cached", status)
            continue

        if progress_callback is not None:
            progress_callback(filename, stage, total, "starting", status)
        download_hf_file(filename, stage, total, progress_callback)


def ensure_clip_reference_model_files(progress_callback: ModelDownloadCallback | None = None) -> None:
    sanitize_proxy_env_for_httpx()
    total = len(CLIP_REFERENCE_REQUIRED_CACHE_FILES)

    for stage, filename in enumerate(CLIP_REFERENCE_REQUIRED_CACHE_FILES, start=1):
        status = get_clip_reference_cache_status()
        missing = set(status.get("missing_files") or [])
        if (
            filename == CLIP_REFERENCE_WEIGHT_FILENAME
            and status.get("integrity_state") == INTEGRITY_STATE_NOT_CHECKED
            and status.get("model_file")
        ):
            try:
                verify_file_sha256(
                    str(status["model_file"]),
                    CLIP_REFERENCE_WEIGHT_SHA256,
                    filename=filename,
                    revision=CLIP_REFERENCE_MODEL_REVISION,
                )
            except TranslatableRuntimeError:
                status = get_clip_reference_cache_status()
            else:
                if progress_callback is not None:
                    progress_callback(filename, stage, total, "cached", get_clip_reference_cache_status())
                continue
        needs_download = filename in missing
        force_download = filename == CLIP_REFERENCE_WEIGHT_FILENAME and status.get("integrity_state") in {
            INTEGRITY_STATE_MISMATCH,
            INTEGRITY_STATE_UNREADABLE,
        }

        if not needs_download:
            if progress_callback is not None:
                progress_callback(filename, stage, total, "cached", status)
            continue

        if progress_callback is not None:
            progress_callback(filename, stage, total, "starting", status)
        downloaded_path = download_hf_repo_file(
            CLIP_REFERENCE_MODEL_ID,
            CLIP_REFERENCE_MODEL_REPO_DIR,
            CLIP_REFERENCE_REQUIRED_CACHE_FILES,
            filename,
            stage,
            total,
            progress_callback,
            revision=CLIP_REFERENCE_MODEL_REVISION,
            force_download=force_download,
        )
        if filename == CLIP_REFERENCE_WEIGHT_FILENAME:
            verify_file_sha256(
                downloaded_path,
                CLIP_REFERENCE_WEIGHT_SHA256,
                filename=filename,
                revision=CLIP_REFERENCE_MODEL_REVISION,
            )
