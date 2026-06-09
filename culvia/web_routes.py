from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from starlette.routing import BaseRoute, Mount, Route
from starlette.responses import Response
from starlette.staticfiles import StaticFiles

RouteEndpoint = Callable[..., Any]


@dataclass(frozen=True)
class RouteSpec:
    path: str
    handler: str
    methods: tuple[str, ...] = ()


@dataclass(frozen=True)
class WebRouteHandlers:
    homepage: RouteEndpoint
    health: RouteEndpoint
    host_config: RouteEndpoint
    api_capabilities: RouteEndpoint
    api_state: RouteEndpoint
    api_filter: RouteEndpoint
    api_network: RouteEndpoint
    api_llm_config: RouteEndpoint
    api_llm_models: RouteEndpoint
    api_models: RouteEndpoint
    api_cache: RouteEndpoint
    api_source_preview: RouteEndpoint
    api_clear_history: RouteEndpoint
    api_clear_local_data: RouteEndpoint
    api_clear_model: RouteEndpoint
    api_upload: RouteEndpoint
    api_score: RouteEndpoint
    api_job_pause: RouteEndpoint
    api_job_resume: RouteEndpoint
    api_mark_photo: RouteEndpoint
    api_mark_color: RouteEndpoint
    api_mark_status: RouteEndpoint
    api_restore_marks: RouteEndpoint
    api_accept_marks: RouteEndpoint
    api_curation_history: RouteEndpoint
    api_curation_undo: RouteEndpoint
    api_image: RouteEndpoint
    api_thumbnail: RouteEndpoint
    api_export: RouteEndpoint
    api_export_selected_csv: RouteEndpoint
    api_export_preflight: RouteEndpoint
    api_export_selected: RouteEndpoint
    api_pick_folder: RouteEndpoint
    api_pick_folders: RouteEndpoint
    api_pick_export_folder: RouteEndpoint
    api_reveal: RouteEndpoint


APP_ROUTE_SPECS: tuple[RouteSpec, ...] = (
    RouteSpec("/", "homepage"),
    RouteSpec("/health", "health"),
    RouteSpec("/api/host-config", "host_config"),
    RouteSpec("/api/capabilities", "api_capabilities"),
    RouteSpec("/api/state", "api_state"),
    RouteSpec("/api/filter", "api_filter", ("POST",)),
    RouteSpec("/api/network", "api_network", ("POST",)),
    RouteSpec("/api/llm-config", "api_llm_config", ("POST",)),
    RouteSpec("/api/llm-models", "api_llm_models", ("POST",)),
    RouteSpec("/api/models", "api_models", ("POST",)),
    RouteSpec("/api/cache", "api_cache", ("POST",)),
    RouteSpec("/api/source/preview", "api_source_preview", ("POST",)),
    RouteSpec("/api/cache/clear", "api_clear_history", ("POST",)),
    RouteSpec("/api/data/clear", "api_clear_local_data", ("POST",)),
    RouteSpec("/api/model/clear", "api_clear_model", ("POST",)),
    RouteSpec("/api/upload", "api_upload", ("POST",)),
    RouteSpec("/api/score", "api_score", ("POST",)),
    RouteSpec("/api/job/pause", "api_job_pause", ("POST",)),
    RouteSpec("/api/job/resume", "api_job_resume", ("POST",)),
    RouteSpec("/api/mark", "api_mark_photo", ("POST",)),
    RouteSpec("/api/mark/color", "api_mark_color", ("POST",)),
    RouteSpec("/api/mark/status", "api_mark_status", ("POST",)),
    RouteSpec("/api/mark/restore", "api_restore_marks", ("POST",)),
    RouteSpec("/api/mark/accept", "api_accept_marks", ("POST",)),
    RouteSpec("/api/curation/history", "api_curation_history"),
    RouteSpec("/api/curation/undo", "api_curation_undo", ("POST",)),
    RouteSpec("/api/image", "api_image"),
    RouteSpec("/api/thumbnail", "api_thumbnail"),
    RouteSpec("/api/export", "api_export"),
    RouteSpec("/api/export/selected", "api_export_selected_csv"),
    RouteSpec("/api/export/preflight", "api_export_preflight", ("POST",)),
    RouteSpec("/api/export/selected-files", "api_export_selected", ("POST",)),
    RouteSpec("/api/pick-folder", "api_pick_folder", ("POST",)),
    RouteSpec("/api/pick-folders", "api_pick_folders", ("POST",)),
    RouteSpec("/api/pick-export-folder", "api_pick_export_folder", ("POST",)),
    RouteSpec("/api/reveal", "api_reveal", ("POST",)),
)

STATIC_ROUTE_PATH = "/static"
STATIC_CACHE_CONTROL = "no-cache"


class CulviaStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: dict[str, Any]) -> Response:
        response = await super().get_response(path, scope)
        response.headers.setdefault("Cache-Control", STATIC_CACHE_CONTROL)
        return response


def build_routes(handlers: WebRouteHandlers, *, web_dir: str | Path) -> list[BaseRoute]:
    routes: list[BaseRoute] = []
    for spec in APP_ROUTE_SPECS:
        endpoint = getattr(handlers, spec.handler)
        if spec.methods:
            routes.append(Route(spec.path, endpoint, methods=list(spec.methods)))
        else:
            routes.append(Route(spec.path, endpoint))
    routes.append(Mount(STATIC_ROUTE_PATH, CulviaStaticFiles(directory=web_dir), name="static"))
    return routes
