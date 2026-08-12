from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from PIL import Image
from starlette.datastructures import QueryParams

from culvia import scoring
from culvia.app_state import AppStateStore, create_initial_state
from culvia.job_service import ScoringJobService
from culvia.runtime_config import RuntimeConfig
from culvia.web_context import (
    media_path_from_request,
    path_from_query,
    request_job_service,
    request_runtime_config,
    request_state_store,
)


def make_image(path: Path) -> Path:
    image = Image.new("RGB", (24, 16), (120, 90, 80))
    image.save(path)
    return path


def make_store(*, scores_df: pd.DataFrame, folders: list[str], cache_path: str) -> AppStateStore:
    return AppStateStore(
        create_initial_state(
            scores_df=scores_df,
            default_photo_dirs=folders,
            default_cache_path=cache_path,
            filter_defaults={},
            default_selected_models=[],
        )
    )


def make_runtime_config(tmp: Path, *, upload_cache_dir: Path | None = None) -> RuntimeConfig:
    return RuntimeConfig(
        web_dir=tmp / "web",
        upload_cache_dir=upload_cache_dir or tmp / "uploads",
        thumbnail_cache_dir=tmp / "thumbs",
        default_cache_path=str(tmp / "scores.sqlite"),
        default_photo_dirs=(),
        thumbnail_max_size=320,
    )


