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
from culvia.runtime_config import RuntimeConfig
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
    scores_df = load_scores(config.default_cache_path)
    source_config = dict(load_source_config(config.default_cache_path) if load_source_config else {})
    default_photo_dirs = source_config["folders"] if "folders" in source_config else config.default_photo_dirs
    state = create_initial_state(
        scores_df=scores_df,
        default_photo_dirs=default_photo_dirs,
        default_cache_path=str(source_config.get("cachePath") or config.default_cache_path),
        filter_defaults=filter_defaults,
        default_selected_models=default_selected_models,
    )
    if source_config.get("mode"):
        state["source"]["mode"] = str(source_config["mode"])
        state["sourcePreview"]["mode"] = str(source_config["mode"])
    return AppStateStore(state)


def create_web_app(
    handlers: WebRouteHandlers,
    *,
    config: RuntimeConfig,
    state_store: AppStateStore,
    job_service: ScoringJobService | None = None,
    debug: bool = False,
) -> Starlette:
    app = Starlette(debug=debug, routes=create_web_routes(handlers, config), lifespan=app_lifespan)
    app.state.app_state_store = state_store
    app.state.job_service = job_service or ScoringJobService(state_store)
    app.state.runtime_config = config
    app.state.export_receipts = ExportReceiptStore(config.resolved_export_receipts_path)
    return app
