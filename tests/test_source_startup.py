from __future__ import annotations

import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from starlette.testclient import TestClient

import culvia_app
from culvia import curation, scoring, source_preview
from culvia.app_state import AppStateStore
from culvia.runtime_config import RuntimeConfig
from culvia.web_app import create_runtime_state_store


class SourceStartupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.old = self.root / "old"
        self.current = self.root / "current"
        self.old.mkdir()
        (self.current / "nested").mkdir(parents=True)
        self.old_photos = [self.photo(self.old / f"old-{index}.jpg") for index in range(8)]
        self.current_photos = [self.photo(self.current / "first.jpg"), self.photo(self.current / "nested/second.jpg")]
        self.config = RuntimeConfig(
            web_dir=Path("web"),
            upload_cache_dir=self.root / "uploads",
            thumbnail_cache_dir=self.root / "thumbnails",
            default_cache_path=str(self.root / "scores.sqlite"),
            default_photo_dirs=(str(self.old),),
            export_receipts_path=self.root / "receipts.sqlite",
        )
        scoring.save_cache_records(pd.DataFrame([self.record(path, score=8.0) for path in self.old_photos]), self.cache)

    @property
    def cache(self) -> str:
        return self.config.default_cache_path

    @staticmethod
    def photo(path: Path) -> Path:
        path.write_bytes(path.name.encode())
        return path

    @staticmethod
    def record(path: Path, *, score: float | None = None) -> dict[str, object]:
        record = culvia_app.make_empty_preview_record(path, scoring.build_file_id(path))
        if score is not None:
            for column in scoring.CORE_AESTHETIC_GROUP.cache_columns:
                record[column] = score / 2 if column.endswith("_0_5") else score
            record[scoring.MODEL_RESULT_VERSION_COLUMNS[scoring.MODEL_CORE_AESTHETIC]] = scoring.MODEL_CAPABILITIES[
                scoring.MODEL_CORE_AESTHETIC
            ].result_version
        return record

    def save_source(self, folders: list[str]) -> None:
        scoring.save_source_config_to_sqlite(
            {"mode": "folders", "folders": folders, "cachePath": self.cache}, self.cache
        )

    def runtime_store(self, config: RuntimeConfig | None = None, **kwargs) -> AppStateStore:
        return create_runtime_state_store(
            config or self.config,
            load_scores=scoring.load_cache_records,
            load_source_config=kwargs.pop("load_source_config", scoring.load_source_config_from_sqlite),
            filter_defaults=culvia_app.FILTER_DEFAULTS,
            default_selected_models=[scoring.MODEL_CORE_AESTHETIC],
            **kwargs,
        )

    def app(self, store: AppStateStore, config: RuntimeConfig | None = None):
        app = culvia_app.create_app(store, runtime_config=config or self.config)
        self.addCleanup(app.state.thumbnail_coordinator.close)
        return app

    def wait_for_job(self, app) -> None:
        deadline = time.monotonic() + 3
        while app.state.job_service.is_running() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(app.state.job_service.is_running(), "source recovery must finish")

    @contextmanager
    def blocked_scan(self):
        entered = threading.Event()
        release = threading.Event()
        scan = culvia_app.scan_image_paths

        def blocked(folders):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("test did not release source scan")
            return scan(folders)

        with patch("culvia_app.scan_image_paths", side_effect=blocked) as mocked:
            try:
                yield entered, release, mocked
            finally:
                release.set()

    def test_restart_scans_current_source_without_exposing_eight_old_photos(self) -> None:
        self.save_source([str(self.current)])
        selected_id = scoring.build_file_id(self.current_photos[0])
        curation.save_photo_mark(self.cache, selected_id, status="pick", rating=4, source="manual")
        store = self.runtime_store()
        app = self.app(store)

        with self.blocked_scan() as (entered, release, _scan), TestClient(app) as client:
            try:
                initial = client.get("/api/state").json()
                self.assertEqual(initial["source"]["folders"], [str(self.current)])
                self.assertEqual(initial["photos"], [])
                self.assertEqual(initial["selectedPhotos"], [])
                self.assertEqual(initial["summary"]["total"], 0)
                old_id = scoring.build_file_id(self.old_photos[0])
                self.assertEqual(client.get("/api/image", params={"file_id": old_id}).status_code, 404)
                self.assertTrue(initial["job"]["running"])
                self.assertEqual(initial["job"]["kind"], "source_preview")
                self.assertTrue(entered.wait(1), "the scan must run asynchronously during app startup")
                refreshed = client.get("/api/state").json()
                self.assertEqual(refreshed["job"]["jobId"], initial["job"]["jobId"])
                self.assertEqual(
                    client.post("/api/mark", json={"fileId": selected_id, "status": "reject"}).status_code, 409
                )
                self.assertEqual(client.post("/api/source/preview", json={"folders": [str(self.old)]}).status_code, 409)
                self.assertEqual(
                    client.post("/api/export/preflight", json={"destination": str(self.root / "export")}).status_code,
                    409,
                )
                self.assertFalse(app.state.job_service.request_pause())
                self.assertFalse(app.state.job_service.request_resume())
            finally:
                release.set()
                self.wait_for_job(app)
            restored = client.get("/api/state").json()
            rejected = client.post("/api/mark", json={"fileId": old_id, "status": "pick"})
            self.assertEqual(rejected.status_code, 404)
            self.assertEqual(rejected.json()["errorCode"], "photoNotFound")

        self.assertEqual(restored["sourcePreview"]["total"], 2)
        self.assertTrue(restored["sourcePreview"]["ready"])
        self.assertEqual(restored["summary"]["total"], 2)
        self.assertEqual(restored["summary"]["scored"], 0)
        self.assertEqual(
            {photo["fileId"] for photo in restored["photos"]},
            {scoring.build_file_id(path) for path in self.current_photos},
        )
        selected = next(photo for photo in restored["photos"] if photo["fileId"] == selected_id)
        self.assertEqual(
            (selected["manual"]["status"], selected["manual"]["rating"], selected["manual"]["source"]),
            ("pick", 4, "manual"),
        )
        self.assertEqual(
            len(scoring.load_cache_records(self.cache)), 8, "preview must not delete or rewrite cached scores"
        )

        restarted = self.runtime_store()
        self.assertTrue(restarted.data["scores_df"].empty)

    def test_initial_scope_reuses_current_scores_and_rejects_a_sibling_prefix(self) -> None:
        sibling = self.root / "current-extra"
        sibling.mkdir()
        sibling_photo = self.photo(sibling / "other.jpg")
        current_record = self.record(self.current_photos[0], score=8.2)
        scoring.save_cache_records(pd.DataFrame([current_record, self.record(sibling_photo, score=9.0)]), self.cache)
        self.save_source([str(self.current)])
        store = self.runtime_store()
        self.assertEqual(store.data["scores_df"]["file_id"].tolist(), [current_record["file_id"]])
        app = self.app(store)

        with TestClient(app) as client:
            self.wait_for_job(app)
            restored = client.get("/api/state").json()

        self.assertEqual(restored["summary"]["total"], 2)
        self.assertEqual(restored["summary"]["scored"], 1)
        row = store.data["scores_df"].set_index("file_id").loc[current_record["file_id"]]
        self.assertEqual(row["overall_0_10"], 8.2)
        self.assertEqual(row["path"], str(self.current_photos[0]))
        self.assertEqual(len(scoring.load_cache_records(self.cache)), 10)

    def test_persisted_empty_source_overrides_defaults_without_loading_old_rows(self) -> None:
        self.save_source([])
        store = self.runtime_store()
        app = self.app(store)

        with (
            patch("culvia_app.scan_image_paths", side_effect=AssertionError("empty source must not scan")),
            TestClient(app) as client,
        ):
            state = client.get("/api/state").json()

        self.assertEqual(state["source"]["folders"], [])
        self.assertEqual(state["photos"], [])
        self.assertEqual(state["summary"]["total"], 0)
        self.assertFalse(state["job"]["running"])
        self.assertTrue(state["sourcePreview"]["ready"])
        self.assertEqual(scoring.load_source_config_from_sqlite(self.cache)["folders"], [])
        self.assertEqual(len(scoring.load_cache_records(self.cache)), 8)

    def test_default_source_scans_recursively_and_deduplicates_without_persisting_defaults(self) -> None:
        config = self.config.with_paths(
            default_photo_dirs=[str(self.current), str(self.current), str(self.current / "nested")]
        )
        store = self.runtime_store(config)
        app = self.app(store, config)

        with TestClient(app) as client:
            self.wait_for_job(app)
            state = client.get("/api/state").json()

        self.assertEqual(state["source"]["folders"], [str(self.current)])
        self.assertEqual(state["summary"]["total"], 2)
        self.assertEqual(scoring.load_source_config_from_sqlite(self.cache), {})
        self.assertEqual(self.runtime_store().data["source"]["folders"], [str(self.old)])

    def test_missing_source_finishes_empty_with_a_warning(self) -> None:
        missing = str(self.root / "missing")
        self.save_source([missing])
        app = self.app(self.runtime_store())

        with TestClient(app) as client:
            self.wait_for_job(app)
            state = client.get("/api/state").json()

        self.assertEqual(state["photos"], [])
        self.assertTrue(state["sourcePreview"]["ready"])
        self.assertEqual(state["job"]["phase"], "source_empty")
        self.assertEqual(state["sourcePreview"]["warnings"][0]["key"], "warning.folderMissing")
        self.assertEqual(state["source"]["folders"], [missing])

    def test_scan_failure_stays_visible_and_releases_the_job_slot(self) -> None:
        self.save_source([str(self.current)])
        app = self.app(self.runtime_store())

        with patch("culvia_app.scan_image_paths", side_effect=OSError("source unavailable")), TestClient(app) as client:
            self.wait_for_job(app)
            state = client.get("/api/state").json()
            self.assertEqual(state["job"]["phase"], "error")
            self.assertEqual(state["job"]["titleText"]["key"], "jobText.scanFailed")
            self.assertIn("source unavailable", state["job"]["error"])
            self.assertFalse(state["sourcePreview"]["ready"])
            self.assertEqual(state["photos"], [])
            service = app.state.job_service
            self.assertEqual(service.control["jobId"], "")
            job_id = service.reserve()
            self.assertTrue(job_id)
            service.finish(job_id)

    def test_thread_start_failures_are_visible_without_failing_app_startup(self) -> None:
        class FailingThread:
            def __init__(self, **_kwargs):
                pass

            def start(self):
                raise RuntimeError("cannot start thread")

        def fail_constructor(**_kwargs):
            raise RuntimeError("cannot construct thread")

        self.save_source([str(self.current)])
        for factory in (FailingThread, fail_constructor):
            with self.subTest(factory=factory):
                store = self.runtime_store()
                app = self.app(store)
                app.state.restore_source = lambda state, service: source_preview.start_source_preview_on_startup(
                    state,
                    service,
                    dependencies=culvia_app.source_preview_dependencies(),
                    thread_factory=factory,
                )
                with TestClient(app) as client:
                    state = client.get("/api/state").json()
                    self.assertEqual(state["job"]["phase"], "error")
                    self.assertEqual(state["job"]["kind"], "source_preview")
                    self.assertFalse(state["job"]["running"])
                    self.assertFalse(state["sourcePreview"]["ready"])
                    self.assertIn("cannot", state["job"]["error"])
                    service = app.state.job_service
                    self.assertEqual(service.control["jobId"], "")
                    job_id = service.reserve()
                    self.assertTrue(job_id)
                    service.finish(job_id)

    def test_existing_paused_scoring_job_is_not_replaced_on_startup_or_refresh(self) -> None:
        self.save_source([str(self.current)])
        app = self.app(self.runtime_store())
        service = app.state.job_service
        job_id = service.reserve(kind="scoring")
        self.assertTrue(service.request_pause())
        service.update(phase="paused")
        before = dict(service.state_store.data["job"])

        with (
            patch("culvia_app.scan_image_paths", side_effect=AssertionError("must not scan during scoring")),
            TestClient(app) as client,
        ):
            for _ in range(2):
                state = client.get("/api/state").json()
                self.assertEqual(state["job"], before)
            self.assertTrue(service.request_resume())
            self.assertEqual(service.state_store.data["job"]["jobId"], job_id)
            service.finish(job_id)

    def test_explicit_preview_thread_failure_retains_error_details_and_releases_the_slot(self) -> None:
        self.save_source([str(self.current)])
        app = self.app(self.runtime_store())
        start_preview = culvia_app.start_source_preview_job_action

        def fail_thread(**_kwargs):
            raise RuntimeError("cannot construct explicit preview worker")

        def start_with_failure(*args, **kwargs):
            return start_preview(*args, **{**kwargs, "thread_factory": fail_thread})

        client = TestClient(app, raise_server_exceptions=False)
        with patch("culvia_app.start_source_preview_job_action", side_effect=start_with_failure):
            response = client.post(
                "/api/source/preview", json={"folders": [str(self.current)], "cachePath": self.cache}
            )
        self.assertEqual(response.status_code, 500)
        state = client.get("/api/state").json()
        self.assertEqual(state["job"]["phase"], "error")
        self.assertEqual(state["job"]["kind"], "source_preview")
        self.assertIn("cannot construct explicit preview worker", state["job"]["error"])
        self.assertFalse(state["job"]["running"])
        self.assertEqual(app.state.job_service.control["jobId"], "")

    def test_active_uploads_survive_startup_and_page_refresh_without_folder_scanning(self) -> None:
        store = self.runtime_store()
        self.config.upload_cache_dir.mkdir()
        uploaded = self.photo(self.config.upload_cache_dir / "upload.jpg")
        row = self.record(uploaded)
        store.publish_media_state(
            scores_df=pd.DataFrame([row]),
            source_patch={"mode": "uploads", "folders": [str(self.old)], "uploadedPaths": [str(uploaded)]},
            source_preview={"mode": "uploads", "ready": True, "total": 1},
        )
        app = self.app(store)

        with (
            patch("culvia_app.scan_image_paths", side_effect=AssertionError("uploads must not scan folders")),
            TestClient(app) as client,
        ):
            for _ in range(2):
                state = client.get("/api/state").json()
                self.assertEqual(state["source"]["mode"], "uploads")
                self.assertEqual(state["source"]["uploadedPaths"], [str(uploaded)])
                self.assertEqual([photo["fileId"] for photo in state["photos"]], [row["file_id"]])
                self.assertFalse(state["job"]["running"])

    def test_temporary_uploads_do_not_replace_the_persisted_folder_source(self) -> None:
        self.save_source([str(self.current)])
        scoring.save_source_config_to_sqlite(
            {"mode": "uploads", "folders": [], "uploadedPaths": ["/uploads/temporary.jpg"]}, self.cache
        )
        store = self.runtime_store()
        self.assertEqual(store.data["source"]["mode"], "folders")
        self.assertEqual(store.data["source"]["folders"], [str(self.current)])
        self.assertTrue(store.data["scores_df"].empty)

    def test_upload_mode_without_a_saved_upload_selection_does_not_restore_folder_cache(self) -> None:
        store = self.runtime_store(load_source_config=lambda _: {"mode": "uploads", "folders": [str(self.old)]})
        app = self.app(store)

        with (
            patch("culvia_app.scan_image_paths", side_effect=AssertionError("uploads must not scan folders")),
            TestClient(app) as client,
        ):
            state = client.get("/api/state").json()

        self.assertEqual(state["source"]["mode"], "uploads")
        self.assertEqual(state["source"]["uploadedPaths"], [])
        self.assertEqual(state["photos"], [])
        self.assertFalse(state["job"]["running"])

    def test_source_config_loading_errors_are_not_silently_replaced_with_defaults(self) -> None:
        def fail(_path):
            raise OSError("configuration unavailable")

        with self.assertRaisesRegex(OSError, "configuration unavailable"):
            self.runtime_store(load_source_config=fail)

    def test_restored_cache_path_is_used_for_initial_scores_and_async_recovery(self) -> None:
        selected_cache = str(self.root / "selected-library.sqlite")
        current_record = self.record(self.current_photos[0], score=7.6)
        scoring.save_cache_records(pd.DataFrame([current_record]), selected_cache)
        scoring.save_source_config_to_sqlite(
            {"mode": "folders", "folders": [str(self.current)], "cachePath": selected_cache}, self.cache
        )
        store = self.runtime_store()
        self.assertEqual(store.data["source"]["cachePath"], selected_cache)
        self.assertEqual(store.data["scores_df"]["file_id"].tolist(), [current_record["file_id"]])
        app = self.app(store)

        with TestClient(app) as client:
            self.wait_for_job(app)
            state = client.get("/api/state").json()

        self.assertEqual(state["summary"]["total"], 2)
        self.assertEqual(state["summary"]["scored"], 1)
        self.assertEqual(scoring.load_source_config_from_sqlite(selected_cache), {})
        self.assertEqual(scoring.load_source_config_from_sqlite(self.cache)["cachePath"], selected_cache)

    def test_ready_folder_source_is_not_restarted_by_a_new_lifespan(self) -> None:
        self.save_source([str(self.current)])
        store = self.runtime_store()
        rows = pd.DataFrame([self.record(path) for path in self.current_photos])
        store.publish_media_state(
            scores_df=rows,
            source_preview={"mode": "folders", "folders": [str(self.current)], "ready": True, "total": 2},
        )
        app = self.app(store)
        before_revision = store.media_revision

        with (
            patch("culvia_app.scan_image_paths", side_effect=AssertionError("ready source must not be scanned again")),
            TestClient(app) as client,
        ):
            state = client.get("/api/state").json()

        self.assertEqual(state["summary"]["total"], 2)
        self.assertFalse(state["job"]["running"])
        self.assertEqual(store.media_revision, before_revision)


if __name__ == "__main__":
    unittest.main()
