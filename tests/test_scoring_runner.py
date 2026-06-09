from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from culvia.app_state import AppStateStore, create_initial_state
from culvia.job_service import ScoringJobService
from culvia.scoring_runner import ScoringRunnerDependencies, run_scoring_job


def make_store(cache_path: str) -> AppStateStore:
    return AppStateStore(
        create_initial_state(
            scores_df=pd.DataFrame(columns=["file_id", "path", "error"]),
            default_photo_dirs=[],
            default_cache_path=cache_path,
            filter_defaults={},
            default_selected_models=["core"],
        )
    )


def make_dependencies(
    *,
    scan_image_paths=None,
    score_image_paths=None,
    sanitize_uploaded_paths=None,
    llm_configured: bool = True,
    calls: dict[str, Any] | None = None,
) -> ScoringRunnerDependencies:
    call_log = calls if calls is not None else {}

    def refresh(cache_path: str) -> None:
        call_log.setdefault("refreshed", []).append(cache_path)

    def save_source_config(config: dict[str, Any], cache_path: str) -> None:
        call_log.setdefault("source_configs", []).append((config, cache_path))

    def normalize_network_mode(value: object) -> str:
        return str(value) if value in {"direct", "system"} else "direct"

    def normalize_selected_models(value: object) -> list[str]:
        return [str(item) for item in (value or ["core"])]

    def model_loader(device: str, network_mode: str, job_service: ScoringJobService) -> object:
        call_log.setdefault("model_loads", []).append((device, network_mode, job_service))
        return object()

    def clip_reference_loader(device: str, network_mode: str, job_service: ScoringJobService) -> object:
        call_log.setdefault("clip_loads", []).append((device, network_mode, job_service))
        return object()

    def thumbnail_url(path: str, max_size: int) -> str:
        return f"/thumb?path={Path(path).name}&max={max_size}"

    def device_label(device: str | None) -> str:
        return f"设备 {device or 'cpu'}"

    return ScoringRunnerDependencies(
        default_cache_path="/tmp/default.sqlite",
        empty_score_columns=["file_id", "path", "error"],
        llm_review_model_key="llm",
        sanitize_uploaded_paths=sanitize_uploaded_paths or (lambda value: [Path(item) for item in value or []]),
        normalize_network_mode=normalize_network_mode,
        normalize_selected_models=normalize_selected_models,
        refresh_persisted_llm_config=refresh,
        save_source_config=save_source_config,
        llm_review_configured=lambda: llm_configured,
        scan_image_paths=scan_image_paths or (lambda folders: ([], [])),
        score_image_paths=score_image_paths or _unused_score_image_paths,
        model_loader=model_loader,
        clip_reference_loader=clip_reference_loader,
        thumbnail_url=thumbnail_url,
        device_label=device_label,
    )


def _unused_score_image_paths(*_args: object, **_kwargs: object) -> tuple[pd.DataFrame, str]:
    raise AssertionError("score_image_paths should not be called")


