from __future__ import annotations

import unittest

import pandas as pd

from culvia.insight_store import AnalysisInsightMatch
from culvia.llm_provenance import resolve_llm_score_dataframe


class LlmProvenanceTests(unittest.TestCase):
    def test_resolver_accepts_exact_generations_and_masks_stale_or_legacy_rows(self) -> None:
        source = pd.DataFrame(
            [
                {
                    "file_id": "current",
                    "llm_review_generation": 2.0,
                    "llm_review_overall_0_10": 8.0,
                    "llm_color_0_10": 7.0,
                    "recommendation_0_10": 8.5,
                },
                {
                    "file_id": "legacy",
                    "llm_review_generation": pd.NA,
                    "llm_review_overall_0_10": 7.5,
                    "llm_color_0_10": 6.0,
                    "recommendation_0_10": 7.0,
                },
                {
                    "file_id": "stale",
                    "llm_review_generation": 1.0,
                    "llm_review_overall_0_10": 9.5,
                    "llm_color_0_10": 9.0,
                    "recommendation_0_10": 9.8,
                },
                {
                    "file_id": "unproven-legacy",
                    "llm_review_generation": pd.NA,
                    "llm_review_overall_0_10": 6.0,
                    "llm_color_0_10": 6.0,
                    "recommendation_0_10": 6.2,
                },
                {
                    "file_id": "local-only",
                    "llm_review_generation": pd.NA,
                    "llm_review_overall_0_10": pd.NA,
                    "llm_color_0_10": pd.NA,
                    "recommendation_0_10": 5.5,
                },
            ]
        )
        matches = {
            "current": AnalysisInsightMatch(2.0),
            "legacy": AnalysisInsightMatch(3.0),
            "stale": AnalysisInsightMatch(2.0),
            "unproven-legacy": AnalysisInsightMatch(4.0),
        }

        result = resolve_llm_score_dataframe(
            source,
            matches,
            generation_column="llm_review_generation",
            score_columns=("llm_review_overall_0_10", "llm_color_0_10"),
            derived_columns=("recommendation_0_10",),
        )
        rows = result.dataframe.set_index("file_id")

        self.assertEqual(result.current_file_ids, frozenset({"current"}))
        self.assertEqual(float(rows.loc["current", "recommendation_0_10"]), 8.5)
        self.assertEqual(float(rows.loc["local-only", "recommendation_0_10"]), 5.5)
        for file_id in ("legacy", "stale", "unproven-legacy"):
            self.assertTrue(pd.isna(rows.loc[file_id, "llm_review_generation"]))
            self.assertTrue(pd.isna(rows.loc[file_id, "llm_review_overall_0_10"]))
            self.assertTrue(pd.isna(rows.loc[file_id, "llm_color_0_10"]))
            self.assertTrue(pd.isna(rows.loc[file_id, "recommendation_0_10"]))


if __name__ == "__main__":
    unittest.main()
