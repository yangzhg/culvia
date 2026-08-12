from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from culvia.app_state import AppStateStore
from culvia.job_service import ScoringJobService
from culvia.media_catalog import resolve_catalog_media_path
from culvia.runtime_config import RuntimeConfig


NormalizeDataFrame = Callable[[object], object]


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
    del normalize_dataframe
    store = state_store or request_state_store(request, fallback_state_store)
    query_params = getattr(request, "query_params", {})
    runtime_config = request_runtime_config(request, fallback_runtime_config)
    return resolve_catalog_media_path(
        store.media_catalog_snapshot(),
        file_id=str(query_params.get("file_id") or "").strip(),
        path_text=str(query_params.get("path") or "").strip(),
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
