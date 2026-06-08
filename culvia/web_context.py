from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pandas as pd

from culvia.app_state import AppStateStore
from culvia.job_service import ScoringJobService
from culvia.media_service import resolve_media_path
from culvia.runtime_config import RuntimeConfig


NormalizeDataFrame = Callable[[pd.DataFrame], pd.DataFrame]


def request_runtime_config(request: object, fallback: RuntimeConfig) -> RuntimeConfig:
    app = getattr(request, "app", None)
    state = getattr(app, "state", None)
    runtime_config = getattr(state, "runtime_config", None)
    return runtime_config if isinstance(runtime_config, RuntimeConfig) else fallback


def request_state_store(request: object, fallback: AppStateStore) -> AppStateStore:
    app = getattr(request, "app", None)
    state = getattr(app, "state", None)
    store = getattr(state, "app_state_store", None)
    return store if isinstance(store, AppStateStore) else fallback


def request_job_service(request: object, fallback: ScoringJobService) -> ScoringJobService:
    app = getattr(request, "app", None)
    state = getattr(app, "state", None)
    service = getattr(state, "job_service", None)
    return service if isinstance(service, ScoringJobService) else fallback


def media_path_from_request(
    request: object,
    *,
    fallback_state_store: AppStateStore,
    fallback_runtime_config: RuntimeConfig,
    normalize_dataframe: NormalizeDataFrame,
    state_store: AppStateStore | None = None,
) -> tuple[Path | None, int]:
    store = state_store or request_state_store(request, fallback_state_store)
    with store.lock:
        state = store.data
        source = dict(state.get("source", {}))
        scores_df = normalize_dataframe(state["scores_df"]).copy()

    query_params = getattr(request, "query_params", {})
    runtime_config = request_runtime_config(request, fallback_runtime_config)
    return resolve_media_path(
        file_id=str(query_params.get("file_id") or "").strip(),
        path_text=str(query_params.get("path") or "").strip(),
        source=source,
        scores_df=scores_df,
        upload_cache_dir=runtime_config.upload_cache_dir,
    )


def path_from_query(
    request: object,
    *,
    fallback_state_store: AppStateStore,
    fallback_runtime_config: RuntimeConfig,
    normalize_dataframe: NormalizeDataFrame,
    state_store: AppStateStore | None = None,
) -> Path | None:
    path, status_code = media_path_from_request(
        request,
        fallback_state_store=fallback_state_store,
        fallback_runtime_config=fallback_runtime_config,
        normalize_dataframe=normalize_dataframe,
        state_store=state_store,
    )
    return path if status_code == 200 else None
