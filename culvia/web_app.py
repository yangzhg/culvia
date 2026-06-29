from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from starlette.applications import Starlette
from starlette.routing import BaseRoute

from culvia.app_state import AppStateStore, create_initial_state
from culvia.job_service import ScoringJobService
from culvia.runtime_config import RuntimeConfig
from culvia.web_routes import WebRouteHandlers, build_routes


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
    app = Starlette(debug=debug, routes=create_web_routes(handlers, config))
    app.state.app_state_store = state_store
    app.state.job_service = job_service or ScoringJobService(state_store)
    app.state.runtime_config = config
    return app
