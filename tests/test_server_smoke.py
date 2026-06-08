from __future__ import annotations

import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from PIL import Image
from starlette.testclient import TestClient

import culvia_app
from culvia import scoring
from culvia.app_state import AppStateStore, create_initial_state
from culvia import curation as photo_curation
from culvia.curation_history import load_curation_actions


def make_test_image(path: Path, size: tuple[int, int] = (32, 24)) -> Path:
    image = Image.new("RGB", size, (96, 128, 180))
    image.save(path)
    return path


class ServerSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._client = TestClient(culvia_app.app)

    def test_home_health_and_static_assets_are_served(self) -> None:
        home = self._client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn("Culvia", home.text)

        health = self._client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json(), {"ok": True})

        app_js = self._client.get("/static/app.js")
        styles = self._client.get("/static/styles.css")
        foundation_styles = self._client.get("/static/styles/00-foundation.css")
        self.assertEqual(app_js.status_code, 200)
        self.assertIn("const $", app_js.text)
        self.assertEqual(styles.status_code, 200)
        self.assertIn("/static/styles/00-foundation.css", styles.text)
        self.assertEqual(foundation_styles.status_code, 200)
        self.assertIn(":root", foundation_styles.text)

    def test_app_factory_serves_health_route(self) -> None:
        client = TestClient(culvia_app.create_app())

        response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})

    def test_app_factory_can_serve_injected_state_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = str(Path(tmp) / "custom.sqlite")
            store = AppStateStore(
                create_initial_state(
                    scores_df=pd.DataFrame(columns=scoring.CSV_COLUMNS),
                    default_photo_dirs=["/custom/photos"],
                    default_cache_path=cache_path,
                    filter_defaults=culvia_app.FILTER_DEFAULTS,
                    default_selected_models=[scoring.MODEL_CORE_AESTHETIC],
                )
            )
            client = TestClient(culvia_app.create_app(store))

            response = client.get("/api/state")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["source"]["folders"], ["/custom/photos"])
        self.assertEqual(payload["source"]["cachePath"], cache_path)
        self.assertEqual(payload["models"]["selected"], [scoring.MODEL_CORE_AESTHETIC])

    def test_injected_state_store_serves_filter_and_mark_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = str(Path(tmp) / "custom.sqlite")
            scores_df = pd.DataFrame(
                [
                    {
                        "file_id": "image-1",
                        "path": "/photos/a.jpg",
                        "folder": "/photos",
                        "filename": "a.jpg",
                        "error": "",
                        "overall_0_10": 8.6,
                    },
                    {
                        "file_id": "image-2",
                        "path": "/photos/b.jpg",
                        "folder": "/photos",
                        "filename": "b.jpg",
                        "error": "",
                        "overall_0_10": 6.1,
                    },
                ]
            )
            store = AppStateStore(
                create_initial_state(
                    scores_df=scores_df,
                    default_photo_dirs=["/custom/photos"],
                    default_cache_path=cache_path,
                    filter_defaults=culvia_app.FILTER_DEFAULTS,
                    default_selected_models=[scoring.MODEL_CORE_AESTHETIC],
                )
            )
            client = TestClient(culvia_app.create_app(store))

            filter_response = client.post("/api/filter", json={"minScore": 7.0, "colorLabel": "all"})
            mark_response = client.post(
                "/api/mark", json={"fileId": "image-1", "rating": 4, "status": "pick", "colorLabel": "red"}
            )
            batch_response = client.post("/api/mark/color", json={"scope": "filtered", "colorLabel": "blue"})
            pick_filter_response = client.post(
                "/api/filter", json={"minScore": 0, "manualStatus": "pick", "colorLabel": "all"}
            )
            pending_filter_response = client.post("/api/filter", json={"manualStatus": "pending"})
            reject_mark_response = client.post("/api/mark", json={"fileId": "image-2", "status": "reject"})
            reject_filter_response = client.post("/api/filter", json={"manualStatus": "reject"})
            marks = photo_curation.load_photo_marks(cache_path, ["image-1", "image-2"])

            self.assertEqual(filter_response.status_code, 200)
            self.assertEqual(mark_response.status_code, 200)
            self.assertEqual(batch_response.status_code, 200)
            self.assertEqual(pick_filter_response.status_code, 200)
            self.assertEqual(pending_filter_response.status_code, 200)
            self.assertEqual(reject_mark_response.status_code, 200)
            self.assertEqual(reject_filter_response.status_code, 200)
            mark_action = mark_response.json()["action"]
            self.assertEqual(mark_action["fileId"], "image-1")
            self.assertEqual(mark_action["beforeMarks"][0]["status"], "")
            history_records = load_curation_actions(cache_path, limit=10)
            mark_history = [record for record in history_records if record.id == mark_action["historyId"]]
            self.assertEqual(mark_history[0].kind, "mark")
            self.assertEqual(mark_history[0].payload["fileId"], "image-1")
            self.assertEqual(batch_response.json()["action"]["colored"], 1)
            self.assertEqual(filter_response.json()["filters"]["minScore"], 7.0)
            self.assertIn("manualStatusOptions", pick_filter_response.json())
            self.assertEqual([photo["fileId"] for photo in pick_filter_response.json()["photos"]], ["image-1"])
            self.assertEqual([photo["fileId"] for photo in pending_filter_response.json()["photos"]], ["image-2"])
            self.assertEqual([photo["fileId"] for photo in reject_filter_response.json()["photos"]], ["image-2"])
            self.assertEqual(marks["image-1"].rating, 4)
            self.assertEqual(marks["image-1"].status, "pick")
            self.assertEqual(marks["image-1"].color_label, "blue")
            self.assertEqual(marks["image-2"].status, "reject")

    def test_mark_route_returns_fresh_state_and_preserves_unset_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = str(Path(tmp) / "custom.sqlite")
            scores_df = pd.DataFrame(
                [
                    {
                        "file_id": "image-1",
                        "path": "/photos/a.jpg",
                        "folder": "/photos",
                        "filename": "a.jpg",
                        "error": "",
                        "overall_0_10": 8.6,
                    },
                ]
            )
            photo_curation.save_photo_mark(cache_path, "image-1", rating=3, color_label="blue")
            store = AppStateStore(
                create_initial_state(
                    scores_df=scores_df,
                    default_photo_dirs=["/custom/photos"],
                    default_cache_path=cache_path,
                    filter_defaults=culvia_app.FILTER_DEFAULTS,
                    default_selected_models=[scoring.MODEL_CORE_AESTHETIC],
                )
            )
            client = TestClient(culvia_app.create_app(store))

            color_response = client.post(
                "/api/mark", json={"fileId": "image-1", "colorLabel": "green", "source": "manual"}
            )
            status_response = client.post(
                "/api/mark", json={"fileId": "image-1", "status": "reject", "source": "manual", "acceptedScore": None}
            )
            clear_response = client.post("/api/mark", json={"fileId": "image-1", "colorLabel": "", "source": "manual"})

            self.assertEqual(color_response.status_code, 200)
            color_manual = color_response.json()["photos"][0]["manual"]
            self.assertEqual(color_manual["rating"], 3)
            self.assertEqual(color_manual["colorLabel"], "green")
            self.assertEqual(status_response.status_code, 200)
            status_manual = status_response.json()["photos"][0]["manual"]
            self.assertEqual(status_manual["rating"], 3)
            self.assertEqual(status_manual["status"], "reject")
            self.assertEqual(status_manual["colorLabel"], "green")
            self.assertEqual(clear_response.status_code, 200)
            clear_manual = clear_response.json()["photos"][0]["manual"]
            self.assertEqual(clear_manual["status"], "reject")
            self.assertEqual(clear_manual["colorLabel"], "")

    def test_injected_state_store_serves_network_models_and_cache_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "photos"
            other = Path(tmp) / "other"
            root.mkdir()
            other.mkdir()
            cache_path = str(Path(tmp) / "scores.sqlite")
            cache_df = pd.DataFrame(
                [
                    {
                        "file_id": "image-1",
                        "path": str(root / "a.jpg"),
                        "folder": str(root),
                        "filename": "a.jpg",
                        "error": "",
                        "overall_0_10": 8.8,
                    },
                    {
                        "file_id": "image-2",
                        "path": str(other / "b.jpg"),
                        "folder": str(other),
                        "filename": "b.jpg",
                        "error": "",
                        "overall_0_10": 6.2,
                    },
                ]
            )
            scoring.save_cache_records(cache_df, cache_path)
            with culvia_app.STATE_LOCK:
                original_network = dict(culvia_app.STATE["network"])
                original_models = deepcopy(culvia_app.STATE["models"])
                original_cache_path = str(culvia_app.STATE["source"].get("cachePath") or "")
            store = AppStateStore(
                create_initial_state(
                    scores_df=pd.DataFrame(columns=scoring.CSV_COLUMNS),
                    default_photo_dirs=[],
                    default_cache_path=str(Path(tmp) / "isolated.sqlite"),
                    filter_defaults=culvia_app.FILTER_DEFAULTS,
                    default_selected_models=[scoring.MODEL_CORE_AESTHETIC],
                )
            )
            client = TestClient(culvia_app.create_app(store))

            network_response = client.post("/api/network", json={"mode": "system"})
            models_response = client.post(
                "/api/models",
                json={"selected": [scoring.MODEL_BASIC_TECHNICAL, scoring.MODEL_CLIP_AESTHETIC]},
            )
            cache_response = client.post(
                "/api/cache",
                json={"mode": "folders", "folders": [str(root)], "cachePath": cache_path},
            )

            self.assertEqual(network_response.status_code, 200)
            self.assertEqual(models_response.status_code, 200)
            self.assertEqual(cache_response.status_code, 200)
            self.assertEqual(network_response.json()["network"]["mode"], "system")
            self.assertEqual(
                models_response.json()["models"]["selected"],
                [scoring.MODEL_BASIC_TECHNICAL, scoring.MODEL_CLIP_AESTHETIC],
            )
            self.assertEqual(cache_response.json()["source"]["folders"], [str(root)])
            self.assertEqual([photo["fileId"] for photo in cache_response.json()["photos"]], ["image-1"])
            with store.lock:
                loaded = scoring.normalize_score_dataframe(store.data["scores_df"])
                self.assertEqual(store.data["network"]["mode"], "system")
                self.assertEqual(loaded["file_id"].tolist(), ["image-1"])
            with culvia_app.STATE_LOCK:
                self.assertEqual(culvia_app.STATE["network"], original_network)
                self.assertEqual(culvia_app.STATE["models"], original_models)
                self.assertEqual(str(culvia_app.STATE["source"].get("cachePath") or ""), original_cache_path)

    def test_cache_route_rejects_unsupported_cache_path_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = str(Path(tmp) / "current.sqlite")
            store = AppStateStore(
                create_initial_state(
                    scores_df=pd.DataFrame(columns=scoring.CSV_COLUMNS),
                    default_photo_dirs=[],
                    default_cache_path=cache_path,
                    filter_defaults=culvia_app.FILTER_DEFAULTS,
                    default_selected_models=[scoring.MODEL_CORE_AESTHETIC],
                )
            )
            client = TestClient(culvia_app.create_app(store))

            response = client.post("/api/cache", json={"cachePath": str(Path(tmp) / "notes.txt")})

            self.assertEqual(response.status_code, 400)
            self.assertIn("SQLite", response.json()["error"])
            self.assertEqual(response.json()["errorCode"], "cachePathInvalid")
            self.assertIn("SQLite", response.json()["errorParams"]["reason"])
            with store.lock:
                self.assertEqual(store.data["source"]["cachePath"], cache_path)

    def test_injected_state_store_serves_maintenance_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = str(Path(tmp) / "history.sqlite")
            scoring.save_cache_records(
                pd.DataFrame(
                    [
                        {
                            "file_id": "image-1",
                            "path": "/photos/a.jpg",
                            "folder": "/photos",
                            "filename": "a.jpg",
                            "error": "",
                            "overall_0_10": 8.0,
                        }
                    ]
                ),
                cache_path,
            )
            source_df = pd.DataFrame(
                [
                    {
                        "file_id": "image-1",
                        "path": "/photos/a.jpg",
                        "folder": "/photos",
                        "filename": "a.jpg",
                        "error": "",
                        "overall_0_10": 8.0,
                    }
                ]
            )
            store = AppStateStore(
                create_initial_state(
                    scores_df=source_df,
                    default_photo_dirs=["/photos"],
                    default_cache_path=cache_path,
                    filter_defaults=culvia_app.FILTER_DEFAULTS,
                    default_selected_models=[scoring.MODEL_CORE_AESTHETIC],
                )
            )
            with store.lock:
                store.data["job"].update({"phase": "done", "title": "已有结果"})
            with culvia_app.STATE_LOCK:
                original_global_scores = culvia_app.STATE["scores_df"].copy()
                original_global_source = deepcopy(culvia_app.STATE["source"])
                original_global_job = deepcopy(culvia_app.STATE["job"])
            client = TestClient(culvia_app.create_app(store))

            history_response = client.post("/api/cache/clear", json={"cachePath": cache_path})

            self.assertEqual(history_response.status_code, 200)
            self.assertEqual(history_response.json()["maintenance"]["kind"], "history")
            self.assertTrue(history_response.json()["maintenance"]["deleted"])
            self.assertFalse(Path(cache_path).exists())
            with store.lock:
                self.assertTrue(scoring.normalize_score_dataframe(store.data["scores_df"]).empty)
                self.assertEqual(store.data["source"]["cachePath"], cache_path)
                self.assertEqual(store.data["job"]["phase"], "idle")
            with culvia_app.STATE_LOCK:
                self.assertTrue(culvia_app.STATE["scores_df"].equals(original_global_scores))
                self.assertEqual(culvia_app.STATE["source"], original_global_source)
                self.assertEqual(culvia_app.STATE["job"], original_global_job)

            app_model_dir = Path(tmp) / "app_models"
            repo_root = Path(tmp) / "hf"
            repo_dir = "models--unit--model"
            app_model_dir.mkdir()
            repo_path = repo_root / repo_dir
            repo_path.mkdir(parents=True)
            (app_model_dir / "model.bin").write_bytes(b"model")
            (repo_path / "config.json").write_text("{}", encoding="utf-8")
            with culvia_app.MODEL_RUNTIME.lock:
                original_model_cache = dict(culvia_app.MODEL_RUNTIME.cache)
                culvia_app.MODEL_RUNTIME.cache["unit-model:cpu"] = object()
            try:
                with (
                    patch("culvia_app.APP_MODEL_CACHE_DIR", app_model_dir),
                    patch(
                        "culvia_app.MODEL_REPO_CACHE_DIRS",
                        [repo_dir],
                    ),
                    patch("culvia_app.get_huggingface_cache_root", return_value=repo_root),
                ):
                    model_response = client.post("/api/model/clear", json={})

                self.assertEqual(model_response.status_code, 200)
                self.assertEqual(model_response.json()["maintenance"]["kind"], "model")
                self.assertTrue(model_response.json()["maintenance"]["deleted"])
                self.assertFalse(app_model_dir.exists())
                self.assertFalse(repo_path.exists())
                with culvia_app.MODEL_RUNTIME.lock:
                    self.assertEqual(culvia_app.MODEL_RUNTIME.cache, {})
                with culvia_app.STATE_LOCK:
                    self.assertTrue(culvia_app.STATE["scores_df"].equals(original_global_scores))
                    self.assertEqual(culvia_app.STATE["source"], original_global_source)
                    self.assertEqual(culvia_app.STATE["job"], original_global_job)
            finally:
                with culvia_app.MODEL_RUNTIME.lock:
                    culvia_app.MODEL_RUNTIME.cache.clear()
                    culvia_app.MODEL_RUNTIME.cache.update(original_model_cache)

    def test_clear_history_rejects_non_current_cache_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            current_cache = str(Path(tmp) / "current.sqlite")
            other_cache = Path(tmp) / "other.sqlite"
            other_cache.write_text("do not delete", encoding="utf-8")
            store = AppStateStore(
                create_initial_state(
                    scores_df=pd.DataFrame(columns=scoring.CSV_COLUMNS),
                    default_photo_dirs=[],
                    default_cache_path=current_cache,
                    filter_defaults=culvia_app.FILTER_DEFAULTS,
                    default_selected_models=[scoring.MODEL_CORE_AESTHETIC],
                )
            )
            client = TestClient(culvia_app.create_app(store))

            response = client.post("/api/cache/clear", json={"cachePath": str(other_cache)})

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["error"], "只能清理当前正在使用的评分记录。")
            self.assertEqual(response.json()["errorCode"], "historyCachePathInvalid")
            self.assertTrue(other_cache.exists())

    def test_clear_local_data_removes_app_data_models_and_resets_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_path = str(root / "scores.sqlite")
            scoring.save_cache_records(
                pd.DataFrame(
                    [
                        {
                            "file_id": "image-1",
                            "path": "/photos/a.jpg",
                            "folder": "/photos",
                            "filename": "a.jpg",
                            "error": "",
                            "overall_0_10": 8.0,
                        }
                    ]
                ),
                cache_path,
            )
            photo_curation.save_photo_mark(cache_path, "image-1", status="pick", rating=5)
            source_df = pd.DataFrame(
                [
                    {
                        "file_id": "image-1",
                        "path": "/photos/a.jpg",
                        "folder": "/photos",
                        "filename": "a.jpg",
                        "error": "",
                        "overall_0_10": 8.0,
                    }
                ]
            )
            store = AppStateStore(
                create_initial_state(
                    scores_df=source_df,
                    default_photo_dirs=["/photos"],
                    default_cache_path=cache_path,
                    filter_defaults=culvia_app.FILTER_DEFAULTS,
                    default_selected_models=[scoring.MODEL_CORE_AESTHETIC],
                )
            )
            with store.lock:
                store.data["source"]["uploadedPaths"] = [str(root / "uploads" / "a.jpg")]
                store.data["network"]["mode"] = "system"
                store.data["job"].update({"phase": "done", "title": "已有结果"})

            upload_dir = root / "uploads"
            thumb_dir = root / "thumbnails"
            analysis_dir = root / "analysis"
            app_model_dir = root / "app_models"
            repo_root = root / "hf"
            repo_dir = "models--unit--model"
            repo_path = repo_root / repo_dir
            lock_path = repo_root / ".locks" / repo_dir
            for path in (upload_dir, thumb_dir, analysis_dir, app_model_dir, repo_path, lock_path):
                path.mkdir(parents=True)
                (path / "file.bin").write_bytes(b"data")

            client = TestClient(culvia_app.create_app(store))
            with (
                patch("culvia_app.UPLOAD_CACHE_DIR", upload_dir),
                patch("culvia_app.THUMBNAIL_CACHE_DIR", thumb_dir),
                patch("culvia_app.ANALYSIS_IMAGE_CACHE_DIR", analysis_dir),
                patch("culvia_app.APP_MODEL_CACHE_DIR", app_model_dir),
                patch("culvia_app.MODEL_REPO_CACHE_DIRS", [repo_dir]),
                patch("culvia_app.get_huggingface_cache_root", return_value=repo_root),
                patch("culvia_app.delete_llm_api_key") as delete_key,
            ):
                response = client.post("/api/data/clear", json={"cachePath": cache_path})

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["maintenance"]["kind"], "localData")
            delete_key.assert_called_once_with()
            for path in (Path(cache_path), upload_dir, thumb_dir, analysis_dir, app_model_dir, repo_path, lock_path):
                self.assertFalse(path.exists())
            with store.lock:
                self.assertTrue(scoring.normalize_score_dataframe(store.data["scores_df"]).empty)
                self.assertEqual(store.data["source"]["folders"], [])
                self.assertEqual(store.data["source"]["uploadedPaths"], [])
                self.assertEqual(store.data["source"]["cachePath"], cache_path)
                self.assertEqual(store.data["network"]["mode"], "direct")
                self.assertEqual(store.data["job"]["phase"], "idle")

    def test_injected_state_store_serves_upload_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            upload_root = Path(tmp) / "uploads"
            store = AppStateStore(
                create_initial_state(
                    scores_df=pd.DataFrame(columns=scoring.CSV_COLUMNS),
                    default_photo_dirs=["/photos"],
                    default_cache_path=str(Path(tmp) / "scores.sqlite"),
                    filter_defaults=culvia_app.FILTER_DEFAULTS,
                    default_selected_models=[scoring.MODEL_CORE_AESTHETIC],
                )
            )
            with culvia_app.STATE_LOCK:
                original_global_source = deepcopy(culvia_app.STATE["source"])
            client = TestClient(
                culvia_app.create_app(
                    store,
                    runtime_config=culvia_app.current_runtime_config().with_paths(upload_cache_dir=upload_root),
                )
            )

            response = client.post(
                "/api/upload",
                files=[
                    ("files", ("keep.jpg", b"fake image bytes", "image/jpeg")),
                    ("files", ("ignore.txt", b"not an image", "text/plain")),
                ],
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["ignored"], 1)
            saved_path = Path(payload["saved"][0])
            self.assertTrue(saved_path.exists())
            self.assertTrue(culvia_app.is_inside_path(saved_path, upload_root))
            with store.lock:
                self.assertEqual(store.data["source"]["mode"], "uploads")
                self.assertEqual(store.data["source"]["uploadedPaths"], payload["saved"])
            with culvia_app.STATE_LOCK:
                self.assertEqual(culvia_app.STATE["source"], original_global_source)

    def test_injected_job_service_serves_pause_and_resume_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = AppStateStore(
                create_initial_state(
                    scores_df=pd.DataFrame(columns=scoring.CSV_COLUMNS),
                    default_photo_dirs=["/photos"],
                    default_cache_path=str(Path(tmp) / "scores.sqlite"),
                    filter_defaults=culvia_app.FILTER_DEFAULTS,
                    default_selected_models=[scoring.MODEL_CORE_AESTHETIC],
                )
            )
            web_app = culvia_app.create_app(store)
            job_service = web_app.state.job_service
            job_id = job_service.reserve()
            self.assertTrue(job_id)
            with culvia_app.STATE_LOCK:
                original_global_job = deepcopy(culvia_app.STATE["job"])
            client = TestClient(web_app)

            pause_response = client.post("/api/job/pause", json={})
            resume_response = client.post("/api/job/resume", json={})

            self.assertEqual(pause_response.status_code, 200)
            self.assertEqual(pause_response.json()["job"]["phase"], "pausing")
            self.assertEqual(pause_response.json()["job"]["jobId"], job_id)
            self.assertEqual(resume_response.status_code, 200)
            self.assertEqual(resume_response.json()["job"]["phase"], "scoring")
            self.assertEqual(resume_response.json()["job"]["jobId"], job_id)
            with store.lock:
                self.assertEqual(store.data["job"]["phase"], "scoring")
                self.assertFalse(store.data["job"]["paused"])
            with culvia_app.STATE_LOCK:
                self.assertEqual(culvia_app.STATE["job"], original_global_job)

    def test_injected_state_store_serves_export_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "photos"
            root.mkdir()
            selected_path = root / "selected.jpg"
            rejected_path = root / "rejected.jpg"
            missing_path = root / "missing.jpg"
            selected_path.write_bytes(b"selected")
            rejected_path.write_bytes(b"rejected")
            cache_path = str(Path(tmp) / "scores.sqlite")
            source_df = pd.DataFrame(
                [
                    {
                        "file_id": "image-1",
                        "path": str(selected_path),
                        "folder": str(root),
                        "filename": selected_path.name,
                        "error": "",
                        "overall_0_10": 8.8,
                    },
                    {
                        "file_id": "image-2",
                        "path": str(rejected_path),
                        "folder": str(root),
                        "filename": rejected_path.name,
                        "error": "",
                        "overall_0_10": 5.2,
                    },
                    {
                        "file_id": "image-3",
                        "path": str(missing_path),
                        "folder": str(root),
                        "filename": missing_path.name,
                        "error": "",
                        "overall_0_10": 8.1,
                    },
                ]
            )
            photo_curation.save_photo_mark(cache_path, "image-1", rating=5, status="pick", color_label="green")
            photo_curation.save_photo_mark(cache_path, "image-3", rating=4, status="pick", color_label="yellow")
            store = AppStateStore(
                create_initial_state(
                    scores_df=source_df,
                    default_photo_dirs=[str(root)],
                    default_cache_path=cache_path,
                    filter_defaults=culvia_app.FILTER_DEFAULTS,
                    default_selected_models=[scoring.MODEL_CORE_AESTHETIC],
                )
            )
            with store.lock:
                store.data["filters"]["minScore"] = 7.0
            with culvia_app.STATE_LOCK:
                original_global_scores = culvia_app.STATE["scores_df"].copy()
                original_global_source = deepcopy(culvia_app.STATE["source"])
            client = TestClient(culvia_app.create_app(store))

            filtered_response = client.get("/api/export")
            selected_response = client.get("/api/export/selected")
            export_dir = Path(tmp) / "exported"
            export_dir.mkdir()
            preflight_response = client.post("/api/export/preflight", json={"destination": str(export_dir)})
            copied_response = client.post("/api/export/selected-files", json={"destination": str(export_dir)})

            self.assertEqual(filtered_response.status_code, 200)
            filtered_csv = filtered_response.content.decode("utf-8-sig")
            self.assertIn("image-1", filtered_csv)
            self.assertNotIn("image-2", filtered_csv)
            self.assertIn("lightroom_rating", filtered_csv)
            self.assertEqual(selected_response.status_code, 200)
            selected_csv = selected_response.content.decode("utf-8-sig")
            self.assertIn("image-1", selected_csv)
            self.assertNotIn("image-2", selected_csv)
            self.assertEqual(preflight_response.status_code, 200)
            preflight_payload = preflight_response.json()
            self.assertEqual(preflight_payload["schemaVersion"], 1)
            self.assertEqual(preflight_payload["total"], 2)
            self.assertEqual(preflight_response.json()["ready"], 1)
            self.assertEqual(preflight_payload["missing"], 1)
            self.assertEqual(preflight_payload["missingFiles"], [str(missing_path)])
            self.assertEqual(copied_response.status_code, 200)
            copied_payload = copied_response.json()
            self.assertEqual(copied_payload["schemaVersion"], 1)
            self.assertEqual(copied_payload["copied"], 1)
            self.assertEqual(copied_payload["skipped"], 1)
            self.assertNotIn("files", copied_payload)
            self.assertNotIn("skippedFiles", copied_payload)
            self.assertEqual(copied_payload["skippedDetails"][0]["reason"], "missing")
            self.assertEqual(copied_payload["skippedDetails"][0]["label"], "源文件缺失")
            self.assertEqual(
                copied_payload["skippedReasonSummary"], [{"reason": "missing", "label": "源文件缺失", "count": 1}]
            )
            self.assertTrue((export_dir / selected_path.name).exists())
            with culvia_app.STATE_LOCK:
                self.assertTrue(culvia_app.STATE["scores_df"].equals(original_global_scores))
                self.assertEqual(culvia_app.STATE["source"], original_global_source)

    def test_injected_state_store_serves_accept_marks_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = str(Path(tmp) / "scores.sqlite")
            source_df = pd.DataFrame(
                [
                    {
                        "file_id": "image-1",
                        "path": "/photos/a.jpg",
                        "folder": "/photos",
                        "filename": "a.jpg",
                        "error": "",
                        "overall_0_10": 8.4,
                    },
                    {
                        "file_id": "image-2",
                        "path": "/photos/b.jpg",
                        "folder": "/photos",
                        "filename": "b.jpg",
                        "error": "",
                        "overall_0_10": 5.1,
                    },
                ]
            )
            store = AppStateStore(
                create_initial_state(
                    scores_df=source_df,
                    default_photo_dirs=["/photos"],
                    default_cache_path=cache_path,
                    filter_defaults=culvia_app.FILTER_DEFAULTS,
                    default_selected_models=[scoring.MODEL_CORE_AESTHETIC],
                )
            )
            with store.lock:
                store.data["filters"]["minScore"] = 7.0
            with culvia_app.STATE_LOCK:
                original_global_scores = culvia_app.STATE["scores_df"].copy()
                original_global_source = deepcopy(culvia_app.STATE["source"])
            client = TestClient(culvia_app.create_app(store))

            response = client.post("/api/mark/accept", json={"scope": "filtered", "basis": "model"})

            self.assertEqual(response.status_code, 200)
            action = response.json()["action"]
            self.assertEqual(action["accepted"], 1)
            self.assertEqual(action["scope"], "filtered")
            self.assertEqual(len(action["beforeMarks"]), 1)
            self.assertEqual(action["beforeMarks"][0]["fileId"], "image-1")
            self.assertEqual(action["beforeMarks"][0]["status"], "")
            marks = photo_curation.load_photo_marks(cache_path, ["image-1", "image-2"])
            self.assertEqual(marks["image-1"].rating, 4)
            self.assertEqual(marks["image-1"].status, "pick")
            self.assertAlmostEqual(float(marks["image-1"].accepted_score or 0), 8.4)
            self.assertNotIn("image-2", marks)
            restore_response = client.post("/api/mark/restore", json={"marks": action["beforeMarks"]})
            self.assertEqual(restore_response.status_code, 200)
            restored_marks = photo_curation.load_photo_marks(cache_path, ["image-1", "image-2"])
            self.assertNotIn("image-1", restored_marks)
            self.assertNotIn("image-2", restored_marks)
            with culvia_app.STATE_LOCK:
                self.assertTrue(culvia_app.STATE["scores_df"].equals(original_global_scores))
                self.assertEqual(culvia_app.STATE["source"], original_global_source)

    def test_llm_acceptance_export_and_undo_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "photos"
            root.mkdir()
            pick_path = root / "llm-pick.jpg"
            reject_path = root / "llm-reject.jpg"
            skipped_path = root / "llm-skipped.jpg"
            pick_path.write_bytes(b"pick")
            reject_path.write_bytes(b"reject")
            skipped_path.write_bytes(b"skipped")
            cache_path = str(Path(tmp) / "scores.sqlite")
            source_df = pd.DataFrame(
                [
                    {
                        "file_id": "image-1",
                        "path": str(pick_path),
                        "folder": str(root),
                        "filename": pick_path.name,
                        "error": "",
                        "overall_0_10": 6.1,
                        "llm_review_overall_0_10": 8.2,
                    },
                    {
                        "file_id": "image-2",
                        "path": str(reject_path),
                        "folder": str(root),
                        "filename": reject_path.name,
                        "error": "",
                        "overall_0_10": 8.8,
                        "llm_review_overall_0_10": 5.2,
                    },
                    {
                        "file_id": "image-3",
                        "path": str(skipped_path),
                        "folder": str(root),
                        "filename": skipped_path.name,
                        "error": "",
                        "overall_0_10": 7.3,
                        "llm_review_overall_0_10": None,
                    },
                ]
            )
            store = AppStateStore(
                create_initial_state(
                    scores_df=source_df,
                    default_photo_dirs=[str(root)],
                    default_cache_path=cache_path,
                    filter_defaults=culvia_app.FILTER_DEFAULTS,
                    default_selected_models=[scoring.MODEL_LLM_REVIEW],
                )
            )
            client = TestClient(culvia_app.create_app(store))

            accept_response = client.post("/api/mark/accept", json={"scope": "filtered", "basis": "llm"})

            self.assertEqual(accept_response.status_code, 200)
            action = accept_response.json()["action"]
            self.assertEqual(action["basis"], "llm")
            self.assertEqual(action["scope"], "filtered")
            self.assertEqual(action["accepted"], 2)
            self.assertEqual(action["skipped"], 1)
            self.assertEqual([mark["fileId"] for mark in action["beforeMarks"]], ["image-2", "image-1"])
            marks = photo_curation.load_photo_marks(cache_path, ["image-1", "image-2", "image-3"])
            self.assertEqual(marks["image-1"].rating, 4)
            self.assertEqual(marks["image-1"].status, "pick")
            self.assertEqual(marks["image-1"].source, "llm_batch")
            self.assertAlmostEqual(float(marks["image-1"].accepted_score or 0), 8.2)
            self.assertEqual(marks["image-2"].rating, 3)
            self.assertEqual(marks["image-2"].status, "reject")
            self.assertEqual(marks["image-2"].source, "llm_batch")
            self.assertAlmostEqual(float(marks["image-2"].accepted_score or 0), 5.2)
            self.assertNotIn("image-3", marks)
            history = load_curation_actions(cache_path, limit=1)
            self.assertEqual(history[0].id, action["historyId"])
            self.assertEqual(history[0].kind, "accept")
            self.assertEqual(history[0].summary, "大模型采纳 2 张")

            export_dir = Path(tmp) / "exported"
            export_dir.mkdir()
            preflight_response = client.post("/api/export/preflight", json={"destination": str(export_dir)})
            copied_response = client.post("/api/export/selected-files", json={"destination": str(export_dir)})

            self.assertEqual(preflight_response.status_code, 200)
            self.assertEqual(preflight_response.json()["total"], 1)
            self.assertEqual(preflight_response.json()["ready"], 1)
            self.assertEqual(copied_response.status_code, 200)
            self.assertEqual(copied_response.json()["copied"], 1)
            self.assertEqual(copied_response.json()["skipped"], 0)
            self.assertEqual(copied_response.json()["copiedFiles"], [str(export_dir / pick_path.name)])
            self.assertTrue((export_dir / pick_path.name).exists())
            self.assertFalse((export_dir / reject_path.name).exists())

            undo_response = client.post("/api/curation/undo", json={"historyId": action["historyId"]})
            history_response = client.get("/api/curation/history?limit=2")
            no_picks_response = client.post("/api/export/selected-files", json={"destination": str(export_dir)})

            self.assertEqual(undo_response.status_code, 200)
            self.assertEqual(undo_response.json()["action"]["restored"], 2)
            self.assertEqual(undo_response.json()["action"]["undoneKind"], "accept")
            restored_marks = photo_curation.load_photo_marks(cache_path, ["image-1", "image-2", "image-3"])
            self.assertNotIn("image-1", restored_marks)
            self.assertNotIn("image-2", restored_marks)
            self.assertNotIn("image-3", restored_marks)
            self.assertEqual(history_response.status_code, 200)
            self.assertEqual(history_response.json()["actions"][0]["undoState"], "undo")
            self.assertEqual(history_response.json()["actions"][1]["undoState"], "undone")
            self.assertEqual(no_picks_response.status_code, 400)
            self.assertEqual(no_picks_response.json()["errorCode"], "exportNoPicks")

    def test_accept_marks_can_apply_to_selected_photo_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = str(Path(tmp) / "scores.sqlite")
            source_df = pd.DataFrame(
                [
                    {
                        "file_id": "image-1",
                        "path": "/photos/a.jpg",
                        "folder": "/photos",
                        "filename": "a.jpg",
                        "error": "",
                        "overall_0_10": 8.4,
                    },
                    {
                        "file_id": "image-2",
                        "path": "/photos/b.jpg",
                        "folder": "/photos",
                        "filename": "b.jpg",
                        "error": "",
                        "overall_0_10": 7.6,
                    },
                    {
                        "file_id": "image-3",
                        "path": "/photos/c.jpg",
                        "folder": "/photos",
                        "filename": "c.jpg",
                        "error": "",
                        "overall_0_10": 5.1,
                    },
                ]
            )
            store = AppStateStore(
                create_initial_state(
                    scores_df=source_df,
                    default_photo_dirs=["/photos"],
                    default_cache_path=cache_path,
                    filter_defaults=culvia_app.FILTER_DEFAULTS,
                    default_selected_models=[scoring.MODEL_CORE_AESTHETIC],
                )
            )
            with store.lock:
                store.data["filters"]["minScore"] = 7.0
            client = TestClient(culvia_app.create_app(store))

            response = client.post(
                "/api/mark/accept", json={"scope": "selected", "fileIds": ["image-2"], "basis": "model"}
            )

            self.assertEqual(response.status_code, 200)
            action = response.json()["action"]
            self.assertEqual(action["accepted"], 1)
            self.assertEqual(action["scope"], "selected")
            self.assertEqual(action["beforeMarks"][0]["fileId"], "image-2")
            marks = photo_curation.load_photo_marks(cache_path, ["image-1", "image-2", "image-3"])
            self.assertNotIn("image-1", marks)
            self.assertEqual(marks["image-2"].rating, 4)
            self.assertEqual(marks["image-2"].status, "pick")
            self.assertAlmostEqual(float(marks["image-2"].accepted_score or 0), 7.6)
            self.assertNotIn("image-3", marks)

    def test_curation_mark_routes_return_stable_target_error_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = str(Path(tmp) / "scores.sqlite")
            source_df = pd.DataFrame(
                [
                    {
                        "file_id": "image-1",
                        "path": "/photos/a.jpg",
                        "folder": "/photos",
                        "filename": "a.jpg",
                        "error": "",
                        "overall_0_10": 8.4,
                    },
                    {
                        "file_id": "image-2",
                        "path": "/photos/b.jpg",
                        "folder": "/photos",
                        "filename": "b.jpg",
                        "error": "",
                        "overall_0_10": 7.6,
                    },
                ]
            )
            store = AppStateStore(
                create_initial_state(
                    scores_df=source_df,
                    default_photo_dirs=["/photos"],
                    default_cache_path=cache_path,
                    filter_defaults=culvia_app.FILTER_DEFAULTS,
                    default_selected_models=[scoring.MODEL_CORE_AESTHETIC],
                )
            )
            client = TestClient(culvia_app.create_app(store))

            color_selected = client.post(
                "/api/mark/color", json={"scope": "selected", "fileIds": ["missing"], "colorLabel": "red"}
            )
            status_selected = client.post(
                "/api/mark/status", json={"scope": "selected", "fileIds": [], "status": "pick"}
            )
            accept_selected = client.post(
                "/api/mark/accept", json={"scope": "selected", "fileIds": ["missing"], "basis": "model"}
            )
            missing_current = client.post("/api/mark/status", json={"status": "pick"})
            unknown_current = client.post("/api/mark/accept", json={"fileId": "missing", "basis": "model"})
            restore_missing = client.post("/api/mark/restore", json={"marks": []})

        for response in (color_selected, status_selected, accept_selected):
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["errorCode"], "selectedPhotosMissing")
            self.assertEqual(response.json()["errorParams"]["scope"], "selected")

        self.assertEqual(missing_current.status_code, 400)
        self.assertEqual(missing_current.json()["errorCode"], "photoIdMissing")
        self.assertEqual(unknown_current.status_code, 404)
        self.assertEqual(unknown_current.json()["errorCode"], "photoNotFound")
        self.assertEqual(restore_missing.status_code, 400)
        self.assertEqual(restore_missing.json()["errorCode"], "restoreMarksMissing")

    def test_injected_state_store_serves_media_and_reveal_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "photos"
            root.mkdir()
            allowed = make_test_image(root / "allowed.jpg")
            broken = root / "broken.jpg"
            broken.write_text("not an image", encoding="utf-8")
            scored_outside = make_test_image(Path(tmp) / "scored.jpg")
            denied = make_test_image(Path(tmp) / "denied.jpg")
            cache_path = str(Path(tmp) / "scores.sqlite")
            source_df = pd.DataFrame(
                [
                    {
                        "file_id": "scored-image",
                        "path": str(scored_outside),
                        "folder": str(scored_outside.parent),
                        "filename": scored_outside.name,
                        "error": "",
                        "overall_0_10": 8.0,
                    }
                ]
            )
            store = AppStateStore(
                create_initial_state(
                    scores_df=source_df,
                    default_photo_dirs=[str(root)],
                    default_cache_path=cache_path,
                    filter_defaults=culvia_app.FILTER_DEFAULTS,
                    default_selected_models=[scoring.MODEL_CORE_AESTHETIC],
                )
            )
            with culvia_app.STATE_LOCK:
                original_global_scores = culvia_app.STATE["scores_df"].copy()
                original_global_source = deepcopy(culvia_app.STATE["source"])
            client = TestClient(culvia_app.create_app(store))

            allowed_response = client.get("/api/image", params={"path": str(allowed), "max": "120"})
            scored_response = client.get("/api/image", params={"file_id": "scored-image", "max": "120"})
            denied_response = client.get("/api/image", params={"path": str(denied), "max": "120"})
            missing_response = client.get("/api/image", params={"path": str(Path(tmp) / "missing.jpg"), "max": "120"})
            thumbnail_response = client.get("/api/thumbnail", params={"file_id": "scored-image", "max": "120"})
            thumbnail_denied_response = client.get("/api/thumbnail", params={"path": str(denied), "max": "120"})
            denied_json_response = client.get(
                "/api/image",
                params={"path": str(denied), "max": "120"},
                headers={"Accept": "application/json"},
            )
            denied_json_q0_response = client.get(
                "/api/image",
                params={"path": str(denied), "max": "120"},
                headers={"Accept": "application/json;q=0, image/*;q=1"},
            )
            image_json_success_response = client.get(
                "/api/image",
                params={"path": str(allowed), "max": "120"},
                headers={"Accept": "application/json"},
            )
            image_generation_json_response = client.get(
                "/api/image",
                params={"path": str(broken), "max": "120"},
                headers={"Accept": "application/json"},
            )
            missing_json_response = client.get(
                "/api/image",
                params={"path": str(Path(tmp) / "missing.jpg"), "max": "120"},
                headers={"Accept": "application/json"},
            )
            thumbnail_denied_json_response = client.get(
                "/api/thumbnail",
                params={"path": str(denied), "max": "120"},
                headers={"Accept": "application/json"},
            )
            with (
                patch("culvia.capabilities.sys.platform", "darwin"),
                patch(
                    "culvia.capabilities.shutil.which",
                    return_value="/usr/bin/open",
                ),
                patch("culvia.desktop_files.subprocess.run") as run,
            ):
                reveal_response = client.post("/api/reveal", json={"path": str(scored_outside)})

            self.assertEqual(allowed_response.status_code, 200)
            self.assertEqual(scored_response.status_code, 200)
            self.assertEqual(denied_response.status_code, 403)
            self.assertEqual(denied_response.text, "image access denied")
            self.assertEqual(missing_response.status_code, 404)
            self.assertEqual(missing_response.text, "image not found")
            self.assertEqual(thumbnail_response.status_code, 200)
            self.assertEqual(thumbnail_denied_response.status_code, 403)
            self.assertEqual(thumbnail_denied_response.text, "thumbnail access denied")
            self.assertEqual(denied_json_response.status_code, 403)
            self.assertEqual(denied_json_response.json()["errorCode"], "imageAccessDenied")
            self.assertEqual(denied_json_response.headers["vary"], "Accept")
            self.assertEqual(denied_json_q0_response.status_code, 403)
            self.assertEqual(denied_json_q0_response.text, "image access denied")
            self.assertEqual(image_json_success_response.status_code, 200)
            self.assertEqual(image_json_success_response.headers["content-type"], "image/jpeg")
            self.assertEqual(image_generation_json_response.status_code, 500)
            self.assertEqual(image_generation_json_response.json()["errorCode"], "imageGenerationFailed")
            self.assertEqual(missing_json_response.status_code, 404)
            self.assertEqual(missing_json_response.json()["errorCode"], "mediaNotFound")
            self.assertEqual(thumbnail_denied_json_response.status_code, 403)
            self.assertEqual(thumbnail_denied_json_response.json()["errorCode"], "thumbnailAccessDenied")
            self.assertEqual(reveal_response.status_code, 200)
            run.assert_called_once()
            with culvia_app.STATE_LOCK:
                self.assertTrue(culvia_app.STATE["scores_df"].equals(original_global_scores))
                self.assertEqual(culvia_app.STATE["source"], original_global_source)

    def test_capabilities_report_local_environment(self) -> None:
        with (
            patch("culvia.capabilities.sys.platform", "linux"),
            patch("culvia.capabilities.shutil.which", return_value=None),
        ):
            response = self._client.get("/api/capabilities")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["mode"], "local")
        self.assertEqual(payload["platform"], "linux")
        self.assertTrue(payload["web"])
        self.assertFalse(payload["nativeFolderPicker"])
        self.assertFalse(payload["revealInFileManager"])

    def test_state_payload_includes_capabilities(self) -> None:
        response = self._client.get("/api/state")

        self.assertEqual(response.status_code, 200)
        capabilities = response.json()["capabilities"]
        self.assertEqual(capabilities["mode"], "local")
        self.assertIn("nativeFolderPicker", capabilities)
        self.assertIn("revealInFileManager", capabilities)

    def test_native_folder_picker_has_predictable_unsupported_response(self) -> None:
        with (
            patch("culvia.capabilities.sys.platform", "linux"),
            patch("culvia.capabilities.shutil.which", return_value=None),
            patch(
                "culvia.desktop_files.subprocess.run",
            ) as run,
        ):
            response = self._client.post("/api/pick-folder", json={})

        self.assertEqual(response.status_code, 501)
        self.assertIn("目录路径", response.json()["error"])
        self.assertEqual(response.json()["errorCode"], "desktopActionUnsupported")
        run.assert_not_called()

    def test_native_folder_picker_cancel_returns_stable_error_code(self) -> None:
        with patch(
            "culvia_app.choose_folder_path", side_effect=culvia_app.DesktopActionCancelled("用户取消了目录选择。")
        ):
            response = self._client.post("/api/pick-export-folder", json={})

        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.json()["cancelled"])
        self.assertEqual(response.json()["errorCode"], "desktopActionCancelled")
        self.assertEqual(response.json()["errorParams"]["reason"], "用户取消了目录选择。")

    def test_reveal_rejects_files_outside_current_photo_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "outside.jpg"
            path.write_bytes(b"not really an image")
            original_source = dict(culvia_app.STATE["source"])
            original_scores = culvia_app.STATE["scores_df"].copy()
            try:
                with culvia_app.STATE_LOCK:
                    culvia_app.STATE["source"].update({"mode": "folders", "folders": [], "uploadedPaths": []})
                    culvia_app.STATE["scores_df"] = pd.DataFrame(columns=scoring.CSV_COLUMNS)
                with (
                    patch("culvia.capabilities.sys.platform", "darwin"),
                    patch("culvia.capabilities.shutil.which", return_value="/usr/bin/open"),
                ):
                    response = self._client.post("/api/reveal", json={"path": str(path)})
            finally:
                with culvia_app.STATE_LOCK:
                    culvia_app.STATE["source"].clear()
                    culvia_app.STATE["source"].update(original_source)
                    culvia_app.STATE["scores_df"] = original_scores

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["errorCode"], "revealOutsideSource")

    def test_reveal_allows_export_destination_directories_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            export_dir = Path(tmp) / "export"
            export_dir.mkdir()
            export_file = export_dir / "photo.jpg"
            export_file.write_bytes(b"photo")
            with (
                patch("culvia.capabilities.sys.platform", "darwin"),
                patch(
                    "culvia.capabilities.shutil.which",
                    return_value="/usr/bin/open",
                ),
                patch("culvia.desktop_files.subprocess.run") as run,
            ):
                directory_response = self._client.post(
                    "/api/reveal",
                    json={"path": str(export_dir), "purpose": "export"},
                )
                file_response = self._client.post(
                    "/api/reveal",
                    json={"path": str(export_file), "purpose": "export"},
                )

        self.assertEqual(directory_response.status_code, 200)
        self.assertEqual(file_response.status_code, 400)
        self.assertEqual(file_response.json()["errorCode"], "exportDestinationNotDirectory")
        run.assert_called_once()

    def test_export_errors_use_stable_codes(self) -> None:
        missing_destination = self._client.post("/api/export/preflight", json={"destination": ""})

        self.assertEqual(missing_destination.status_code, 400)
        self.assertEqual(missing_destination.json()["errorCode"], "exportDestinationRequired")

        with tempfile.TemporaryDirectory() as tmp:
            export_dir = Path(tmp) / "export"
            store = AppStateStore(
                create_initial_state(
                    scores_df=pd.DataFrame(columns=scoring.CSV_COLUMNS),
                    default_photo_dirs=[],
                    default_cache_path=str(Path(tmp) / "scores.sqlite"),
                    filter_defaults=culvia_app.FILTER_DEFAULTS,
                    default_selected_models=[scoring.MODEL_CORE_AESTHETIC],
                )
            )
            client = TestClient(culvia_app.create_app(store))
            no_picks = client.post("/api/export/selected-files", json={"destination": str(export_dir)})

        self.assertEqual(no_picks.status_code, 400)
        self.assertEqual(no_picks.json()["errorCode"], "exportNoPicks")

    def test_state_payload_masks_or_omits_api_key(self) -> None:
        sentinel = "unit-test-api-key-should-never-leak"
        original_session = dict(scoring.SESSION_LLM_CONFIG)
        original_persisted = dict(scoring.PERSISTED_LLM_CONFIG)
        env_keys = [scoring.ENV_LLM_API_KEY, "OPENAI_API_KEY"]
        original_env = {key: os.environ.get(key) for key in env_keys}
        try:
            for key in env_keys:
                os.environ.pop(key, None)
            scoring.clear_session_llm_config()
            scoring.set_persisted_llm_config({})
            scoring.set_session_llm_config({"api_key": sentinel})

            response = self._client.get("/api/state")

            self.assertEqual(response.status_code, 200)
            body = response.text
            self.assertNotIn(sentinel, body)
            self.assertIn("unit****leak", body)
        finally:
            scoring.clear_session_llm_config()
            scoring.set_session_llm_config(original_session, replace=True)
            scoring.set_persisted_llm_config(original_persisted)
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_llm_model_list_request_never_echoes_key(self) -> None:
        sentinel = "unit-test-api-key-should-never-leak"
        with patch("culvia_app.requests.get") as mocked_get:
            mocked_get.return_value.status_code = 200
            mocked_get.return_value.json.return_value = {"data": [{"id": "mock-vlm"}]}

            response = self._client.post(
                "/api/llm-models",
                json={
                    "apiKey": sentinel,
                    "baseUrl": "https://example.test/v1",
                    "model": "mock-vlm",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(sentinel, response.text)
        mocked_get.assert_called_once()
        self.assertEqual(mocked_get.call_args.kwargs["headers"]["Authorization"], f"Bearer {sentinel}")

    def test_llm_model_list_error_uses_stable_code_without_request(self) -> None:
        with patch("culvia_app.requests.get") as mocked_get:
            response = self._client.post("/api/llm-models", json={"apiKey": "", "baseUrl": "https://example.test/v1"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["errorCode"], "llmModelListInvalid")
        self.assertIn("reason", response.json()["errorParams"])
        mocked_get.assert_not_called()

    def test_score_start_reserves_job_slot_before_thread_runs(self) -> None:
        class FakeThread:
            created: list["FakeThread"] = []

            def __init__(self, *args, **kwargs) -> None:
                self.args = args
                self.kwargs = kwargs
                self.started = False
                FakeThread.created.append(self)

            def start(self) -> None:
                self.started = True

        with culvia_app.STATE_LOCK:
            original_job = deepcopy(culvia_app.STATE["job"])
            culvia_app.STATE["job"] = culvia_app.empty_job()
        try:
            with patch("culvia_app.threading.Thread", FakeThread):
                first = self._client.post("/api/score", json={"mode": "folders", "folders": []})
                second = self._client.post("/api/score", json={"mode": "folders", "folders": []})

            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 409)
            job_id = first.json()["jobId"]
            self.assertTrue(job_id)
            self.assertEqual(len(FakeThread.created), 1)
            self.assertTrue(FakeThread.created[0].started)
            self.assertEqual(FakeThread.created[0].kwargs["args"][0], job_id)
            self.assertEqual(FakeThread.created[0].kwargs["args"][2], culvia_app.APP_STATE)
            self.assertEqual(FakeThread.created[0].kwargs["args"][3], culvia_app.APP_JOB_SERVICE)
            with culvia_app.STATE_LOCK:
                self.assertTrue(culvia_app.STATE["job"]["running"])
                self.assertEqual(culvia_app.STATE["job"]["phase"], "queued")
                self.assertEqual(culvia_app.STATE["job"]["jobId"], job_id)
        finally:
            with culvia_app.STATE_LOCK:
                culvia_app.STATE["job"] = original_job
            culvia_app.reset_job_control()

    def test_injected_state_store_serves_score_start_route(self) -> None:
        class FakeThread:
            created: list["FakeThread"] = []

            def __init__(self, *args, **kwargs) -> None:
                self.args = args
                self.kwargs = kwargs
                self.started = False
                FakeThread.created.append(self)

            def start(self) -> None:
                self.started = True

        with tempfile.TemporaryDirectory() as tmp:
            store = AppStateStore(
                create_initial_state(
                    scores_df=pd.DataFrame(columns=scoring.CSV_COLUMNS),
                    default_photo_dirs=["/injected/photos"],
                    default_cache_path=str(Path(tmp) / "scores.sqlite"),
                    filter_defaults=culvia_app.FILTER_DEFAULTS,
                    default_selected_models=[scoring.MODEL_CORE_AESTHETIC],
                )
            )
            web_app = culvia_app.create_app(store)
            with culvia_app.STATE_LOCK:
                original_global_job = deepcopy(culvia_app.STATE["job"])
            client = TestClient(web_app)
            try:
                with patch("culvia_app.threading.Thread", FakeThread):
                    first = client.post("/api/score", json={"mode": "folders", "folders": []})
                    second = client.post("/api/score", json={"mode": "folders", "folders": []})

                self.assertEqual(first.status_code, 200)
                self.assertEqual(second.status_code, 409)
                job_id = first.json()["jobId"]
                self.assertEqual(len(FakeThread.created), 1)
                self.assertTrue(FakeThread.created[0].started)
                self.assertEqual(FakeThread.created[0].kwargs["args"][0], job_id)
                self.assertEqual(FakeThread.created[0].kwargs["args"][2], store)
                self.assertEqual(FakeThread.created[0].kwargs["args"][3], web_app.state.job_service)
                with store.lock:
                    self.assertTrue(store.data["job"]["running"])
                    self.assertEqual(store.data["job"]["phase"], "queued")
                    self.assertEqual(store.data["job"]["jobId"], job_id)
                with culvia_app.STATE_LOCK:
                    self.assertEqual(culvia_app.STATE["job"], original_global_job)
            finally:
                web_app.state.job_service.reset_control()

    def test_run_scoring_job_empty_source_uses_injected_state_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = str(Path(tmp) / "scores.sqlite")
            store = AppStateStore(
                create_initial_state(
                    scores_df=pd.DataFrame(
                        [
                            {
                                "file_id": "stale",
                                "path": "/photos/stale.jpg",
                                "folder": "/photos",
                                "filename": "stale.jpg",
                                "error": "",
                                "overall_0_10": 9.0,
                            }
                        ]
                    ),
                    default_photo_dirs=["/injected/photos"],
                    default_cache_path=cache_path,
                    filter_defaults=culvia_app.FILTER_DEFAULTS,
                    default_selected_models=[scoring.MODEL_CORE_AESTHETIC],
                )
            )
            web_app = culvia_app.create_app(store)
            job_service = web_app.state.job_service
            job_id = job_service.reserve()
            self.assertTrue(job_id)
            with culvia_app.STATE_LOCK:
                original_global_scores = culvia_app.STATE["scores_df"].copy()
                original_global_source = deepcopy(culvia_app.STATE["source"])
                original_global_job = deepcopy(culvia_app.STATE["job"])

            culvia_app.run_scoring_job(
                job_id,
                {"mode": "folders", "folders": [], "cachePath": cache_path},
                store,
                job_service,
            )

            with store.lock:
                self.assertTrue(scoring.normalize_score_dataframe(store.data["scores_df"]).empty)
                self.assertEqual(store.data["source"]["cachePath"], cache_path)
                self.assertEqual(store.data["job"]["phase"], "empty")
                self.assertFalse(store.data["job"]["running"])
            with culvia_app.STATE_LOCK:
                self.assertTrue(culvia_app.STATE["scores_df"].equals(original_global_scores))
                self.assertEqual(culvia_app.STATE["source"], original_global_source)
                self.assertEqual(culvia_app.STATE["job"], original_global_job)

    def test_stale_job_thread_cannot_update_new_job_state(self) -> None:
        with culvia_app.STATE_LOCK:
            original_job = deepcopy(culvia_app.STATE["job"])
            culvia_app.STATE["job"] = culvia_app.empty_job()
            culvia_app.STATE["job"].update({"jobId": "current-job", "running": True, "title": "当前任务"})
        try:
            culvia_app.bind_thread_job("stale-job")
            culvia_app.update_job(title="过期任务")

            with culvia_app.STATE_LOCK:
                self.assertEqual(culvia_app.STATE["job"]["title"], "当前任务")
        finally:
            culvia_app.clear_thread_job()
            with culvia_app.STATE_LOCK:
                culvia_app.STATE["job"] = original_job
            culvia_app.reset_job_control()

    def test_batch_color_marks_current_filtered_photos_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = str(Path(tmp) / "scores.sqlite")
            source_df = pd.DataFrame(
                [
                    {
                        "file_id": "image-1",
                        "path": "/photos/a.jpg",
                        "folder": "/photos",
                        "filename": "a.jpg",
                        "error": "",
                        "overall_0_10": 8.4,
                    },
                    {
                        "file_id": "image-2",
                        "path": "/photos/b.jpg",
                        "folder": "/photos",
                        "filename": "b.jpg",
                        "error": "",
                        "overall_0_10": 7.1,
                    },
                    {
                        "file_id": "image-3",
                        "path": "/photos/c.jpg",
                        "folder": "/photos",
                        "filename": "c.jpg",
                        "error": "",
                        "overall_0_10": 5.8,
                    },
                ]
            )
            original_source = dict(culvia_app.STATE["source"])
            original_filters = deepcopy(culvia_app.STATE["filters"])
            original_scores = culvia_app.STATE["scores_df"].copy()
            try:
                photo_curation.save_photo_mark(cache_path, "image-1", rating=5, status="pick", accepted_score=8.8)
                with culvia_app.STATE_LOCK:
                    culvia_app.STATE["scores_df"] = source_df
                    culvia_app.STATE["source"].update(
                        {"mode": "folders", "folders": ["/photos"], "cachePath": cache_path}
                    )
                    culvia_app.STATE["filters"].update({"minScore": 7.0, "limit": 80, "colorLabel": "all"})

                response = self._client.post("/api/mark/color", json={"scope": "filtered", "colorLabel": "green"})

                self.assertEqual(response.status_code, 200)
                action = response.json()["action"]
                self.assertEqual(action["colored"], 2)
                self.assertEqual(len(action["beforeMarks"]), 2)
                self.assertEqual(action["beforeMarks"][0]["fileId"], "image-1")
                self.assertEqual(action["beforeMarks"][0]["status"], "pick")
                self.assertEqual(action["beforeMarks"][1]["fileId"], "image-2")
                self.assertEqual(action["beforeMarks"][1]["colorLabel"], "")
                marks = photo_curation.load_photo_marks(cache_path, ["image-1", "image-2", "image-3"])
                self.assertEqual(marks["image-1"].color_label, "green")
                self.assertEqual(marks["image-2"].color_label, "green")
                self.assertNotIn("image-3", marks)
                self.assertEqual(marks["image-1"].rating, 5)
                self.assertAlmostEqual(float(marks["image-1"].accepted_score or 0), 8.8)
                restore_response = self._client.post("/api/mark/restore", json={"marks": action["beforeMarks"]})
                self.assertEqual(restore_response.status_code, 200)
                restored_marks = photo_curation.load_photo_marks(cache_path, ["image-1", "image-2", "image-3"])
                self.assertEqual(restored_marks["image-1"].status, "pick")
                self.assertEqual(restored_marks["image-1"].color_label, "")
                self.assertAlmostEqual(float(restored_marks["image-1"].accepted_score or 0), 8.8)
                self.assertNotIn("image-2", restored_marks)
                self.assertNotIn("image-3", restored_marks)
            finally:
                with culvia_app.STATE_LOCK:
                    culvia_app.STATE["source"].clear()
                    culvia_app.STATE["source"].update(original_source)
                    culvia_app.STATE["filters"].clear()
                    culvia_app.STATE["filters"].update(original_filters)
                    culvia_app.STATE["scores_df"] = original_scores

    def test_batch_color_can_mark_selected_photo_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = str(Path(tmp) / "scores.sqlite")
            source_df = pd.DataFrame(
                [
                    {
                        "file_id": "image-1",
                        "path": "/photos/a.jpg",
                        "folder": "/photos",
                        "filename": "a.jpg",
                        "error": "",
                        "overall_0_10": 8.4,
                    },
                    {
                        "file_id": "image-2",
                        "path": "/photos/b.jpg",
                        "folder": "/photos",
                        "filename": "b.jpg",
                        "error": "",
                        "overall_0_10": 7.1,
                    },
                    {
                        "file_id": "image-3",
                        "path": "/photos/c.jpg",
                        "folder": "/photos",
                        "filename": "c.jpg",
                        "error": "",
                        "overall_0_10": 5.8,
                    },
                ]
            )
            original_source = dict(culvia_app.STATE["source"])
            original_filters = deepcopy(culvia_app.STATE["filters"])
            original_scores = culvia_app.STATE["scores_df"].copy()
            try:
                with culvia_app.STATE_LOCK:
                    culvia_app.STATE["scores_df"] = source_df
                    culvia_app.STATE["source"].update(
                        {"mode": "folders", "folders": ["/photos"], "cachePath": cache_path}
                    )
                    culvia_app.STATE["filters"].update({"minScore": 7.0, "limit": 80, "colorLabel": "all"})

                response = self._client.post(
                    "/api/mark/color",
                    json={"scope": "selected", "fileIds": ["image-2", "image-3"], "colorLabel": "blue"},
                )

                self.assertEqual(response.status_code, 200)
                action = response.json()["action"]
                self.assertEqual(action["scope"], "selected")
                self.assertEqual(action["colored"], 2)
                marks = photo_curation.load_photo_marks(cache_path, ["image-1", "image-2", "image-3"])
                self.assertNotIn("image-1", marks)
                self.assertEqual(marks["image-2"].color_label, "blue")
                self.assertEqual(marks["image-3"].color_label, "blue")
            finally:
                with culvia_app.STATE_LOCK:
                    culvia_app.STATE["source"].clear()
                    culvia_app.STATE["source"].update(original_source)
                    culvia_app.STATE["filters"].clear()
                    culvia_app.STATE["filters"].update(original_filters)
                    culvia_app.STATE["scores_df"] = original_scores

    def test_batch_status_marks_current_filtered_photos_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = str(Path(tmp) / "scores.sqlite")
            source_df = pd.DataFrame(
                [
                    {
                        "file_id": "image-1",
                        "path": "/photos/a.jpg",
                        "folder": "/photos",
                        "filename": "a.jpg",
                        "error": "",
                        "overall_0_10": 8.4,
                    },
                    {
                        "file_id": "image-2",
                        "path": "/photos/b.jpg",
                        "folder": "/photos",
                        "filename": "b.jpg",
                        "error": "",
                        "overall_0_10": 7.1,
                    },
                    {
                        "file_id": "image-3",
                        "path": "/photos/c.jpg",
                        "folder": "/photos",
                        "filename": "c.jpg",
                        "error": "",
                        "overall_0_10": 5.8,
                    },
                ]
            )
            original_source = dict(culvia_app.STATE["source"])
            original_filters = deepcopy(culvia_app.STATE["filters"])
            original_scores = culvia_app.STATE["scores_df"].copy()
            try:
                photo_curation.save_photo_mark(
                    cache_path,
                    "image-1",
                    rating=5,
                    status="pick",
                    color_label="green",
                    accepted_score=8.8,
                )
                with culvia_app.STATE_LOCK:
                    culvia_app.STATE["scores_df"] = source_df
                    culvia_app.STATE["source"].update(
                        {"mode": "folders", "folders": ["/photos"], "cachePath": cache_path}
                    )
                    culvia_app.STATE["filters"].update({"minScore": 7.0, "limit": 80, "colorLabel": "all"})

                response = self._client.post("/api/mark/status", json={"scope": "filtered", "status": "reject"})

                self.assertEqual(response.status_code, 200)
                action = response.json()["action"]
                self.assertEqual(action["marked"], 2)
                self.assertEqual(action["statusLabel"], "淘汰")
                self.assertEqual(len(action["beforeMarks"]), 2)
                self.assertEqual(action["beforeMarks"][0]["fileId"], "image-1")
                self.assertEqual(action["beforeMarks"][0]["status"], "pick")
                self.assertEqual(action["beforeMarks"][0]["colorLabel"], "green")
                self.assertEqual(action["beforeMarks"][1]["fileId"], "image-2")
                self.assertEqual(action["beforeMarks"][1]["status"], "")
                history = load_curation_actions(cache_path)
                self.assertEqual(history[0].id, action["historyId"])
                self.assertEqual(history[0].kind, "status")
                self.assertEqual(history[0].payload["marked"], 2)
                self.assertEqual(history[0].payload["beforeMarks"], action["beforeMarks"])
                self.assertEqual(history[0].payload["afterMarks"], action["afterMarks"])
                self.assertEqual(action["afterMarks"][0]["status"], "reject")
                history_response = self._client.get("/api/curation/history?limit=1")
                self.assertEqual(history_response.status_code, 200)
                self.assertEqual(history_response.json()["actions"][0]["id"], action["historyId"])
                self.assertEqual(history_response.json()["actions"][0]["summary"], "淘汰 2 张")
                self.assertEqual(history_response.json()["actions"][0]["undoState"], "available")
                marks = photo_curation.load_photo_marks(cache_path, ["image-1", "image-2", "image-3"])
                self.assertEqual(marks["image-1"].status, "reject")
                self.assertEqual(marks["image-2"].status, "reject")
                self.assertNotIn("image-3", marks)
                self.assertEqual(marks["image-1"].rating, 5)
                self.assertEqual(marks["image-1"].color_label, "green")
                self.assertIsNone(marks["image-1"].accepted_score)

                restore_response = self._client.post("/api/curation/undo", json={"historyId": action["historyId"]})

                self.assertEqual(restore_response.status_code, 200)
                self.assertEqual(restore_response.json()["action"]["restored"], 2)
                self.assertEqual(restore_response.json()["action"]["targetHistoryId"], action["historyId"])
                self.assertEqual(restore_response.json()["action"]["undoneHistoryId"], action["historyId"])
                self.assertEqual(restore_response.json()["action"]["undoneKind"], "status")
                undo_history = load_curation_actions(cache_path, limit=2)
                self.assertEqual(undo_history[0].kind, "undo")
                self.assertEqual(undo_history[0].payload["targetHistoryId"], action["historyId"])
                self.assertEqual(undo_history[0].payload["undoneHistoryId"], action["historyId"])
                self.assertEqual(undo_history[0].payload["beforeMarks"][0]["status"], "reject")
                self.assertEqual(undo_history[0].payload["afterMarks"][0]["status"], "pick")
                history_after_undo_response = self._client.get("/api/curation/history?limit=2")
                self.assertEqual(history_after_undo_response.status_code, 200)
                history_after_undo = history_after_undo_response.json()["actions"]
                self.assertEqual(history_after_undo[0]["undoState"], "undo")
                self.assertEqual(history_after_undo[1]["undoState"], "undone")
                restored_marks = photo_curation.load_photo_marks(cache_path, ["image-1", "image-2", "image-3"])
                self.assertEqual(restored_marks["image-1"].status, "pick")
                self.assertEqual(restored_marks["image-1"].rating, 5)
                self.assertEqual(restored_marks["image-1"].color_label, "green")
                self.assertAlmostEqual(float(restored_marks["image-1"].accepted_score or 0), 8.8)
                self.assertNotIn("image-2", restored_marks)
                self.assertNotIn("image-3", restored_marks)
                repeated_restore_response = self._client.post(
                    "/api/curation/undo", json={"historyId": action["historyId"]}
                )
                self.assertEqual(repeated_restore_response.status_code, 409)
                self.assertEqual(repeated_restore_response.json()["errorCode"], "curationUndoAlreadyUndone")
                latest_restore_response = self._client.post("/api/curation/undo", json={})
                self.assertEqual(latest_restore_response.status_code, 404)
                self.assertEqual(latest_restore_response.json()["errorCode"], "curationUndoNoRestorableAction")
                missing_history_response = self._client.post(
                    "/api/curation/undo", json={"historyId": "missing-history-id"}
                )
                self.assertEqual(missing_history_response.status_code, 404)
                self.assertEqual(missing_history_response.json()["errorCode"], "curationUndoNotFound")

                clear_response = self._client.post(
                    "/api/mark/restore",
                    json={
                        "marks": [
                            {
                                "fileId": "image-1",
                                "rating": 0,
                                "status": "",
                                "colorLabel": "",
                                "note": "",
                                "source": "manual",
                                "acceptedScore": None,
                            }
                        ]
                    },
                )

                self.assertEqual(clear_response.status_code, 200)
                cleared_marks = photo_curation.load_photo_marks(cache_path, ["image-1", "image-2", "image-3"])
                self.assertNotIn("image-1", cleared_marks)
            finally:
                with culvia_app.STATE_LOCK:
                    culvia_app.STATE["source"].clear()
                    culvia_app.STATE["source"].update(original_source)
                    culvia_app.STATE["filters"].clear()
                    culvia_app.STATE["filters"].update(original_filters)
                    culvia_app.STATE["scores_df"] = original_scores

    def test_curation_undo_rejects_conflicting_later_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = str(Path(tmp) / "scores.sqlite")
            source_df = pd.DataFrame(
                [
                    {
                        "file_id": "image-1",
                        "path": "/photos/a.jpg",
                        "folder": "/photos",
                        "filename": "a.jpg",
                        "error": "",
                        "overall_0_10": 8.4,
                    },
                    {
                        "file_id": "image-2",
                        "path": "/photos/b.jpg",
                        "folder": "/photos",
                        "filename": "b.jpg",
                        "error": "",
                        "overall_0_10": 7.1,
                    },
                ]
            )
            original_source = dict(culvia_app.STATE["source"])
            original_filters = deepcopy(culvia_app.STATE["filters"])
            original_scores = culvia_app.STATE["scores_df"].copy()
            try:
                with culvia_app.STATE_LOCK:
                    culvia_app.STATE["scores_df"] = source_df
                    culvia_app.STATE["source"].update(
                        {"mode": "folders", "folders": ["/photos"], "cachePath": cache_path}
                    )
                    culvia_app.STATE["filters"].update({"minScore": 7.0, "limit": 80, "colorLabel": "all"})

                response = self._client.post("/api/mark/status", json={"scope": "filtered", "status": "reject"})
                self.assertEqual(response.status_code, 200)
                action = response.json()["action"]
                photo_curation.save_photo_mark(cache_path, "image-1", status="pick")

                undo_response = self._client.post("/api/curation/undo", json={"historyId": action["historyId"]})

                self.assertEqual(undo_response.status_code, 409)
                self.assertEqual(undo_response.json()["errorCode"], "curationUndoConflict")
                self.assertEqual(undo_response.json()["errorParams"]["conflictCount"], 1)
                self.assertEqual(undo_response.json()["conflicts"], ["image-1"])
                marks = photo_curation.load_photo_marks(cache_path, ["image-1", "image-2"])
                self.assertEqual(marks["image-1"].status, "pick")
                self.assertEqual(marks["image-2"].status, "reject")
            finally:
                with culvia_app.STATE_LOCK:
                    culvia_app.STATE["source"].clear()
                    culvia_app.STATE["source"].update(original_source)
                    culvia_app.STATE["filters"].clear()
                    culvia_app.STATE["filters"].update(original_filters)
                    culvia_app.STATE["scores_df"] = original_scores

    def test_curation_undo_rejects_actions_outside_current_source_with_stable_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = str(Path(tmp) / "scores.sqlite")
            source_df = pd.DataFrame(
                [
                    {
                        "file_id": "image-1",
                        "path": "/photos/a.jpg",
                        "folder": "/photos",
                        "filename": "a.jpg",
                        "error": "",
                        "overall_0_10": 8.4,
                    },
                    {
                        "file_id": "image-2",
                        "path": "/photos/b.jpg",
                        "folder": "/photos",
                        "filename": "b.jpg",
                        "error": "",
                        "overall_0_10": 7.1,
                    },
                ]
            )
            store = AppStateStore(
                create_initial_state(
                    scores_df=source_df,
                    default_photo_dirs=["/photos"],
                    default_cache_path=cache_path,
                    filter_defaults=culvia_app.FILTER_DEFAULTS,
                    default_selected_models=[scoring.MODEL_CORE_AESTHETIC],
                )
            )
            with store.lock:
                store.data["filters"].update({"minScore": 7.0, "limit": 80, "colorLabel": "all"})
            client = TestClient(culvia_app.create_app(store))
            response = client.post("/api/mark/status", json={"scope": "filtered", "status": "reject"})
            self.assertEqual(response.status_code, 200)
            action = response.json()["action"]

            with store.lock:
                store.data["scores_df"] = source_df[source_df["file_id"].eq("image-2")].copy()
            undo_response = client.post("/api/curation/undo", json={"historyId": action["historyId"]})

            self.assertEqual(undo_response.status_code, 409)
            self.assertEqual(undo_response.json()["errorCode"], "curationUndoOutsideSource")

    def test_batch_status_can_mark_selected_photo_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = str(Path(tmp) / "scores.sqlite")
            source_df = pd.DataFrame(
                [
                    {
                        "file_id": "image-1",
                        "path": "/photos/a.jpg",
                        "folder": "/photos",
                        "filename": "a.jpg",
                        "error": "",
                        "overall_0_10": 8.4,
                    },
                    {
                        "file_id": "image-2",
                        "path": "/photos/b.jpg",
                        "folder": "/photos",
                        "filename": "b.jpg",
                        "error": "",
                        "overall_0_10": 7.1,
                    },
                    {
                        "file_id": "image-3",
                        "path": "/photos/c.jpg",
                        "folder": "/photos",
                        "filename": "c.jpg",
                        "error": "",
                        "overall_0_10": 5.8,
                    },
                ]
            )
            original_source = dict(culvia_app.STATE["source"])
            original_filters = deepcopy(culvia_app.STATE["filters"])
            original_scores = culvia_app.STATE["scores_df"].copy()
            try:
                with culvia_app.STATE_LOCK:
                    culvia_app.STATE["scores_df"] = source_df
                    culvia_app.STATE["source"].update(
                        {"mode": "folders", "folders": ["/photos"], "cachePath": cache_path}
                    )
                    culvia_app.STATE["filters"].update({"minScore": 7.0, "limit": 80, "colorLabel": "all"})

                response = self._client.post(
                    "/api/mark/status",
                    json={"scope": "selected", "fileIds": ["image-2", "image-3", "missing"], "status": "pick"},
                )

                self.assertEqual(response.status_code, 200)
                action = response.json()["action"]
                self.assertEqual(action["scope"], "selected")
                self.assertEqual(action["marked"], 2)
                self.assertEqual([mark["fileId"] for mark in action["beforeMarks"]], ["image-2", "image-3"])
                marks = photo_curation.load_photo_marks(cache_path, ["image-1", "image-2", "image-3"])
                self.assertNotIn("image-1", marks)
                self.assertEqual(marks["image-2"].status, "pick")
                self.assertEqual(marks["image-3"].status, "pick")
            finally:
                with culvia_app.STATE_LOCK:
                    culvia_app.STATE["source"].clear()
                    culvia_app.STATE["source"].update(original_source)
                    culvia_app.STATE["filters"].clear()
                    culvia_app.STATE["filters"].update(original_filters)
                    culvia_app.STATE["scores_df"] = original_scores


if __name__ == "__main__":
    unittest.main()
