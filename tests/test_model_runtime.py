from __future__ import annotations

import unittest
from unittest.mock import patch

from culvia.schema import RUNTIME_CLIP_REFERENCE, RUNTIME_CORE_AESTHETIC
from culvia.model_runtime import ModelRuntimeCache, model_progress_payload


class FakeJobService:
    def __init__(self) -> None:
        self.updates: list[dict[str, object]] = []

    def update(self, **updates: object) -> None:
        self.updates.append(updates)


class ModelProgressPayloadTests(unittest.TestCase):
    def test_reference_model_cached_progress_is_hidden(self) -> None:
        self.assertIsNone(model_progress_payload("config.json", 1, 5, "cached", {}))

    def test_reference_model_active_progress_uses_compact_copy(self) -> None:
        payload = model_progress_payload(
            "tokenizer.json",
            2,
            5,
            "downloading",
            {"active_download_size_label": "3.4 MB"},
        )

        self.assertIsNotNone(payload)
        self.assertEqual(payload["labelText"], {"key": "jobText.prepRefModel", "params": {"stage": 2, "total": 5}})
        self.assertEqual(
            payload["detailText"],
            {"key": "jobText.prepFileWithSize", "params": {"filename": "tokenizer.json", "size": "3.4 MB"}},
        )
        self.assertGreater(float(payload["progress"]), 0)

    def test_core_model_connection_progress_is_terse(self) -> None:
        payload = model_progress_payload("model.pt", 5, 5, "connecting", {})

        self.assertEqual(payload["labelText"], {"key": "jobText.prepModel"})
        self.assertEqual(payload["detailText"], {"key": "jobText.connectingSource"})
        self.assertGreater(float(payload["progress"]), 0)

    def test_core_model_download_progress_includes_size_speed_and_eta(self) -> None:
        payload = model_progress_payload(
            "model.pt",
            5,
            5,
            "downloading",
            {
                "download_fraction": 0.123,
                "active_download_size": 41.0 * 1024 * 1024,
                "expected_size": 333.7 * 1024 * 1024,
                "speed_bps": 2.1 * 1024 * 1024,
                "eta_seconds": 130,
            },
        )

        self.assertEqual(payload["labelText"], {"key": "jobText.downloadingModel", "params": {"percent": "12.3%"}})
        self.assertEqual(payload["progress"], 0.123)
        self.assertEqual(
            payload["detailText"],
            {
                "key": "jobText.downloadStats",
                "params": {
                    "downloaded": "41.0 MB",
                    "expected": "333.7 MB",
                    "speed": "2.1 MB/s",
                    "eta": {"key": "duration.minutesSeconds", "params": {"minutes": 2, "seconds": "10"}},
                },
            },
        )


class ModelRuntimeCacheTests(unittest.TestCase):
    def test_cache_key_set_any_loaded_and_clear(self) -> None:
        cache = ModelRuntimeCache()
        self.assertTrue(cache.any_loaded([], "cpu"))
        self.assertFalse(cache.any_loaded([RUNTIME_CORE_AESTHETIC], "cpu"))

        loaded = object()
        cache.set(RUNTIME_CORE_AESTHETIC, "cpu", loaded)

        self.assertIs(cache.get(RUNTIME_CORE_AESTHETIC, "cpu"), loaded)
        self.assertTrue(cache.any_loaded([RUNTIME_CLIP_REFERENCE, RUNTIME_CORE_AESTHETIC], "cpu"))
        self.assertFalse(cache.any_loaded([RUNTIME_CORE_AESTHETIC], "mps"))

        cache.clear()
        self.assertFalse(cache.any_loaded([RUNTIME_CORE_AESTHETIC], "cpu"))

    def test_core_model_loader_reuses_cached_model(self) -> None:
        cache = ModelRuntimeCache()
        job_service = FakeJobService()
        loaded_model = object()

        with (
            patch("culvia.model_runtime.ensure_model_files") as ensure_files,
            patch(
                "culvia.model_runtime.load_model",
                return_value=loaded_model,
            ) as load_model,
        ):
            first = cache.load_core_model("cpu", job_service=job_service)
            second = cache.load_core_model("cpu", job_service=job_service)

        self.assertIs(first, loaded_model)
        self.assertIs(second, loaded_model)
        ensure_files.assert_called_once()
        load_model.assert_called_once_with("cpu")
        self.assertTrue(any(update.get("phase") == "loading_model" for update in job_service.updates))


if __name__ == "__main__":
    unittest.main()
