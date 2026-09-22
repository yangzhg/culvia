from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any

from starlette.applications import Starlette
from starlette.routing import BaseRoute

from culvia.app_state import AppStateStore, create_initial_state
from culvia.export_receipts import ExportReceiptError, ExportReceiptStore
from culvia.job_service import ScoringJobService
from culvia.path_semantics import is_same_or_child_path
from culvia.runtime_config import RuntimeConfig
from culvia.source_requests import source_request_from_payload
from culvia.source_service import filter_cache_to_folders
from culvia.web_routes import WebRouteHandlers, build_routes


def close_app_thumbnail_coordinator(app: Starlette) -> None:
    coordinator = getattr(app.state, "thumbnail_coordinator", None)
    close = getattr(coordinator, "close", None)
    if callable(close):
        close()


def start_app_thumbnail_coordinator(app: Starlette) -> None:
    coordinator = getattr(app.state, "thumbnail_coordinator", None)
    runtime_config = getattr(app.state, "runtime_config", None)
    start = getattr(coordinator, "start", None)
    cache_dir = getattr(runtime_config, "thumbnail_cache_dir", None)
    if callable(start) and cache_dir is not None:
        start(cache_dir)


@asynccontextmanager
async def app_lifespan(app: Starlette):
    start_app_thumbnail_coordinator(app)
    receipts = getattr(app.state, "export_receipts", None)
    if receipts is not None:
        try:
            await asyncio.to_thread(receipts.recover_interrupted)
        except ExportReceiptError as error:
            app.state.export_receipt_recovery_error = error
    try:
        restore_source = getattr(app.state, "restore_source", None)
        if restore_source is not None:
            restore_source(app.state.app_state_store, app.state.job_service)
        yield
    finally:
        await asyncio.to_thread(close_app_thumbnail_coordinator, app)


def create_web_routes(handlers: WebRouteHandlers, config: RuntimeConfig) -> list[BaseRoute]:
    return build_routes(handlers, web_dir=config.web_dir)


def create_runtime_state_store(
    config: RuntimeConfig,
    *,
    load_scores: Callable[[str], Any],
    load_source_config: Callable[[str], Mapping[str, Any]] | None = None,
    filter_defaults: Mapping[str, Any],
    default_selected_models: Sequence[str],
) -> AppStateStore:
    source_config = dict(load_source_config(config.default_cache_path) if load_source_config else {})
    default_photo_dirs = source_config["folders"] if "folders" in source_config else config.default_photo_dirs
    source = source_request_from_payload(
        {
            "mode": source_config.get("mode"),
            "folders": default_photo_dirs,
            "cachePath": source_config.get("cachePath") or config.default_cache_path,
        },
        default_cache_path=config.default_cache_path,
    )
    scores_df = load_scores(source.cache_path)
    if source.mode == "folders" and source.folders and "path" in scores_df.columns:
        scores_df = filter_cache_to_folders(
            scores_df,
            source.folders,
            path_matcher=lambda path, folders: (
                bool(path) and any(is_same_or_child_path(path, folder) for folder in folders)
            ),
        )
    else:
        scores_df = scores_df.iloc[:0].copy()
    state = create_initial_state(
        scores_df=scores_df,
        default_photo_dirs=source.folders,
        default_cache_path=source.cache_path,
        filter_defaults=filter_defaults,
        default_selected_models=default_selected_models,
    )
    state["source"]["mode"] = source.mode
    state["sourcePreview"]["mode"] = source.mode
    return AppStateStore(state)


def create_web_app(
    handlers: WebRouteHandlers,
    *,
    config: RuntimeConfig,
    state_store: AppStateStore,
    job_service: ScoringJobService | None = None,
    restore_source: Callable[[AppStateStore, ScoringJobService], None] | None = None,
    debug: bool = False,
) -> Starlette:
    app = Starlette(debug=debug, routes=create_web_routes(handlers, config), lifespan=app_lifespan)
    app.state.app_state_store = state_store
    app.state.job_service = job_service or ScoringJobService(state_store)
    app.state.restore_source = restore_source
    app.state.runtime_config = config
    app.state.export_receipts = ExportReceiptStore(config.resolved_export_receipts_path)
    return app