class ScoringRunnerTests(unittest.TestCase):
    def test_empty_folder_source_updates_injected_state_and_filters_unconfigured_llm(self) -> None:
        calls: dict[str, Any] = {}
        cache_path = "/tmp/empty.sqlite"
        store = make_store(cache_path)
        service = ScoringJobService(store)
        job_id = service.reserve()
        self.assertTrue(job_id)

        def scan_image_paths(folders: Sequence[str]) -> tuple[list[Path], list[str]]:
            calls["folders"] = list(folders)
            return [], ["目录为空"]

        run_scoring_job(
            job_id,
            {
                "mode": "folders",
                "folders": ["/photos", ""],
                "cachePath": cache_path,
                "networkMode": "system",
                "selectedModels": ["core", "llm"],
            },
            store,
            service,
            make_dependencies(scan_image_paths=scan_image_paths, llm_configured=False, calls=calls),
        )

        with store.lock:
            self.assertTrue(store.data["scores_df"].empty)
            self.assertEqual(list(store.data["scores_df"].columns), ["file_id", "path", "error"])
            self.assertEqual(store.data["source"]["folders"], ["/photos"])
            self.assertEqual(store.data["source"]["cachePath"], cache_path)
            self.assertEqual(store.data["network"]["mode"], "system")
            self.assertEqual(store.data["models"]["selected"], ["core"])
            self.assertFalse(store.data["job"]["running"])
            self.assertEqual(store.data["job"]["phase"], "empty")
            self.assertEqual(store.data["job"]["warnings"], ["目录为空"])
        self.assertEqual(calls["folders"], ["/photos"])
        self.assertEqual(calls["refreshed"], [cache_path])
        self.assertEqual(calls["source_configs"][0][1], cache_path)
        self.assertEqual(service.active_thread_job_id(), "")

    def test_successful_upload_source_scores_without_cache_and_reports_progress(self) -> None:
        calls: dict[str, Any] = {}
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "portrait.jpg"
            image_path.write_bytes(b"image")
            cache_path = str(Path(tmp) / "scores.sqlite")
            store = make_store(cache_path)
            service = ScoringJobService(store)
            job_id = service.reserve()
            self.assertTrue(job_id)

            def score_image_paths(paths: list[Path], **kwargs: Any) -> tuple[pd.DataFrame, str]:
                calls["paths"] = paths
                calls["use_cache"] = kwargs["use_cache"]
                calls["cache_path"] = kwargs["cache_path"]
                kwargs["progress_callback"](0, 1, image_path, "started")
                kwargs["model_loader"]("cpu")
                kwargs["clip_reference_loader"]("cpu")
                return (
                    pd.DataFrame(
                        [
                            {
                                "file_id": "photo-1",
                                "path": str(image_path),
                                "filename": image_path.name,
                                "error": "",
                            }
                        ]
                    ),
                    "mps",
                )

            run_scoring_job(
                job_id,
                {
                    "mode": "uploads",
                    "uploadedPaths": [str(image_path)],
                    "cachePath": cache_path,
                    "networkMode": "system",
                    "selectedModels": ["core"],
                },
                store,
                service,
                make_dependencies(score_image_paths=score_image_paths, calls=calls),
            )

        with store.lock:
            self.assertEqual(len(store.data["scores_df"]), 1)
            self.assertEqual(store.data["source"]["mode"], "uploads")
            self.assertEqual(store.data["source"]["uploadedPaths"], [str(image_path)])
            self.assertFalse(store.data["job"]["running"])
            self.assertEqual(store.data["job"]["phase"], "done")
            self.assertEqual(store.data["job"]["detail"], "1 张照片 · 设备 mps")
            self.assertEqual(store.data["job"]["currentFile"], "")
        self.assertEqual(calls["paths"], [image_path])
        self.assertFalse(calls["use_cache"])
        self.assertEqual(calls["cache_path"], cache_path)
        self.assertEqual(calls["source_configs"][0][0]["mode"], "uploads")
        self.assertEqual(calls["model_loads"][0][0:2], ("cpu", "system"))
        self.assertEqual(calls["clip_loads"][0][0:2], ("cpu", "system"))
        self.assertEqual(service.control["jobId"], "")

    def test_scoring_exception_is_reported_and_control_is_reset(self) -> None:
        cache_path = "/tmp/error.sqlite"
        store = make_store(cache_path)
        service = ScoringJobService(store)
        job_id = service.reserve()
        self.assertTrue(job_id)
        photo_path = Path("/photos/fail.jpg")

        def scan_image_paths(_folders: Sequence[str]) -> tuple[list[Path], list[str]]:
            return [photo_path], []

        def score_image_paths(_paths: list[Path], **_kwargs: Any) -> tuple[pd.DataFrame, str]:
            raise RuntimeError("boom")

        run_scoring_job(
            job_id,
            {"mode": "folders", "folders": ["/photos"], "cachePath": cache_path},
            store,
            service,
            make_dependencies(scan_image_paths=scan_image_paths, score_image_paths=score_image_paths),
        )

        with store.lock:
            self.assertFalse(store.data["job"]["running"])
            self.assertEqual(store.data["job"]["phase"], "error")
            self.assertEqual(store.data["job"]["title"], "评分失败")
            self.assertIn("RuntimeError", store.data["job"]["error"])
        self.assertEqual(service.control["jobId"], "")
        self.assertEqual(service.active_thread_job_id(), "")

    def test_cancelled_scoring_finishes_as_cancelled_not_error(self) -> None:
        cache_path = "/tmp/cancel.sqlite"
        store = make_store(cache_path)
        service = ScoringJobService(store)
        job_id = service.reserve()
        self.assertTrue(job_id)
        photo_path = Path("/photos/cancel.jpg")

        def scan_image_paths(_folders: Sequence[str]) -> tuple[list[Path], list[str]]:
            return [photo_path], []

        def score_image_paths(_paths: list[Path], **kwargs: Any) -> tuple[pd.DataFrame, str]:
            service.request_cancel()
            kwargs["progress_callback"](0, 1, photo_path, "started")
            raise AssertionError("cancel should raise before scoring continues")

        run_scoring_job(
            job_id,
            {"mode": "folders", "folders": ["/photos"], "cachePath": cache_path},
            store,
            service,
            make_dependencies(scan_image_paths=scan_image_paths, score_image_paths=score_image_paths),
        )

        with store.lock:
            self.assertFalse(store.data["job"]["running"])
            self.assertEqual(store.data["job"]["phase"], "cancelled")
            self.assertEqual(store.data["job"]["title"], "评分已取消")
        self.assertEqual(service.control["jobId"], "")

    def test_unsupported_cache_path_suffix_is_reported_as_job_error(self) -> None:
        store = make_store("/tmp/current.sqlite")
        service = ScoringJobService(store)
        job_id = service.reserve()
        self.assertTrue(job_id)

        run_scoring_job(
            job_id,
            {"mode": "folders", "folders": ["/photos"], "cachePath": "/tmp/notes.txt"},
            store,
            service,
            make_dependencies(),
        )

        with store.lock:
            self.assertFalse(store.data["job"]["running"])
            self.assertEqual(store.data["job"]["phase"], "error")
            self.assertIn("ValueError", store.data["job"]["error"])
            self.assertEqual(store.data["source"]["cachePath"], "/tmp/current.sqlite")
        self.assertEqual(service.control["jobId"], "")
        self.assertEqual(service.active_thread_job_id(), "")


if __name__ == "__main__":
    unittest.main()
