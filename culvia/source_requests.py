from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from culvia.path_semantics import is_same_or_child_path, path_identity_key, stable_path

from culvia.job_text import TranslatableValueError


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


def _source_path_key(path: Path) -> str:
    return path_identity_key(path)


def _normalized_source_path(value: object) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    expanded = os.path.expandvars(os.path.expanduser(raw.replace("\\", os.sep)))
    return stable_path(expanded)


def _is_relative_to(child: Path, parent: Path) -> bool:
    return is_same_or_child_path(child, parent)


def normalize_source_folders(value: object) -> list[str]:
    if isinstance(value, (str, bytes)) or value is None:
        items: Iterable[object] = str(value).splitlines() if value else []
    else:
        try:
            items = list(value)  # type: ignore[arg-type]
        except TypeError:
            items = [value]

    paths: list[Path] = []
    seen: set[str] = set()
    for item in items:
        path = _normalized_source_path(item)
        if path is None:
            continue
        key = _source_path_key(path)
        if key in seen:
            continue
        paths.append(path)
        seen.add(key)

    pruned = [
        path
        for index, path in enumerate(paths)
        if not any(index != other_index and _is_relative_to(path, other) for other_index, other in enumerate(paths))
    ]
    return [str(path) for path in pruned]


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
        raise TranslatableValueError("error.cachePathNotSqlite", fallback="评分记录路径只支持 SQLite 文件。")
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
