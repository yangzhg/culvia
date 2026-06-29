from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from culvia.curation import load_photo_marks, save_photo_mark
from culvia.curation_service import (
    CurationServiceError,
    accept_targets_action,
    curation_history_payload,
    mark_photo_action,
    status_targets_action,
    undo_curation_action,
)


def passthrough_display(
    source_df: pd.DataFrame,
    _filters: dict[str, object],
    _marks: dict[str, object],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    working = source_df.copy()
    filtered = working[working["recommendation_0_10"] >= 7.0].copy()
    return working, filtered, working.iloc[0:0].copy()


class CurationServiceTests(unittest.TestCase):
    def source_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "file_id": "image-1",
                    "path": "/photos/a.jpg",
                    "recommendation_0_10": 8.2,
                    "llm_review_overall_0_10": 8.5,
                },
                {
                    "file_id": "image-2",
                    "path": "/photos/b.jpg",
                    "recommendation_0_10": 6.8,
                    "llm_review_overall_0_10": None,
                },
                {
                    "file_id": "image-3",
                    "path": "/photos/c.jpg",
                    "recommendation_0_10": 7.4,
                    "llm_review_overall_0_10": 7.6,
                },
            ]
        )

    def test_mark_photo_action_validates_source_and_records_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = str(Path(tmp) / "scores.sqlite")
            action = mark_photo_action(
                cache_path, self.source_frame(), {"fileId": "image-1", "rating": 4, "status": "pick"}
            )
            missing = None
            try:
                mark_photo_action(cache_path, self.source_frame(), {"fileId": "missing", "status": "pick"})
            except CurationServiceError as error:
                missing = error
            marks = load_photo_marks(cache_path, ["image-1"])
            history = curation_history_payload(cache_path, limit=5)["actions"]

        self.assertEqual(action["marked"], 1)
        self.assertEqual(action["scope"], "current")
        self.assertTrue(action["historyId"])
        self.assertEqual(marks["image-1"].rating, 4)
        self.assertEqual(marks["image-1"].status, "pick")
        self.assertIsNotNone(missing)
        self.assertEqual(missing.error_code, "photoNotFound")
        self.assertEqual(history[0]["id"], action["historyId"])

    def test_status_targets_action_resolves_selected_ids_and_preserves_target_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = str(Path(tmp) / "scores.sqlite")
            action = status_targets_action(
                cache_path,
                self.source_frame(),
                {},
                {"scope": "selected", "fileIds": ["image-3", "missing", "image-1"], "status": "hold"},
                passthrough_display,
            )
            marks = load_photo_marks(cache_path, ["image-1", "image-2", "image-3"])

        self.assertEqual(action["scope"], "selected")
        self.assertEqual(action["marked"], 2)
        self.assertEqual([mark["fileId"] for mark in action["beforeMarks"]], ["image-3", "image-1"])
        self.assertEqual(marks["image-3"].status, "hold")
        self.assertEqual(marks["image-1"].status, "hold")
        self.assertNotIn("image-2", marks)

    def test_accept_targets_action_uses_basis_scores_and_reports_skips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = str(Path(tmp) / "scores.sqlite")
            action = accept_targets_action(
                cache_path,
                self.source_frame(),
                {},
                {"scope": "selected", "fileIds": ["image-1", "image-2"], "basis": "llm"},
                passthrough_display,
            )
            marks = load_photo_marks(cache_path, ["image-1", "image-2"])

        self.assertEqual(action["basis"], "llm")
        self.assertEqual(action["accepted"], 1)
        self.assertEqual(action["skipped"], 1)
        self.assertEqual(marks["image-1"].source, "llm_batch")
        self.assertAlmostEqual(float(marks["image-1"].accepted_score or 0), 8.5)
        self.assertNotIn("image-2", marks)

    def test_undo_curation_action_detects_conflicts_before_restore(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = str(Path(tmp) / "scores.sqlite")
            action = status_targets_action(
                cache_path,
                self.source_frame(),
                {},
                {"fileId": "image-1", "status": "reject"},
                passthrough_display,
            )
            save_photo_mark(cache_path, "image-1", status="pick")

            conflict = None
            try:
                undo_curation_action(cache_path, self.source_frame(), {"historyId": action["historyId"]})
            except CurationServiceError as error:
                conflict = error

        self.assertIsNotNone(conflict)
        self.assertEqual(conflict.error_code, "curationUndoConflict")
        self.assertEqual(conflict.params["conflictCount"], 1)
        self.assertEqual(conflict.conflicts, ["image-1"])


if __name__ == "__main__":
    unittest.main()
