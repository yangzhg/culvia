from __future__ import annotations

import unittest
from dataclasses import fields
from pathlib import Path

import pandas as pd
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

import culvia_app
from culvia.app_state import AppStateStore, create_initial_state
from culvia.job_service import ScoringJobService
from culvia.runtime_config import RuntimeConfig
from culvia.web_app import create_web_app
from culvia.web_routes import APP_ROUTE_SPECS, STATIC_ROUTE_PATH, WebRouteHandlers, build_routes


async def dummy_endpoint(_: Request) -> Response:
    return Response("ok")


def dummy_handlers() -> WebRouteHandlers:
    return WebRouteHandlers(**{field.name: dummy_endpoint for field in fields(WebRouteHandlers)})


class WebRouteTests(unittest.TestCase):
    def test_route_contract_is_stable(self) -> None:
        self.assertEqual(
            [(spec.path, spec.handler, spec.methods) for spec in APP_ROUTE_SPECS],
            [
                ("/", "homepage", ()),
                ("/health", "health", ()),
                ("/api/host-config", "host_config", ()),
                ("/api/capabilities", "api_capabilities", ()),
                ("/api/state", "api_state", ()),
                ("/api/filter", "api_filter", ("POST",)),
                ("/api/network", "api_network", ("POST",)),
                ("/api/llm-config", "api_llm_config", ("POST",)),
                ("/api/llm-models", "api_llm_models", ("POST",)),
                ("/api/models", "api_models", ("POST",)),
                ("/api/cache", "api_cache", ("POST",)),
                ("/api/cache/clear", "api_clear_history", ("POST",)),
                ("/api/model/clear", "api_clear_model", ("POST",)),
                ("/api/upload", "api_upload", ("POST",)),
                ("/api/score", "api_score", ("POST",)),
                ("/api/job/pause", "api_job_pause", ("POST",)),
                ("/api/job/resume", "api_job_resume", ("POST",)),
                ("/api/mark", "api_mark_photo", ("POST",)),
                ("/api/mark/color", "api_mark_color", ("POST",)),
                ("/api/mark/status", "api_mark_status", ("POST",)),
                ("/api/mark/restore", "api_restore_marks", ("POST",)),
                ("/api/mark/accept", "api_accept_marks", ("POST",)),
                ("/api/curation/history", "api_curation_history", ()),
                ("/api/curation/undo", "api_curation_undo", ("POST",)),
                ("/api/image", "api_image", ()),
                ("/api/thumbnail", "api_thumbnail", ()),
                ("/api/export", "api_export", ()),
                ("/api/export/selected", "api_export_selected_csv", ()),
                ("/api/export/preflight", "api_export_preflight", ("POST",)),
                ("/api/export/selected-files", "api_export_selected", ("POST",)),
                ("/api/pick-folder", "api_pick_folder", ("POST",)),
                ("/api/pick-export-folder", "api_pick_export_folder", ("POST",)),
                ("/api/reveal", "api_reveal", ("POST",)),
            ],
        )

    def test_build_routes_mounts_static_after_api_routes(self) -> None:
        routes = build_routes(dummy_handlers(), web_dir=Path("web"))

        self.assertEqual(
            [route.path for route in routes], [spec.path for spec in APP_ROUTE_SPECS] + [STATIC_ROUTE_PATH]
        )
        self.assertTrue(all(isinstance(route, Route) for route in routes[:-1]))
        self.assertIsInstance(routes[-1], Mount)
        self.assertEqual(routes[-1].name, "static")

    def test_build_routes_applies_post_methods_only_to_post_specs(self) -> None:
        routes = build_routes(dummy_handlers(), web_dir=Path("web"))
        route_methods = {route.path: route.methods for route in routes if isinstance(route, Route)}

        for spec in APP_ROUTE_SPECS:
            if spec.methods:
                self.assertEqual(route_methods[spec.path], set(spec.methods))
            else:
                self.assertEqual(route_methods[spec.path], {"GET", "HEAD"})

    def test_create_app_uses_fresh_route_instances(self) -> None:
        first = culvia_app.create_app()
        second = culvia_app.create_app()

        self.assertEqual(
            [route.path for route in first.routes], [spec.path for spec in APP_ROUTE_SPECS] + [STATIC_ROUTE_PATH]
        )
        self.assertEqual(
            [route.path for route in second.routes], [spec.path for spec in APP_ROUTE_SPECS] + [STATIC_ROUTE_PATH]
        )
        self.assertIsNot(first.routes[0], second.routes[0])

    def test_package_web_app_factory_mounts_runtime_state_and_fresh_routes(self) -> None:
        config = RuntimeConfig(
            web_dir=Path("web"),
            upload_cache_dir=Path("uploads"),
            thumbnail_cache_dir=Path("thumbs"),
            default_cache_path="scores.sqlite",
            default_photo_dirs=("/photos",),
        )
        state_store = AppStateStore(
            create_initial_state(
                scores_df=pd.DataFrame(),
                default_photo_dirs=[],
                default_cache_path="scores.sqlite",
                filter_defaults={},
                default_selected_models=[],
            )
        )
        job_service = ScoringJobService(state_store)

        first = create_web_app(dummy_handlers(), config=config, state_store=state_store, job_service=job_service)
        second = create_web_app(dummy_handlers(), config=config, state_store=state_store, job_service=job_service)

        self.assertIs(first.state.runtime_config, config)
        self.assertIs(first.state.app_state_store, state_store)
        self.assertIs(first.state.job_service, job_service)
        self.assertEqual(
            [route.path for route in first.routes], [spec.path for spec in APP_ROUTE_SPECS] + [STATIC_ROUTE_PATH]
        )
        self.assertIsNot(first.routes[0], second.routes[0])


if __name__ == "__main__":
    unittest.main()
