from __future__ import annotations

import unittest

import pandas as pd

from culvia.recommendation import (
    FILTER_DEFAULTS,
    active_weights,
    apply_model_agreement_filter,
    apply_threshold_filters,
    calculate_recommendation,
    enrich_scores_for_display,
    model_agreement_matches,
    numeric_column,
    weighted_average,
)


def normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    return df.copy()


class RecommendationTests(unittest.TestCase):
    def test_active_weights_normalizes_custom_values(self) -> None:
        weights = active_weights(
            {
                "weightPreset": "custom",
                "customWeights": {"aesthetic": 2, "technical": 1, "compositionLight": 1},
            }
        )

        self.assertEqual(weights, {"aesthetic": 0.5, "technical": 0.25, "compositionLight": 0.25})

    def test_weighted_average_ignores_missing_and_zero_weight_parts(self) -> None:
        self.assertAlmostEqual(weighted_average([(8.0, 0.5), (None, 0.5), (2.0, 0.0)]) or 0, 8.0)
        self.assertIsNone(weighted_average([(None, 1.0), (4.0, 0.0)]))

    def test_calculate_recommendation_combines_aesthetic_technical_and_composition(self) -> None:
        row = pd.Series(
            {
                "overall_0_10": 8.0,
                "clip_aesthetic_0_10": 6.0,
                "llm_aesthetic_overall_0_10": 9.0,
                "technical_overall_0_10": 7.0,
                "clip_iqa_overall_0_10": 6.0,
                "llm_technical_overall_0_10": 5.0,
                "composition_0_10": 9.0,
                "lighting_0_10": 7.0,
            }
        )

        score = calculate_recommendation(row, FILTER_DEFAULTS)

        self.assertIsNotNone(score)
        self.assertAlmostEqual(score or 0, 7.39, places=2)

    def test_enrich_scores_for_display_numericizes_fields_and_adds_recommendation(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "file_id": "a",
                    "overall_0_10": "8.0",
                    "technical_overall_0_10": "7.0",
                    "composition_0_10": "bad",
                }
            ]
        )

        enriched = enrich_scores_for_display(
            df,
            FILTER_DEFAULTS,
            normalize_dataframe=normalize_frame,
            score_fields=("overall", "technical_overall", "composition", "lighting"),
        )

        self.assertAlmostEqual(float(enriched.loc[0, "overall_0_10"]), 8.0)
        self.assertTrue(pd.isna(enriched.loc[0, "composition_0_10"]))
        self.assertTrue(pd.isna(enriched.loc[0, "lighting_0_10"]))
        self.assertAlmostEqual(float(enriched.loc[0, "recommendation_0_10"]), 7.7222, places=4)

    def test_threshold_filters_keep_rows_that_meet_active_minimums(self) -> None:
        df = pd.DataFrame(
            [
                {"file_id": "a", "recommendation_0_10": 8.0, "technical_overall_0_10": 6.0},
                {"file_id": "b", "recommendation_0_10": 6.0, "technical_overall_0_10": 8.0},
                {"file_id": "c", "recommendation_0_10": 8.5, "technical_overall_0_10": 8.0},
            ]
        )

        filtered = apply_threshold_filters(
            df,
            {"minScore": 7.0, "minTechnical": 7.0},
            {"minScore": "recommendation_0_10", "minTechnical": "technical_overall_0_10"},
        )

        self.assertEqual(filtered["file_id"].tolist(), ["c"])

    def test_model_agreement_modes_detect_alignment_and_disagreement(self) -> None:
        aligned = pd.Series(
            {
                "overall_0_10": 7.6,
                "clip_aesthetic_0_10": 7.4,
                "clip_iqa_overall_0_10": 7.2,
                "technical_overall_0_10": 7.1,
            }
        )
        split = pd.Series(
            {
                "overall_0_10": 8.5,
                "clip_aesthetic_0_10": 8.1,
                "clip_iqa_overall_0_10": 5.2,
                "technical_overall_0_10": 5.4,
            }
        )
        llm_split = pd.Series(
            {
                "overall_0_10": 8.2,
                "clip_iqa_overall_0_10": 7.8,
                "llm_aesthetic_overall_0_10": 4.0,
                "llm_technical_overall_0_10": 4.2,
            }
        )

        self.assertTrue(
            model_agreement_matches(
                aligned,
                "aligned",
                llm_aesthetic_weight=0.75,
                llm_technical_weight=0.25,
            )
        )
        self.assertTrue(
            model_agreement_matches(
                split,
                "disagreement",
                llm_aesthetic_weight=0.75,
                llm_technical_weight=0.25,
            )
        )
        self.assertTrue(
            model_agreement_matches(
                split,
                "aesthetic_gap",
                llm_aesthetic_weight=0.75,
                llm_technical_weight=0.25,
            )
        )
        self.assertTrue(
            model_agreement_matches(
                llm_split,
                "llm_disagreement",
                llm_aesthetic_weight=0.75,
                llm_technical_weight=0.25,
            )
        )

    def test_apply_model_agreement_filter_returns_matching_rows(self) -> None:
        df = pd.DataFrame(
            [
                {"file_id": "a", "overall_0_10": 7.6, "technical_overall_0_10": 7.5},
                {"file_id": "b", "overall_0_10": 9.0, "technical_overall_0_10": 4.0},
            ]
        )

        filtered = apply_model_agreement_filter(
            df,
            "disagreement",
            llm_aesthetic_weight=0.75,
            llm_technical_weight=0.25,
        )

        self.assertEqual(filtered["file_id"].tolist(), ["b"])

    def test_numeric_column_returns_none_for_missing_values(self) -> None:
        self.assertIsNone(numeric_column({"score": ""}, "score"))
        self.assertAlmostEqual(numeric_column({"score": "7.3"}, "score") or 0, 7.3)


if __name__ == "__main__":
    unittest.main()
