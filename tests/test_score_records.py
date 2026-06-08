from __future__ import annotations

import unittest
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from culvia.score_records import (
    apply_dual_scale_scores,
    apply_single_scale_scores,
    make_empty_score_record,
)


@dataclass(frozen=True)
class DummyFieldGroup:
    cache_columns: tuple[str, ...]


class ScoreRecordHelperTests(unittest.TestCase):
    def test_make_empty_score_record_populates_identity_and_missing_scores(self) -> None:
        record = make_empty_score_record(
            Path("/tmp/photos/a.jpg"),
            "photo-id",
            recommendation_column="recommendation",
            field_groups=(DummyFieldGroup(("overall_0_10", "quality_0_10")),),
            error="broken",
        )

        self.assertEqual(record["file_id"], "photo-id")
        self.assertEqual(record["path"], "/tmp/photos/a.jpg")
        self.assertEqual(record["folder"], "/tmp/photos")
        self.assertEqual(record["filename"], "a.jpg")
        self.assertEqual(record["error"], "broken")
        self.assertIs(record["recommendation"], pd.NA)
        self.assertIs(record["overall_0_10"], pd.NA)
        self.assertIs(record["quality_0_10"], pd.NA)

    def test_apply_dual_scale_scores_writes_both_scales_without_mutating_original(self) -> None:
        original = {"file_id": "photo-id"}

        updated = apply_dual_scale_scores(
            original,
            fields=("overall", "quality"),
            scores={"overall": 4.12345, "quality": 2.0},
            source_scale="0_5",
            target_scale="0_10",
            multiplier=2.0,
        )

        self.assertEqual(original, {"file_id": "photo-id"})
        self.assertEqual(updated["overall_0_5"], 4.1235)
        self.assertEqual(updated["overall_0_10"], 8.2469)
        self.assertEqual(updated["quality_0_5"], 2.0)
        self.assertEqual(updated["quality_0_10"], 4.0)

    def test_apply_single_scale_scores_requires_all_fields_by_default(self) -> None:
        with self.assertRaises(KeyError):
            apply_single_scale_scores(
                {},
                fields=("overall", "quality"),
                scores={"overall": 7.0},
            )

    def test_apply_single_scale_scores_can_write_only_present_fields(self) -> None:
        updated = apply_single_scale_scores(
            {"file_id": "photo-id"},
            fields=("overall", "quality"),
            scores={"quality": 6.78901},
            only_present=True,
        )

        self.assertNotIn("overall_0_10", updated)
        self.assertEqual(updated["quality_0_10"], 6.789)


if __name__ == "__main__":
    unittest.main()
