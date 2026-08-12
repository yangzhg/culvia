from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

import pandas as pd

from culvia.path_semantics import is_same_or_child_path, path_identity_key, stable_path


@dataclass(frozen=True)
class MediaCatalogSnapshot:
    revision: int
    by_file_id: Mapping[str, str]
    scored_paths_by_key: Mapping[str, tuple[str, ...]]
    source_mode: str
    folder_roots: tuple[str, ...]
    uploaded_paths_by_key: Mapping[str, tuple[str, ...]]


def build_media_catalog(
    scores: object,
    source: Mapping[str, object] | None,
    *,
    revision: int,
) -> MediaCatalogSnapshot:
    by_file_id: dict[str, str] = {}
    scored_paths_by_key: dict[str, dict[str, None]] = {}
    frame = scores if isinstance(scores, pd.DataFrame) else pd.DataFrame(scores)
    if "path" in frame.columns:
        file_ids = frame["file_id"] if "file_id" in frame.columns else pd.Series("", index=frame.index)
        for raw_file_id, raw_path in zip(file_ids.tolist(), frame["path"].tolist(), strict=False):
            file_id = _text_value(raw_file_id)
            path_text = _text_value(raw_path)
            if file_id and file_id not in by_file_id:
                by_file_id[file_id] = path_text
            if not path_text:
                continue
            if path_key := _safe_identity_key(path_text):
                scored_paths_by_key.setdefault(path_key, {}).setdefault(path_text, None)

    source_payload = dict(source or {})
    mode = str(source_payload.get("mode") or "folders")
    folder_roots = tuple(
        dict.fromkeys(os.fspath(stable_path(value)) for value in _source_paths(source_payload.get("folders")))
    )
    uploaded_paths_by_key: dict[str, dict[str, None]] = {}
    for value in _source_paths(source_payload.get("uploadedPaths")):
        if key := _safe_identity_key(value):
            uploaded_paths_by_key.setdefault(key, {}).setdefault(value, None)
    return MediaCatalogSnapshot(
        revision=revision,
        by_file_id=MappingProxyType(by_file_id),
        scored_paths_by_key=_freeze_path_candidates(scored_paths_by_key),
        source_mode=mode,
        folder_roots=folder_roots,
        uploaded_paths_by_key=_freeze_path_candidates(uploaded_paths_by_key),
    )


def resolve_catalog_media_path(
    catalog: MediaCatalogSnapshot,
    *,
    file_id: str,
    path_text: str,
    upload_cache_dir: Path,
) -> tuple[Path | None, int]:
    requested_file_id = str(file_id or "").strip()
    requested_path = str(path_text or "").strip()
    matched_score = False
    if requested_file_id:
        if requested_file_id in catalog.by_file_id:
            requested_path = catalog.by_file_id[requested_file_id]
            matched_score = True

    if not requested_path:
        return None, 404
    try:
        path = Path(requested_path).expanduser().resolve()
    except Exception:
        return None, 404
    if not path.exists() or not path.is_file():
        return None, 404
    if matched_score or catalog_allows_path(catalog, path, upload_cache_dir=upload_cache_dir):
        return path, 200
    return None, 403


def catalog_allows_path(
    catalog: MediaCatalogSnapshot,
    path: Path,
    *,
    upload_cache_dir: Path,
) -> bool:
    path_key = _safe_identity_key(path)
    if not path_key:
        return False
    if _candidate_still_matches(catalog.scored_paths_by_key.get(path_key, ()), path_key):
        return True
    if catalog.source_mode == "uploads":
        upload_root_key = _safe_identity_key(upload_cache_dir)
        return bool(
            upload_root_key
            and _candidate_still_matches(catalog.uploaded_paths_by_key.get(path_key, ()), path_key)
            and _key_is_same_or_child(path_key, upload_root_key)
        )
    return any(_safe_is_same_or_child(path, root) for root in catalog.folder_roots)


def _source_paths(value: object) -> list[str]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes)):
        value = [value] if value else []
    return [text for item in value if (text := _text_value(item))]


def _text_value(value: object) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _key_is_same_or_child(child_key: str, parent_key: str) -> bool:
    if child_key == parent_key:
        return True
    try:
        Path(child_key).relative_to(Path(parent_key))
        return True
    except ValueError:
        return child_key.startswith(parent_key.rstrip(os.sep) + os.sep)


def _safe_identity_key(value: str | Path) -> str:
    try:
        return path_identity_key(value)
    except Exception:
        return ""


def _freeze_path_candidates(values: Mapping[str, Mapping[str, None]]) -> Mapping[str, tuple[str, ...]]:
    return MappingProxyType({key: tuple(paths) for key, paths in values.items()})


def _candidate_still_matches(candidates: Iterable[str], expected_key: str) -> bool:
    return any(_safe_identity_key(candidate) == expected_key for candidate in candidates)


def _safe_is_same_or_child(child: str | Path, parent: str | Path) -> bool:
    try:
        return is_same_or_child_path(child, parent)
    except Exception:
        return False
