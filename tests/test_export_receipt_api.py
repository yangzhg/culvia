from __future__ import annotations

import asyncio
import csv
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from starlette.testclient import TestClient

import culvia_app
from culvia import curation, export_service, scoring
from culvia.app_state import AppStateStore, create_initial_state
from culvia.export_receipts import ExportReceiptStorageError, ExportReceiptStore


class ExportReceiptApiTests(unittest.TestCase):
    def make_app(self, root: Path, *, count: int = 52):
        cache_path = str(root / "scores.sqlite")
        photos = root / "photos"
        photos.mkdir(exist_ok=True)
        rows = []
        for index in range(count):
            source = photos / f"photo-{index:03}.jpg"
            if index % 2 == 0:
                source.write_bytes(f"photo {index}".encode())
            file_id = f"photo-{index:03}"
            rows.append({"file_id": file_id, "path": str(source), "error": "", "overall_0_10": 8.0})
            curation.save_photo_mark(cache_path, file_id, status="pick")
        store = AppStateStore(
            create_initial_state(
                scores_df=pd.DataFrame(rows),
                default_photo_dirs=[str(photos)],
                default_cache_path=cache_path,
                filter_defaults=culvia_app.FILTER_DEFAULTS,
                default_selected_models=[scoring.MODEL_CORE_AESTHETIC],
            )
        )
        config = culvia_app.current_runtime_config().with_paths(
            default_cache_path=cache_path,
            upload_cache_dir=root / "uploads",
            thumbnail_cache_dir=root / "thumbnails",
            export_receipts_path=root / "receipts.sqlite",
        )
        app = culvia_app.create_app(store, runtime_config=config)
        self.addCleanup(app.state.thumbnail_coordinator.close)
        return app

    def test_copy_receipt_survives_a_new_app_and_exposes_complete_file_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = self.make_app(root)
            destination = root / "delivery"
            destination.mkdir()
            (destination / "photo-000.jpg").write_bytes(b"earlier delivery")
            client = TestClient(app)
            response = client.post("/api/export/selected-files", json={"destination": str(destination)})

            self.assertEqual(response.status_code, 200)
            result = response.json()
            self.assertTrue(result.get("operationId"), "Each real copy needs a recoverable delivery receipt")
            self.assertEqual(result["status"], "completed")
            self.assertEqual((result["copied"], result["skipped"]), (26, 26))
            self.assertEqual(result["totalEntryCount"], 52)
            self.assertLessEqual(result["previewCount"], 20)
            self.assertEqual((destination / "photo-000.jpg").read_bytes(), b"earlier delivery")
            self.assertEqual((destination / "photo-000-2.jpg").read_bytes(), b"photo 0")

            with TestClient(self.make_app(root)) as reopened:
                restored = reopened.get("/api/state").json()["exportReceipt"]
                self.assertEqual(restored["operationId"], result["operationId"])
                self.assertEqual(restored["status"], "completed")
                receipt_url = f"/api/export/receipts/{result['operationId']}"
                detail = reopened.get(receipt_url)
                self.assertEqual(detail.status_code, 200)
                entries = detail.json()["entries"]
                self.assertEqual(len(entries), 52)
                self.assertEqual(entries[0]["source"], str(root / "photos" / "photo-000.jpg"))
                self.assertEqual(entries[0]["target"], str(destination / "photo-000-2.jpg"))
                self.assertEqual(entries[-1]["status"], "missing")
                manifest = reopened.get(f"{receipt_url}/manifest.csv")
                self.assertEqual(manifest.status_code, 200)
                self.assertIn("attachment", manifest.headers["content-disposition"])
                rows = list(csv.DictReader(io.StringIO(manifest.content.decode("utf-8-sig"))))
                self.assertEqual(len(rows), 52)
                self.assertEqual({row["operationId"] for row in rows}, {result["operationId"]})
                self.assertEqual(sum(row["status"] == "copied" for row in rows), 26)
                self.assertEqual(sum(row["status"] == "missing" for row in rows), 26)

    def test_refresh_and_request_cancellation_keep_the_same_running_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = self.make_app(root, count=4)
            destination = root / "delivery"
            entered = threading.Event()
            release = threading.Event()
            real_copy = export_service._copy_photo_file

            def blocked_copy(source, output, **kwargs):
                if source.name == "photo-002.jpg":
                    entered.set()
                    if not release.wait(timeout=5):
                        raise RuntimeError("Test copy was not released")
                return real_copy(source, output, **kwargs)

            class Request:
                async def json(self):
                    return {"destination": str(destination)}

            request = Request()
            request.app = app

            async def exercise():
                with patch("culvia.export_service._copy_photo_file", side_effect=blocked_copy):
                    task = asyncio.create_task(culvia_app.api_export_selected(request))
                    try:
                        self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                        state = json.loads((await culvia_app.api_state(request)).body)
                        receipt = state["exportReceipt"]
                        self.assertTrue(state["job"]["running"])
                        self.assertEqual(receipt["status"], "running")
                        self.assertEqual((receipt["copied"], receipt["skipped"]), (1, 1))
                        self.assertEqual(receipt["total"], 4)
                        task.cancel()
                        await asyncio.sleep(0)
                        refreshed = json.loads((await culvia_app.api_state(request)).body)
                        self.assertEqual(refreshed["exportReceipt"]["operationId"], receipt["operationId"])
                        self.assertTrue(refreshed["job"]["running"])
                    finally:
                        release.set()
                        if not task.done():
                            with self.assertRaises(asyncio.CancelledError):
                                await task
                    final = json.loads((await culvia_app.api_state(request)).body)
                    self.assertFalse(final["job"]["running"])
                    self.assertEqual(final["exportReceipt"]["operationId"], receipt["operationId"])
                    self.assertEqual(final["exportReceipt"]["status"], "completed")
                    self.assertEqual((final["exportReceipt"]["copied"], final["exportReceipt"]["skipped"]), (2, 2))

            asyncio.run(exercise())

    def test_read_failure_does_not_replace_existing_receipt_with_an_empty_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = self.make_app(Path(tmp), count=2)
            with patch.object(app.state.export_receipts, "latest", side_effect=ExportReceiptStorageError()):
                response = TestClient(app).get("/api/state")
            self.assertEqual(response.status_code, 200)
            self.assertIn("photos", response.json())
            self.assertNotIn("exportReceipt", response.json())
            self.assertEqual(response.json()["exportReceiptError"]["errorCode"], "exportReceiptStorageFailed")

    def test_successful_export_recovers_from_an_earlier_startup_storage_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = self.make_app(root, count=2)
            (root / "receipts.sqlite").touch()
            with TestClient(app) as client:
                self.assertIn("exportReceiptError", client.get("/api/state").json())
                exported = client.post("/api/export/selected-files", json={"destination": str(root / "delivery")})
                self.assertEqual(exported.status_code, 200)
                restored = client.get("/api/state").json()
                self.assertNotIn("exportReceiptError", restored)
                self.assertEqual(restored["exportReceipt"]["operationId"], exported.json()["operationId"])

    def test_state_rechecks_storage_after_a_transient_startup_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = self.make_app(root, count=2)
            result = (
                TestClient(app).post("/api/export/selected-files", json={"destination": str(root / "delivery")}).json()
            )
            with patch.object(
                app.state.export_receipts, "recover_interrupted", side_effect=ExportReceiptStorageError()
            ):
                with TestClient(app) as client:
                    restored = client.get("/api/state").json()
            self.assertNotIn("exportReceiptError", restored)
            self.assertEqual(restored["exportReceipt"]["operationId"], result["operationId"])

    def test_history_cleanup_rejects_a_receipt_alias_of_the_score_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = self.make_app(root, count=2)
            score_path = root / "scores.sqlite"
            alias = root / "receipt-alias.sqlite"
            alias.symlink_to(score_path)
            app.state.export_receipts = ExportReceiptStore(alias)
            before = score_path.read_bytes()
            response = TestClient(app).post("/api/cache/clear", json={"cachePath": str(score_path)})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["errorCode"], "exportReceiptPathConflict")
            self.assertEqual(score_path.read_bytes(), before)

    def test_model_cleanup_does_not_delete_receipts_inside_the_model_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = self.make_app(root, count=2)
            models = root / "models"
            app.state.export_receipts = ExportReceiptStore(models / "receipts.sqlite")
            client = TestClient(app)
            result = client.post("/api/export/selected-files", json={"destination": str(root / "delivery")}).json()
            with patch("culvia_app.APP_MODEL_CACHE_DIR", models), patch("culvia_app.MODEL_REPO_CACHE_DIRS", []):
                response = client.post("/api/model/clear", json={})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["errorCode"], "exportReceiptPathConflict")
            self.assertEqual(app.state.export_receipts.latest()["operationId"], result["operationId"])

    def test_local_reset_checks_receipt_paths_before_any_cleanup(self) -> None:
        for directory in ("uploads", "thumbnails", "analysis", "models", "hf/models--unit", "hf/.locks/models--unit"):
            with self.subTest(directory=directory), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                app = self.make_app(root, count=2)
                receipt_path = root / directory / "receipts.sqlite"
                app.state.export_receipts = ExportReceiptStore(receipt_path)
                client = TestClient(app)
                result = client.post("/api/export/selected-files", json={"destination": str(root / "delivery")}).json()
                thumbnail = root / "thumbnails" / "sentinel.jpg"
                thumbnail.parent.mkdir(exist_ok=True)
                thumbnail.write_bytes(b"thumbnail")
                with (
                    patch("culvia_app.ANALYSIS_IMAGE_CACHE_DIR", root / "analysis"),
                    patch("culvia_app.APP_MODEL_CACHE_DIR", root / "models"),
                    patch("culvia_app.MODEL_REPO_CACHE_DIRS", ["models--unit"]),
                    patch("culvia_app.get_huggingface_cache_root", return_value=root / "hf"),
                    patch("culvia_app.delete_llm_api_key") as clear_secret,
                    patch("culvia_app.clear_session_llm_config"),
                    patch("culvia_app.clear_secure_llm_config"),
                    patch("culvia_app.set_persisted_llm_config"),
                    patch("culvia_app.MODEL_RUNTIME.clear"),
                ):
                    response = client.post("/api/data/clear", json={"cachePath": str(root / "scores.sqlite")})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["errorCode"], "exportReceiptPathConflict")
                clear_secret.assert_not_called()
                self.assertEqual(thumbnail.read_bytes(), b"thumbnail")
                self.assertTrue((root / "scores.sqlite").exists())
                self.assertEqual(app.state.export_receipts.latest()["operationId"], result["operationId"])

    def test_unknown_receipt_and_manifest_are_not_found_without_creating_a_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = self.make_app(root, count=2)
            client = TestClient(app)
            self.assertIsNone(client.get("/api/state").json()["exportReceipt"])
            for suffix in ("", "/manifest.csv"):
                response = client.get(f"/api/export/receipts/unknown{suffix}")
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json()["errorCode"], "exportReceiptNotFound")
            self.assertFalse((root / "receipts.sqlite").exists())

    def test_clearing_scores_preserves_delivery_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = self.make_app(root, count=2)
            client = TestClient(app)
            receipt = client.post("/api/export/selected-files", json={"destination": str(root / "delivery")}).json()
            cleared = client.post("/api/cache/clear", json={"cachePath": str(root / "scores.sqlite")})
            self.assertEqual(cleared.status_code, 200)
            restored = client.get("/api/state").json()["exportReceipt"]
            self.assertEqual(restored["operationId"], receipt["operationId"])
            self.assertTrue((root / "delivery" / "photo-000.jpg").is_file())


if __name__ == "__main__":
    unittest.main()
