from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


DEFAULT_CACHE_SUFFIXES = (".sqlite", ".sqlite3", ".db")
SOURCE_MODES = ("folders", "uploads")


@dataclass(frozen=True)
class SourceRequest:
    mode: str
    folders: list[str]
    cache_path: str
    uploaded_paths: list[object]


def normalize_source_mode(value: object) -> str:
    mode = str(value or "").strip()
    return mode if mode in SOURCE_MODES else "folders"


def normalize_source_folders(value: object) -> list[str]:
    if isinstance(value, (str, bytes)) or value is None:
        items: Iterable[object] = str(value).splitlines() if value else []
    else:
        try:
            items = list(value)  # type: ignore[arg-type]
        except TypeError:
            items = [value]

    folders: list[str] = []
    seen: set[str] = set()
    for item in items:
        folder = str(item or "").strip()
        if not folder or folder in seen:
            continue
        folders.append(folder)
        seen.add(folder)
    return folders


def normalize_uploaded_path_values(value: object) -> list[object]:
    if isinstance(value, (str, bytes)) or value is None:
        return [value] if value else []
    try:
        return list(value)  # type: ignore[arg-type]
    except TypeError:
        return [value]


def normalize_cache_path(
    value: object,
    *,
    default_cache_path: str | Path,
    allowed_suffixes: Iterable[str] = DEFAULT_CACHE_SUFFIXES,
) -> str:
    cache_path = str(value or default_cache_path).strip() or str(default_cache_path)
    suffix = Path(cache_path).expanduser().suffix.lower()
    allowed = {item.lower() for item in allowed_suffixes}
    if suffix not in allowed:
        raise ValueError("评分记录路径只支持 SQLite 文件。")
    return cache_path


def source_request_from_payload(
    payload: Mapping[str, object],
    *,
    default_cache_path: str | Path,
    allowed_cache_suffixes: Iterable[str] = DEFAULT_CACHE_SUFFIXES,
) -> SourceRequest:
    return SourceRequest(
        mode=normalize_source_mode(payload.get("mode")),
        folders=normalize_source_folders(payload.get("folders")),
        cache_path=normalize_cache_path(
            payload.get("cachePath"),
            default_cache_path=default_cache_path,
            allowed_suffixes=allowed_cache_suffixes,
        ),
        uploaded_paths=normalize_uploaded_path_values(payload.get("uploadedPaths")),
    )
