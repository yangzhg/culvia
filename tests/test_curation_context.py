from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

import pandas as pd

from culvia.curation import PhotoMark, save_photo_mark
from culvia.curation_context import build_curation_display_context


class CurationContextTests(unittest.TestCase):
    def test_builds_display_context_with_loaded_marks_and_target_rows(self) -> None:
        source_df = pd.DataFrame(
            {
                "file_id": ["a", "b", "c"],
                "recommendation_0_10": [6.0, 8.0, 7.0],
            }
        )

        def dataframe_builder(
            df: pd.DataFrame,
            filters: dict[str, Any],
            marks: dict[str, PhotoMark],
        ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
            working = df.copy()
            if filters.get("manualStatus") == "pick":
                picked_ids = {file_id for file_id, mark in marks.items() if mark.status == "pick"}
                filtered = working[working["file_id"].astype(str).isin(picked_ids)].copy()
            else:
                filtered = working.head(2).copy()
            return working, filtered, working.iloc[0:0].copy()

        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = str(Path(temp_dir) / "scores.sqlite")
            save_photo_mark(cache_path, "b", status="pick", source="manual")

            context = build_curation_display_context(
                source_df,
                {"manualStatus": "pick"},
                cache_path,
                dataframe_builder,
            )

        self.assertEqual(context.source_file_ids, ["a", "b", "c"])
        self.assertEqual(context.valid_file_ids, {"a", "b", "c"})
        self.assertEqual(set(context.mark_by_file_id), {"b"})
        self.assertEqual(context.filtered["file_id"].tolist(), ["b"])

        filtered_targets = context.resolve_targets({"scope": "filtered"})
        self.assertTrue(filtered_targets.ok)
        self.assertEqual(filtered_targets.target_ids, ["b"])
        self.assertEqual(context.rows_for_targets(filtered_targets)["file_id"].tolist(), ["b"])

        selected_targets = context.resolve_targets({"scope": "selected", "fileIds": ["c", "missing", "a"]})
        self.assertTrue(selected_targets.ok)
        self.assertEqual(selected_targets.target_ids, ["c", "a"])
        self.assertEqual(context.rows_for_targets(selected_targets)["file_id"].tolist(), ["a", "c"])

    def test_empty_cache_path_uses_empty_marks(self) -> None:
        source_df = pd.DataFrame({"file_id": ["a"]})

        def dataframe_builder(
            df: pd.DataFrame,
            filters: dict[str, Any],
            marks: dict[str, PhotoMark],
        ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
            self.assertEqual(marks, {})
            return df.copy(), df.copy(), df.iloc[0:0].copy()

        context = build_curation_display_context(source_df, {}, "", dataframe_builder)

        self.assertEqual(context.mark_by_file_id, {})
        self.assertEqual(context.source_file_ids, ["a"])


if __name__ == "__main__":
    unittest.main()
