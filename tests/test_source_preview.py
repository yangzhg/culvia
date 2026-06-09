from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any

import pandas as pd

from culvia.app_state import AppStateStore, create_initial_state
from culvia.job_service import ScoringJobService
from culvia.photo_scan import build_file_id, scan_image_paths
from culvia.score_records import make_empty_score_record
from culvia.schema import CSV_COLUMNS, FIELD_GROUPS, RECOMMENDATION_COLUMN
from culvia.source_preview import (
    SourcePreviewDependencies,
    SourcePreviewStartError,
    apply_source_preview_state,
    run_source_preview_job,
    source_preview_action,
    start_source_preview_job_action,
)


class FakeThread:
    created: list["FakeThread"] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs
        self.started = False
        FakeThread.created.append(self)

    def start(self) -> None:
        self.started = True


class SourcePreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeThread.created = []

    def dependencies(self, cached: pd.DataFrame | None = None) -> SourcePreviewDependencies:
        return SourcePreviewDependencies(
            default_cache_path="scores.sqlite",
            scan_image_paths=scan_image_paths,
            sanitize_uploaded_paths=lambda paths: [Path(str(path)) for path in paths],
            build_file_id=build_file_id,
            load_cache_records=lambda _cache_path: cached if cached is not None else pd.DataFrame(columns=CSV_COLUMNS),
            normalize_score_dataframe=lambda frame: frame.reindex(columns=CSV_COLUMNS),
            make_empty_record=lambda path, file_id, error: make_empty_score_record(
                path,
                file_id,
                recommendation_column=RECOMMENDATION_COLUMN,
                field_groups=FIELD_GROUPS,
                error=error,
            ),
        )

    def store(self, cache_path: str = "/tmp/scores.sqlite") -> AppStateStore:
        return AppStateStore(
            create_initial_state(
                scores_df=pd.DataFrame(columns=CSV_COLUMNS),
                default_photo_dirs=[],
                default_cache_path=cache_path,
                filter_defaults={},
                default_selected_models=[],
            )
        )

    def test_preview_scans_nested_folders_and_reuses_cached_scores(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "nested"
            nested.mkdir()
            first = root / "a.jpg"
            second = nested / "b.jpg"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            second_id = build_file_id(second.resolve())
            cached = pd.DataFrame(
                [
                    {
                        "file_id": second_id,
                        "path": str(second.resolve()),
                        "folder": str(nested.resolve()),
                        "filename": "b.jpg",
                        "error": "",
                        "recommendation_0_10": 8.4,
                    }
                ]
            )

            result = source_preview_action(
                {"mode": "folders", "folders": [str(root), str(nested)], "cachePath": str(root / "scores.sqlite")},
                self.dependencies(cached),
            )

        self.assertEqual(len(result.paths), 2)
        self.assertEqual(result.warnings, [])
        self.assertEqual(result.scores_df["file_id"].nunique(), 2)
        cached_row = result.scores_df[result.scores_df["file_id"] == second_id].iloc[0]
        self.assertEqual(float(cached_row["recommendation_0_10"]), 8.4)

    def test_preview_uses_uploaded_paths_without_scanning_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "upload.jpg"
            path.write_bytes(b"upload")

            result = source_preview_action(
                {"mode": "uploads", "uploadedPaths": [str(path)], "cachePath": str(Path(tmp) / "scores.sqlite")},
                self.dependencies(),
            )

        self.assertEqual(result.source_payload()["uploadedPaths"], [str(path)])
        self.assertEqual(len(result.scores_df), 1)

    def test_start_preview_job_reserves_slot_and_starts_thread(self) -> None:
        store = self.store()
        service = ScoringJobService(store)
        payload = {"mode": "folders", "folders": ["/photos"], "cachePath": "/tmp/scores.sqlite"}
        calls: list[tuple[str, dict[str, Any], AppStateStore, ScoringJobService]] = []

        def run_job(
            job_id: str,
            job_payload: dict[str, Any],
            state_store: AppStateStore,
            job_service: ScoringJobService,
        ) -> None:
            calls.append((job_id, job_payload, state_store, job_service))

        result = start_source_preview_job_action(
            payload,
            store,
            service,
            default_cache_path="/tmp/scores.sqlite",
            run_source_preview_job=run_job,
            thread_factory=FakeThread,
        )

        self.assertEqual(result.to_payload(), {"started": True, "jobId": result.job_id})
        self.assertEqual(calls, [])
        self.assertEqual(len(FakeThread.created), 1)
        self.assertTrue(FakeThread.created[0].started)
        self.assertIs(FakeThread.created[0].kwargs["target"], run_job)
        self.assertEqual(FakeThread.created[0].kwargs["args"], (result.job_id, payload, store, service))
        self.assertTrue(FakeThread.created[0].kwargs["daemon"])
        with store.lock:
            self.assertTrue(store.data["job"]["running"])
            self.assertEqual(store.data["job"]["kind"], "source_preview")
            self.assertEqual(store.data["job"]["phase"], "source_scanning")

    def test_start_preview_job_rejects_existing_running_task(self) -> None:
        store = self.store()
        service = ScoringJobService(store)
        first = service.reserve()
        self.assertTrue(first)

        with self.assertRaises(SourcePreviewStartError) as error:
            start_source_preview_job_action(
                {"mode": "folders", "folders": ["/photos"], "cachePath": "/tmp/scores.sqlite"},
                store,
                service,
                default_cache_path="/tmp/scores.sqlite",
                run_source_preview_job=lambda *_args: None,
                thread_factory=FakeThread,
            )

        self.assertEqual(error.exception.error_code, "jobAlreadyRunning")
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(FakeThread.created, [])

    def test_run_preview_job_updates_state_and_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "photo.jpg"
            path.write_bytes(b"photo")
            store = self.store(str(root / "scores.sqlite"))
            service = ScoringJobService(store)
            job_id = service.reserve(kind="source_preview", phase="source_scanning")
            self.assertTrue(job_id)

            run_source_preview_job(
                job_id,
                {"mode": "folders", "folders": [tmp], "cachePath": str(root / "scores.sqlite")},
                store,
                service,
                self.dependencies(),
            )

        with store.lock:
            self.assertFalse(store.data["job"]["running"])
            self.assertEqual(store.data["job"]["kind"], "source_preview")
            self.assertEqual(store.data["job"]["phase"], "source_ready")
            self.assertEqual(store.data["sourcePreview"]["total"], 1)
            self.assertEqual(len(store.data["scores_df"]), 1)
        self.assertEqual(service.control["jobId"], "")

    def test_preview_skips_paths_that_cannot_build_file_id(self) -> None:
        root = Path("/photos")

        def scan(_folders: list[str]) -> tuple[list[Path], list[str]]:
            return [root / "missing.jpg"], []

        result = source_preview_action(
            {"mode": "folders", "folders": [str(root)], "cachePath": "scores.sqlite"},
            SourcePreviewDependencies(
                default_cache_path="scores.sqlite",
                scan_image_paths=scan,
                sanitize_uploaded_paths=lambda paths: [Path(str(path)) for path in paths],
                build_file_id=build_file_id,
                load_cache_records=lambda _cache_path: pd.DataFrame(columns=CSV_COLUMNS),
                normalize_score_dataframe=lambda frame: frame.reindex(columns=CSV_COLUMNS),
                make_empty_record=lambda path, file_id, error: make_empty_score_record(
                    path,
                    file_id,
                    recommendation_column=RECOMMENDATION_COLUMN,
                    field_groups=FIELD_GROUPS,
                    error=error,
                ),
            ),
        )

        self.assertEqual(result.paths, [])
        self.assertEqual(len(result.scores_df), 0)
        self.assertIn("读取照片失败", result.warnings[0])

    def test_apply_preview_state_updates_source_and_scores(self) -> None:
        class Store:
            def __init__(self) -> None:
                self.lock = threading.Lock()
                self.data = {
                    "scores_df": pd.DataFrame(columns=CSV_COLUMNS),
                    "source": {"mode": "folders", "folders": [], "cachePath": "old.sqlite", "uploadedPaths": []},
                }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "photo.jpg"
            path.write_bytes(b"photo")
            result = source_preview_action(
                {"mode": "folders", "folders": [tmp], "cachePath": str(Path(tmp) / "scores.sqlite")},
                self.dependencies(),
            )

        store = Store()
        apply_source_preview_state(store, result)

        self.assertEqual(store.data["source"]["folders"], [tmp])
        self.assertEqual(store.data["source"]["cachePath"], str(Path(tmp) / "scores.sqlite"))
        self.assertEqual(store.data["sourcePreview"]["total"], 1)
        self.assertTrue(store.data["sourcePreview"]["ready"])
        self.assertEqual(store.data["sourcePreview"]["folders"], [tmp])
        self.assertEqual(len(store.data["scores_df"]), 1)


if __name__ == "__main__":
    unittest.main()
