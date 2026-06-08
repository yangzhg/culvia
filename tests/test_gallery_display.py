from __future__ import annotations

import unittest
from typing import Any, Mapping

import pandas as pd

from culvia.curation import PhotoMark
from culvia.gallery_display import (
    apply_color_label_filter,
    apply_manual_status_filter,
    color_label_matches,
    dataframe_for_display,
    manual_status_matches,
    selected_preview_for_display,
)


MANUAL_MODES = {"all", "pick", "pending", "reject"}
COLOR_MODES = {"all", "labeled", "none", "red", "yellow", "green", "blue", "purple"}


def enrich_scores(df: pd.DataFrame, _filters: Mapping[str, Any]) -> pd.DataFrame:
    working = df.copy()
    if "recommendation_0_10" not in working.columns:
        working["recommendation_0_10"] = working["overall_0_10"]
    return working


def apply_model_agreement(df: pd.DataFrame, mode: str) -> pd.DataFrame:
    if mode == "high_quality_only":
        return df[pd.to_numeric(df["technical_overall_0_10"], errors="coerce") >= 8.0].copy()
    return df


class GalleryDisplayTests(unittest.TestCase):
    def test_manual_status_matching_preserves_pending_semantics(self) -> None:
        self.assertTrue(manual_status_matches(None, "pending"))
        self.assertTrue(manual_status_matches(PhotoMark("a", status=""), "pending"))
        self.assertTrue(manual_status_matches(PhotoMark("b", status="hold"), "pending"))
        self.assertFalse(manual_status_matches(PhotoMark("c", status="pick"), "pending"))
        self.assertFalse(manual_status_matches(PhotoMark("d", status="reject"), "pending"))
        self.assertTrue(manual_status_matches(PhotoMark("e", status="pick"), "all"))

    def test_manual_status_filter_invalid_mode_falls_back_to_all(self) -> None:
        df = pd.DataFrame([{"file_id": "a"}, {"file_id": "b"}])
        marks = {"a": PhotoMark("a", status="pick")}

        filtered = apply_manual_status_filter(df, marks, "unknown", valid_modes=MANUAL_MODES)

        self.assertEqual(filtered["file_id"].tolist(), ["a", "b"])

    def test_color_label_matching_preserves_virtual_modes(self) -> None:
        self.assertTrue(color_label_matches(PhotoMark("a", color_label="red"), "labeled"))
        self.assertTrue(color_label_matches(None, "none"))
        self.assertTrue(color_label_matches(PhotoMark("b", color_label=""), "none"))
        self.assertTrue(color_label_matches(PhotoMark("c", color_label="green"), "green"))
        self.assertFalse(color_label_matches(PhotoMark("d", color_label="blue"), "green"))
        self.assertTrue(color_label_matches(PhotoMark("e", color_label="blue"), "all"))

    def test_color_label_filter_invalid_mode_falls_back_to_all(self) -> None:
        df = pd.DataFrame([{"file_id": "a"}, {"file_id": "b"}])
        marks = {"a": PhotoMark("a", color_label="red")}

        filtered = apply_color_label_filter(df, marks, "orange", valid_modes=COLOR_MODES)

        self.assertEqual(filtered["file_id"].tolist(), ["a", "b"])

    def test_dataframe_for_display_applies_display_pipeline_without_app_state(self) -> None:
        source = pd.DataFrame(
            [
                {
                    "file_id": "a",
                    "error": "",
                    "recommendation_0_10": 8.1,
                    "overall_0_10": 8.1,
                    "technical_overall_0_10": 8.5,
                },
                {
                    "file_id": "b",
                    "error": "",
                    "recommendation_0_10": 9.3,
                    "overall_0_10": 9.3,
                    "technical_overall_0_10": 6.0,
                },
                {
                    "file_id": "c",
                    "error": "",
                    "recommendation_0_10": 7.7,
                    "overall_0_10": 7.7,
                    "technical_overall_0_10": 9.0,
                },
                {
                    "file_id": "d",
                    "error": "decode failed",
                    "recommendation_0_10": 9.9,
                    "overall_0_10": 9.9,
                    "technical_overall_0_10": 9.9,
                },
                {
                    "file_id": "e",
                    "error": "",
                    "recommendation_0_10": pd.NA,
                    "overall_0_10": 10.0,
                    "technical_overall_0_10": 10.0,
                },
            ]
        )
        marks = {
            "a": PhotoMark("a", status="hold", color_label="red"),
            "b": PhotoMark("b", status="pick", color_label="red"),
            "c": PhotoMark("c", status="hold", color_label="blue"),
        }
        filters = {
            "minScore": 7.0,
            "minTechnical": 8.0,
            "modelAgreement": "high_quality_only",
            "manualStatus": "pending",
            "colorLabel": "red",
            "sortField": "not_a_sort_field",
            "limit": 0,
        }

        working, filtered, errors = dataframe_for_display(
            source,
            filters,
            marks,
            enrich_scores=enrich_scores,
            apply_model_agreement=apply_model_agreement,
            sort_fields={"recommendation_0_10", "overall_0_10"},
            manual_status_filter_values=MANUAL_MODES,
            color_label_filter_values=COLOR_MODES,
        )

        self.assertEqual(working["file_id"].tolist(), ["a", "b", "c", "d", "e"])
        self.assertEqual(errors["file_id"].tolist(), ["d"])
        self.assertEqual(filtered["file_id"].tolist(), ["a"])

    def test_selected_preview_uses_pick_status_score_order_and_limit(self) -> None:
        working = pd.DataFrame(
            [
                {"file_id": "a", "recommendation_0_10": 7.0},
                {"file_id": "b", "recommendation_0_10": 9.0},
                {"file_id": "c", "recommendation_0_10": 8.0},
            ]
        )
        marks = {
            "a": PhotoMark("a", status="pick"),
            "b": PhotoMark("b", status="reject"),
            "c": PhotoMark("c", status="pick"),
            "missing": PhotoMark("missing", status="pick"),
        }

        selected = selected_preview_for_display(working, marks, limit=1)

        self.assertEqual(selected["file_id"].tolist(), ["c"])


if __name__ == "__main__":
    unittest.main()