class WebContextTests(unittest.TestCase):
    def test_request_helpers_prefer_starlette_app_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fallback_config = make_runtime_config(root / "fallback")
            injected_config = make_runtime_config(root / "injected")
            fallback_store = make_store(
                scores_df=pd.DataFrame(columns=scoring.CSV_COLUMNS),
                folders=["/fallback"],
                cache_path=str(root / "fallback.sqlite"),
            )
            injected_store = make_store(
                scores_df=pd.DataFrame(columns=scoring.CSV_COLUMNS),
                folders=["/injected"],
                cache_path=str(root / "injected.sqlite"),
            )
            fallback_service = ScoringJobService(fallback_store)
            injected_service = ScoringJobService(injected_store)
            request = SimpleNamespace(
                app=SimpleNamespace(
                    state=SimpleNamespace(
                        runtime_config=injected_config,
                        app_state_store=injected_store,
                        job_service=injected_service,
                    )
                )
            )

            self.assertIs(request_runtime_config(request, fallback_config), injected_config)
            self.assertIs(request_state_store(request, fallback_store), injected_store)
            self.assertIs(request_job_service(request, fallback_service), injected_service)

    def test_request_helpers_fallback_without_app_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fallback_config = make_runtime_config(root)
            fallback_store = make_store(
                scores_df=pd.DataFrame(columns=scoring.CSV_COLUMNS),
                folders=["/fallback"],
                cache_path=str(root / "fallback.sqlite"),
            )
            fallback_service = ScoringJobService(fallback_store)
            request = SimpleNamespace()

            self.assertIs(request_runtime_config(request, fallback_config), fallback_config)
            self.assertIs(request_state_store(request, fallback_store), fallback_store)
            self.assertIs(request_job_service(request, fallback_service), fallback_service)

    def test_media_path_uses_store_and_runtime_config_from_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upload_root = root / "uploads"
            upload_root.mkdir()
            image_path = make_image(upload_root / "inside.jpg")
            fallback_store = make_store(
                scores_df=pd.DataFrame(columns=scoring.CSV_COLUMNS),
                folders=[],
                cache_path=str(root / "fallback.sqlite"),
            )
            injected_store = make_store(
                scores_df=pd.DataFrame(columns=scoring.CSV_COLUMNS),
                folders=[],
                cache_path=str(root / "injected.sqlite"),
            )
            injected_store.publish_media_state(
                source_patch={"mode": "uploads", "uploadedPaths": [str(image_path)], "folders": []}
            )
            fallback_config = make_runtime_config(root / "fallback", upload_cache_dir=root / "other-uploads")
            injected_config = make_runtime_config(root / "injected", upload_cache_dir=upload_root)
            request = SimpleNamespace(
                app=SimpleNamespace(
                    state=SimpleNamespace(
                        runtime_config=injected_config,
                        app_state_store=injected_store,
                    )
                ),
                query_params=QueryParams({"path": str(image_path)}),
            )

            path, status = media_path_from_request(
                request,
                fallback_state_store=fallback_store,
                fallback_runtime_config=fallback_config,
                normalize_dataframe=lambda _df: self.fail(
                    "DataFrame media snapshots must not normalize the full table"
                ),
            )

            self.assertEqual(path, image_path.resolve())
            self.assertEqual(status, 200)
            self.assertEqual(
                path_from_query(
                    request,
                    fallback_state_store=fallback_store,
                    fallback_runtime_config=fallback_config,
                    normalize_dataframe=lambda _df: self.fail(
                        "DataFrame media snapshots must not normalize the full table"
                    ),
                ),
                image_path.resolve(),
            )

    def test_explicit_media_state_store_overrides_request_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            allowed_root = root / "allowed"
            blocked_root = root / "blocked"
            allowed_root.mkdir()
            blocked_root.mkdir()
            allowed_image = make_image(allowed_root / "allowed.jpg")
            blocked_image = make_image(blocked_root / "blocked.jpg")
            request_store = make_store(
                scores_df=pd.DataFrame(columns=scoring.CSV_COLUMNS),
                folders=[str(blocked_root)],
                cache_path=str(root / "request.sqlite"),
            )
            explicit_store = make_store(
                scores_df=pd.DataFrame(columns=scoring.CSV_COLUMNS),
                folders=[str(allowed_root)],
                cache_path=str(root / "explicit.sqlite"),
            )
            request = SimpleNamespace(
                app=SimpleNamespace(state=SimpleNamespace(app_state_store=request_store)),
                query_params=QueryParams({"path": str(allowed_image)}),
            )

            path, status = media_path_from_request(
                request,
                fallback_state_store=request_store,
                fallback_runtime_config=make_runtime_config(root),
                normalize_dataframe=scoring.normalize_score_dataframe,
                state_store=explicit_store,
            )
            blocked_path, blocked_status = media_path_from_request(
                SimpleNamespace(
                    app=SimpleNamespace(state=SimpleNamespace(app_state_store=explicit_store)),
                    query_params=QueryParams({"path": str(blocked_image)}),
                ),
                fallback_state_store=explicit_store,
                fallback_runtime_config=make_runtime_config(root),
                normalize_dataframe=scoring.normalize_score_dataframe,
                state_store=explicit_store,
            )

            self.assertEqual(path, allowed_image.resolve())
            self.assertEqual(status, 200)
            self.assertIsNone(blocked_path)
            self.assertEqual(blocked_status, 403)

    def test_consecutive_media_requests_do_not_touch_the_scores_dataframe(self) -> None:
        armed = False

        class TripwireFrame(pd.DataFrame):
            def __getattribute__(self, name: str):
                if armed and not name.startswith("_"):
                    raise AssertionError(f"request touched DataFrame.{name}")
                return super().__getattribute__(name)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_root = root / "source"
            source_root.mkdir()
            scored_outside = make_image(root / "outside.jpg")
            store = make_store(
                scores_df=TripwireFrame([{"file_id": "outside", "path": str(scored_outside)}]),
                folders=[str(source_root)],
                cache_path=str(root / "scores.sqlite"),
            )
            config = make_runtime_config(root)
            by_id_request = SimpleNamespace(
                app=SimpleNamespace(state=SimpleNamespace(app_state_store=store, runtime_config=config)),
                query_params=QueryParams({"file_id": "outside"}),
            )
            by_path_request = SimpleNamespace(
                app=by_id_request.app,
                query_params=QueryParams({"path": str(scored_outside)}),
            )

            armed = True
            first = media_path_from_request(
                by_id_request,
                fallback_state_store=store,
                fallback_runtime_config=config,
                normalize_dataframe=lambda _value: self.fail("request normalized DataFrame"),
            )
            second = media_path_from_request(
                by_path_request,
                fallback_state_store=store,
                fallback_runtime_config=config,
                normalize_dataframe=lambda _value: self.fail("request normalized DataFrame"),
            )

            self.assertEqual(first, (scored_outside.resolve(), 200))
            self.assertEqual(second, (scored_outside.resolve(), 200))


if __name__ == "__main__":
    unittest.main()
