from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from culvia.app_state import AppStateStore
from culvia.media_service import path_is_inside as default_path_is_inside
from culvia.source_requests import SourceRequest, source_request_from_payload


@dataclass(frozen=True)
class SourceCacheDependencies:
    default_cache_path: str | Path
    load_cache_records: Callable[[str | Path], pd.DataFrame]
    path_is_inside: Callable[[str, Iterable[str]], bool] = default_path_is_inside


@dataclass(frozen=True)
class SourceCacheResult:
    request: SourceRequest
    scores_df: pd.DataFrame


def filter_cache_to_folders(
    df: pd.DataFrame,
    folders: list[str],
    *,
    path_matcher: Callable[[str, Iterable[str]], bool] = default_path_is_inside,
) -> pd.DataFrame:
    if df.empty or not folders:
        return df
    mask = df["path"].fillna("").astype(str).map(lambda value: path_matcher(value, folders))
    return df[mask].copy()


def load_source_cache_action(
    payload: Mapping[str, object],
    dependencies: SourceCacheDependencies,
) -> SourceCacheResult:
    source_request = source_request_from_payload(
        payload,
        default_cache_path=dependencies.default_cache_path,
    )
    loaded = dependencies.load_cache_records(source_request.cache_path)
    if source_request.mode == "folders":
        loaded = filter_cache_to_folders(
            loaded,
            source_request.folders,
            path_matcher=dependencies.path_is_inside,
        )
    return SourceCacheResult(request=source_request, scores_df=loaded)


def apply_source_cache_state(state_store: AppStateStore, result: SourceCacheResult) -> None:
    source_request = result.request
    with state_store.lock:
        state_store.data["scores_df"] = result.scores_df
        state_store.data["source"].update(
            {
                "mode": source_request.mode,
                "folders": source_request.folders,
                "cachePath": source_request.cache_path,
            }
        )
