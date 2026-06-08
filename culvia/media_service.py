from __future__ import annotations

import hashlib
import io
from collections.abc import Iterable, Mapping
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd

from culvia.image_io import (
    bounded_image_cache_size,
    ensure_resized_image_cache,
    open_image_rgb,
    resized_image_cache_path,
)


def safe_uploaded_relative_path(name: str) -> Path:
    normalized = name.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part and part not in {".", ".."}]
    if not parts:
        parts = ["uploaded_image"]
    return Path(*parts)


def path_is_inside(path_text: str, folders: Iterable[str]) -> bool:
    try:
        path = Path(path_text).expanduser().resolve()
    except Exception:
        return False

    for folder in folders:
        try:
            root = Path(folder).expanduser().resolve()
            if path == root or root in path.parents:
                return True
        except Exception:
            continue
    return False


def is_inside_path(path: Path, root: Path) -> bool:
    try:
        resolved_path = path.expanduser().resolve()
        resolved_root = root.expanduser().resolve()
    except Exception:
        return False
    return resolved_path == resolved_root or resolved_root in resolved_path.parents


def is_allowed_media_path(
    path: Path,
    source: Mapping[str, object],
    scores_df: pd.DataFrame,
    *,
    upload_cache_dir: Path,
) -> bool:
    resolved_text = str(path.expanduser().resolve())
    if not scores_df.empty and "path" in scores_df.columns:
        for value in scores_df["path"].dropna().astype(str):
            try:
                if str(Path(value).expanduser().resolve()) == resolved_text:
                    return True
            except Exception:
                continue

    mode = str(source.get("mode") or "folders")
    if mode == "uploads":
        uploaded_paths = source.get("uploadedPaths", [])
        if not isinstance(uploaded_paths, Iterable) or isinstance(uploaded_paths, (str, bytes)):
            uploaded_paths = []
        for value in uploaded_paths:
            try:
                uploaded_path = Path(str(value)).expanduser().resolve()
            except Exception:
                continue
            if str(uploaded_path) == resolved_text and is_inside_path(uploaded_path, upload_cache_dir):
                return True
        return False

    raw_folders = source.get("folders", [])
    if not isinstance(raw_folders, Iterable) or isinstance(raw_folders, (str, bytes)):
        raw_folders = [raw_folders] if raw_folders else []
    folders = [str(item) for item in raw_folders if str(item).strip()]
    return bool(folders and path_is_inside(resolved_text, folders))


def resolve_media_path(
    *,
    file_id: str,
    path_text: str,
    source: Mapping[str, object],
    scores_df: pd.DataFrame,
    upload_cache_dir: Path,
) -> tuple[Path | None, int]:
    file_id = str(file_id or "").strip()
    path_text = str(path_text or "").strip()

    if file_id and not scores_df.empty and "file_id" in scores_df.columns:
        matches = scores_df[scores_df["file_id"].fillna("").astype(str) == file_id]
        if not matches.empty:
            path_text = str(matches.iloc[0].get("path") or "").strip()

    if not path_text:
        return None, 404
    try:
        path = Path(path_text).expanduser().resolve()
    except Exception:
        return None, 404
    if not path.exists() or not path.is_file():
        return None, 404
    if not is_allowed_media_path(path, source, scores_df, upload_cache_dir=upload_cache_dir):
        return None, 403
    return path, 200


def sanitize_uploaded_paths(paths: Iterable[object], *, upload_cache_dir: Path) -> list[Path]:
    allowed: list[Path] = []
    seen: set[str] = set()
    for item in paths:
        if not str(item).strip():
            continue
        try:
            path = Path(str(item)).expanduser().resolve()
        except Exception:
            continue
        path_text = str(path)
        if path_text in seen:
            continue
        if path.exists() and path.is_file() and is_inside_path(path, upload_cache_dir):
            allowed.append(path)
            seen.add(path_text)
    return allowed


def save_uploaded_bytes(
    *,
    filename: str,
    data: bytes,
    upload_cache_dir: Path,
    supported_extensions: Iterable[str],
) -> Path | None:
    relative_path = safe_uploaded_relative_path(filename or "uploaded_image")
    supported = {extension.lower() for extension in supported_extensions}
    if relative_path.suffix.lower() not in supported:
        return None

    digest = hashlib.sha256(data).hexdigest()[:16]
    target = upload_cache_dir / digest / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or target.stat().st_size != len(data):
        target.write_bytes(data)
    return target


def image_url(path: str, max_size: int) -> str:
    return f"/api/image?{urlencode({'path': path, 'max': str(max_size)})}"


def thumbnail_url(path: str, max_size: int) -> str:
    return f"/api/thumbnail?{urlencode({'path': path, 'max': str(max_size)})}"


def resized_jpeg_bytes(path: Path, max_size: int) -> bytes:
    bounded_size = bounded_image_cache_size(max_size, minimum=120, maximum=2200)
    image = open_image_rgb(path)
    image.thumbnail((bounded_size, bounded_size))
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=90, optimize=True)
    return output.getvalue()


def thumbnail_cache_path(path: Path, cache_dir: Path, max_size: int) -> Path:
    bounded_size = bounded_image_cache_size(max_size, minimum=80, maximum=900)
    return resized_image_cache_path(path, cache_dir, bounded_size)


def ensure_thumbnail_file(
    path: Path,
    cache_dir: Path,
    max_size: int,
    *,
    lock: object | None = None,
) -> Path:
    return ensure_resized_image_cache(
        path,
        cache_dir,
        max_size,
        minimum_size=80,
        maximum_size=900,
        quality=82,
        lock=lock,
    )
