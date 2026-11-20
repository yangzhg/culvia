from __future__ import annotations

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from starlette.testclient import TestClient

import culvia_app
from culvia import scoring
from culvia.app_state import AppStateStore, create_initial_state
from culvia.export_receipts import ExportReceiptError
from culvia.runtime_config import RuntimeConfig


class ColdDeviceProbe:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.lock = threading.Lock()
        self.calls = 0

    def __call__(self) -> str:
        with self.lock:
            cold = self.calls == 0
            self.calls += 1
        if cold:
            self.entered.set()
            try:
                if not self.release.wait(5):
                    raise RuntimeError("test did not release the cold device probe")
            finally:
                self.finished.set()
        return "mps"


class StatePollingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.cache_path = self.root / "scores.sqlite"
        config = RuntimeConfig(
            web_dir=Path("web"),
            upload_cache_dir=self.root / "uploads",
            thumbnail_cache_dir=self.root / "thumbnails",
            default_cache_path=str(self.cache_path),
            default_photo_dirs=(),
            export_receipts_path=self.root / "receipts.sqlite",
        )
        state = create_initial_state(
            scores_df=pd.DataFrame(columns=scoring.CSV_COLUMNS),
            default_photo_dirs=[],
            default_cache_path=str(self.cache_path),
            filter_defaults=culvia_app.FILTER_DEFAULTS,
            default_selected_models=[scoring.MODEL_CORE_AESTHETIC],
        )
        state["sourcePreview"].update(ready=True, total=0)
        self.store = AppStateStore(state)
        self.app = culvia_app.create_app(self.store, runtime_config=config)
        self.client = self.enterContext(TestClient(self.app))

    def assert_state_response(self, response, *, receipt=None) -> dict[str, object]:
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        payload = response.json()
        self.assertEqual(payload["source"]["cachePath"], str(self.cache_path))
        self.assertEqual(payload["source"]["folders"], [])
        self.assertEqual(payload["photos"], [])
        self.assertEqual(payload["summary"]["total"], 0)
        self.assertEqual(payload["exportReceipt"], receipt)
        return payload

    def test_health_responds_during_the_first_cold_device_probe(self) -> None:
        probe = ColdDeviceProbe()
        receipt = {"operationId": "delivery-1", "status": "completed", "copied": 2}
        with (
            patch("culvia_app.get_device", side_effect=probe),
            patch.object(self.app.state.export_receipts, "latest", return_value=receipt),
            ThreadPoolExecutor(max_workers=2) as requests,
        ):
            pending = requests.submit(self.client.get, "/api/state")
            try:
                self.assertTrue(probe.entered.wait(2))
                health = requests.submit(self.client.get, "/health").result(timeout=2)
                self.assertEqual(health.status_code, 200)
                self.assertEqual(health.json(), {"ok": True})
                self.assertFalse(probe.finished.is_set())
                self.assertFalse(pending.done())
            finally:
                probe.release.set()
                response = pending.result(timeout=3)
            payload = self.assert_state_response(response, receipt=receipt)
            self.assertFalse(payload["job"]["running"])
            self.assertEqual(payload["app"]["deviceText"], {"key": "device.appleSilicon"})
            self.assertEqual(payload["model"]["runtimeDeviceText"], payload["app"]["deviceText"])
            self.assertEqual(probe.calls, 1)
            self.assert_state_response(self.client.get("/api/state"), receipt=receipt)
            self.assertEqual(probe.calls, 2)

    def test_maintenance_started_during_device_probe_prevents_persistent_snapshot_reads(self) -> None:
        probe = ColdDeviceProbe()
        clearing = threading.Event()
        release_clear = threading.Event()
        original_clear = culvia_app.clear_history_cache
        forbidden_reads: list[str] = []

        def blocked_clear(path):
            clearing.set()
            if not release_clear.wait(5):
                raise RuntimeError("test did not release history cleanup")
            return original_clear(path)

        def guard_read(name, function):
            def guarded(*args, **kwargs):
                with self.store.lock:
                    job = self.store.data["job"]
                    maintaining = job.get("running") and job.get("kind") == "maintenance"
                if maintaining:
                    forbidden_reads.append(name)
                    raise AssertionError(f"maintenance snapshot touched {name}")
                return function(*args, **kwargs)

            return guarded

        dependencies = culvia_app.STATE_PAYLOAD_DEPENDENCIES
        guarded_dependencies = replace(
            dependencies,
            load_photo_marks=guard_read("photo marks", dependencies.load_photo_marks),
            load_analysis_insights=guard_read("analysis insights", dependencies.load_analysis_insights),
            model_payload=guard_read("model files", dependencies.model_payload),
        )
        with (
            patch("culvia_app.get_device", side_effect=probe),
            patch("culvia_app.clear_history_cache", side_effect=blocked_clear),
            patch.object(culvia_app, "STATE_PAYLOAD_DEPENDENCIES", guarded_dependencies),
            patch(
                "culvia_app.load_latest_matching_analysis_insight_results",
                side_effect=guard_read("analysis matches", culvia_app.load_latest_matching_analysis_insight_results),
            ),
            patch(
                "culvia_app.load_llm_config_from_sqlite",
                side_effect=guard_read("LLM configuration", culvia_app.load_llm_config_from_sqlite),
            ),
            ThreadPoolExecutor(max_workers=2) as requests,
        ):
            pending = requests.submit(self.client.get, "/api/state")
            cleanup = None
            try:
                self.assertTrue(probe.entered.wait(2))
                cleanup = requests.submit(
                    self.client.post, "/api/cache/clear", json={"cachePath": str(self.cache_path)}
                )
                self.assertTrue(clearing.wait(2), "maintenance must start while device detection is pending")
                probe.release.set()
                payload = self.assert_state_response(pending.result(timeout=3))
                self.assertTrue(payload["job"]["running"])
                self.assertEqual(payload["job"]["kind"], "maintenance")
                self.assertEqual(payload["job"]["phase"], "clearing_history")
                self.assertEqual(forbidden_reads, [])
                self.assertFalse(cleanup.done())
            finally:
                probe.release.set()
                release_clear.set()
                pending.result(timeout=3)
                if cleanup is not None:
                    cleared = cleanup.result(timeout=3)
            self.assertEqual(cleared.status_code, 200)
            self.assertFalse(self.store.data["job"]["running"])
            self.assertEqual(forbidden_reads, [])

    def test_device_failure_propagates_before_snapshot_or_receipt_reads(self) -> None:
        with (
            patch("culvia_app.get_device", side_effect=RuntimeError("device probe failed")),
            patch("culvia_app.state_payload", wraps=culvia_app.state_payload) as snapshot,
            patch.object(self.app.state.export_receipts, "latest") as receipt,
        ):
            with self.assertRaisesRegex(RuntimeError, "device probe failed"):
                self.client.get("/api/state")
        snapshot.assert_not_called()
        receipt.assert_not_called()

    def test_snapshot_failure_after_device_probe_is_not_silently_replaced(self) -> None:
        def failed_read(*_args, **_kwargs):
            raise OSError("photo marks unavailable")

        dependencies = replace(culvia_app.STATE_PAYLOAD_DEPENDENCIES, load_photo_marks=failed_read)
        with (
            patch("culvia_app.get_device", return_value="cpu"),
            patch.object(culvia_app, "STATE_PAYLOAD_DEPENDENCIES", dependencies),
            patch.object(self.app.state.export_receipts, "latest") as receipt,
        ):
            with self.assertRaisesRegex(OSError, "photo marks unavailable"):
                self.client.get("/api/state")
        receipt.assert_not_called()

    def test_receipt_failure_preserves_state_and_machine_readable_error(self) -> None:
        error = ExportReceiptError("exportReceiptStorageFailed", "receipt unavailable", params={"operation": "read"})
        with (
            patch("culvia_app.get_device", return_value="cpu"),
            patch.object(self.app.state.export_receipts, "latest", side_effect=error),
        ):
            response = self.client.get("/api/state")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        payload = response.json()
        self.assertEqual(payload["source"]["cachePath"], str(self.cache_path))
        self.assertEqual(payload["photos"], [])
        self.assertFalse(payload["job"]["running"])
        self.assertNotIn("exportReceipt", payload)
        self.assertEqual(
            payload["exportReceiptError"],
            {"errorCode": "exportReceiptStorageFailed", "errorParams": {"operation": "read"}},
        )


if __name__ == "__main__":
    unittest.main()
