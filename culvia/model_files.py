from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

import requests
from huggingface_hub import hf_hub_download, hf_hub_url

from culvia.settings import rsinema_model_cache_dir


MODEL_ID = "rsinema/aesthetic-scorer"
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
CLIP_REFERENCE_MODEL_REPO_DIR = "models--openai--clip-vit-base-patch32"
CLIP_REFERENCE_REQUIRED_CACHE_FILES = [
    "config.json",
    "preprocessor_config.json",
    "tokenizer_config.json",
    "vocab.json",
    "merges.txt",
    "pytorch_model.bin",
]

ModelDownloadCallback = Callable[[str, int, int, str, dict[str, object]], None]


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
    if size is None:
        return "未知"
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


def get_model_cache_status() -> dict[str, object]:
    repo_cache = get_hf_repo_cache_dir(MODEL_CACHE_REPO_DIR)
    snapshots_dir = repo_cache / "snapshots"
    app_model_path = get_app_model_path()
    app_part_path = get_app_model_part_path()
    app_model_exists = app_model_path.exists()
    app_model_size = app_model_path.stat().st_size if app_model_exists else None
    active_download_size = app_part_path.stat().st_size if app_part_path.exists() else 0
    status: dict[str, object] = {
        "model_id": MODEL_ID,
        "cache_root": str(repo_cache),
        "app_cache_root": str(APP_MODEL_CACHE_DIR),
        "snapshot_path": "",
        "downloaded": False,
        "partial": False,
        "model_file": str(app_model_path) if app_model_exists else "",
        "model_size": app_model_size,
        "model_size_label": format_bytes(app_model_size),
        "active_download_size": active_download_size,
        "active_download_size_label": format_bytes(active_download_size),
        "missing_files": MODEL_REQUIRED_CACHE_FILES.copy(),
    }

    if not snapshots_dir.exists():
        return status

    snapshots = sorted(
        [path for path in snapshots_dir.iterdir() if path.is_dir()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for snapshot in snapshots:
        missing = []
        for name in MODEL_REQUIRED_CACHE_FILES:
            if name == "model.pt":
                if not app_model_exists and not (snapshot / name).exists():
                    missing.append(name)
            elif not (snapshot / name).exists():
                missing.append(name)

        snapshot_model_file = snapshot / "model.pt"
        if not app_model_exists and snapshot_model_file.exists():
            size = snapshot_model_file.stat().st_size
            status.update(
                {
                    "model_file": str(snapshot_model_file),
                    "model_size": size,
                    "model_size_label": format_bytes(size),
                }
            )

        status.update(
            {
                "snapshot_path": str(snapshot),
                "partial": bool(missing) or active_download_size > 0,
                "downloaded": not missing,
                "missing_files": missing,
            }
        )
        return status

    if snapshots:
        snapshot = snapshots[0]
        missing = []
        for name in MODEL_REQUIRED_CACHE_FILES:
            if name == "model.pt":
                if not app_model_exists and not (snapshot / name).exists():
                    missing.append(name)
            elif not (snapshot / name).exists():
                missing.append(name)
        status.update(
            {
                "snapshot_path": str(snapshot),
                "partial": True,
                "missing_files": missing,
            }
        )
    return status


def get_hf_snapshot_status(
    model_id: str,
    repo_dir: str,
    required_files: list[str],
) -> dict[str, object]:
    repo_cache = get_hf_repo_cache_dir(repo_dir)
    snapshots_dir = repo_cache / "snapshots"
    active_download_size = get_active_hf_download_size(repo_dir)
    status: dict[str, object] = {
        "model_id": model_id,
        "cache_root": str(repo_cache),
        "snapshot_path": "",
        "downloaded": False,
        "partial": False,
        "model_size": None,
        "model_size_label": "未知",
        "active_download_size": active_download_size,
        "active_download_size_label": format_bytes(active_download_size),
        "missing_files": required_files.copy(),
    }
    if not snapshots_dir.exists():
        return status

    snapshots = sorted(
        [path for path in snapshots_dir.iterdir() if path.is_dir()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for snapshot in snapshots:
        missing = [name for name in required_files if not (snapshot / name).exists()]
        model_files = [
            snapshot / "model.safetensors",
            snapshot / "pytorch_model.bin",
        ]
        size = sum(path.stat().st_size for path in model_files if path.exists())
        status.update(
            {
                "snapshot_path": str(snapshot),
                "downloaded": not missing,
                "partial": bool(missing) or bool(status["active_download_size"]),
                "model_size": size or None,
                "model_size_label": format_bytes(size or None),
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
    )


def get_model_assets_dir() -> Path:
    status = get_model_cache_status()
    snapshot_path = str(status.get("snapshot_path") or "")
    if not snapshot_path:
        raise RuntimeError("模型配置文件未准备好，请先完成模型准备。")
    path = Path(snapshot_path)
    if not path.exists():
        raise RuntimeError(f"模型配置目录不存在：{path}")
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
        if progress_callback is not None:
            status = get_model_cache_status()
            progress_callback("model.pt", stage, total, "cached", status)
        return str(model_path)

    url = hf_hub_url(repo_id=MODEL_ID, filename="model.pt")
    resume_from = part_path.stat().st_size if part_path.exists() else 0
    headers = request_headers({"Range": f"bytes={resume_from}-"} if resume_from else None)

    if progress_callback is not None:
        status = get_model_cache_status()
        progress_callback("model.pt", stage, total, "connecting", status)

    response = requests.get(url, headers=headers, stream=True, timeout=(15, 120), allow_redirects=True)
    if response.status_code == 416:
        part_path.unlink(missing_ok=True)
        resume_from = 0
        response = requests.get(url, headers=request_headers(), stream=True, timeout=(15, 120), allow_redirects=True)
    elif response.status_code != 206 and resume_from:
        part_path.unlink(missing_ok=True)
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

    part_path.replace(model_path)
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
        return hf_hub_download(repo_id=MODEL_ID, filename=filename)

    result: dict[str, str] = {}
    error: dict[str, BaseException] = {}

    def worker() -> None:
        try:
            result["path"] = hf_hub_download(repo_id=MODEL_ID, filename=filename)
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
) -> str:
    if progress_callback is None:
        return hf_hub_download(repo_id=model_id, filename=filename)

    result: dict[str, str] = {}
    error: dict[str, BaseException] = {}

    def worker() -> None:
        try:
            result["path"] = hf_hub_download(repo_id=model_id, filename=filename)
        except BaseException as exc:
            error["exc"] = exc

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    while thread.is_alive():
        status = get_hf_snapshot_status(model_id, repo_dir, required_files)
        progress_callback(filename, stage, total, "downloading", status)
        time.sleep(1.0)

    thread.join()
    if error:
        raise error["exc"]

    status = get_hf_snapshot_status(model_id, repo_dir, required_files)
    progress_callback(filename, stage, total, "ready", status)
    return result["path"]


def ensure_model_files(progress_callback: ModelDownloadCallback | None = None) -> None:
    sanitize_proxy_env_for_httpx()
    total = len(MODEL_REQUIRED_CACHE_FILES)

    for stage, filename in enumerate(MODEL_REQUIRED_CACHE_FILES, start=1):
        status = get_model_cache_status()
        missing = set(status.get("missing_files") or [])
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
        if filename not in missing:
            if progress_callback is not None:
                progress_callback(filename, stage, total, "cached", status)
            continue

        if progress_callback is not None:
            progress_callback(filename, stage, total, "starting", status)
        download_hf_repo_file(
            CLIP_REFERENCE_MODEL_ID,
            CLIP_REFERENCE_MODEL_REPO_DIR,
            CLIP_REFERENCE_REQUIRED_CACHE_FILES,
            filename,
            stage,
            total,
            progress_callback,
        )
