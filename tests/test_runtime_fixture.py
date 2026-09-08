from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from culvia import schema, scoring
from culvia.local_score_provenance import resolve_local_score_dataframe
from tools.prepare_runtime_fixture import write_fixture


class RuntimeFixtureTests(unittest.TestCase):
    def test_fixture_persists_current_local_model_scores(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = write_fixture(Path(tmp) / "fixture", count=2)
            stored = scoring.load_cache_records(Path(str(fixture["cachePath"])))

        for _, row in stored.iterrows():
            for model_key in schema.VERSIONED_LOCAL_MODEL_KEYS:
                self.assertEqual(schema.model_result_state(row, model_key), "current")

        resolution = resolve_local_score_dataframe(stored)
        for model_key in schema.VERSIONED_LOCAL_MODEL_KEYS:
            self.assertEqual(resolution.summary[model_key]["current"], 2)
            for column in schema.model_output_columns(model_key):
                self.assertTrue(resolution.dataframe[column].notna().all(), f"masked fixture column: {column}")
        self.assertTrue(resolution.dataframe[schema.RECOMMENDATION_COLUMN].notna().all())

    def test_fixture_binds_llm_scores_to_current_default_insights(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = write_fixture(Path(tmp) / "fixture", count=2)
            cache_path = Path(str(fixture["cachePath"]))
            scores = scoring.load_cache_records(cache_path).set_index("file_id")
            insights = scoring.load_analysis_insights(cache_path)

        self.assertEqual(len(insights), 2)
        for insight in insights:
            self.assertEqual(insight.provider, "openai-compatible")
            self.assertEqual(insight.model, scoring.DEFAULT_LLM_MODEL)
            self.assertEqual(
                float(scores.loc[insight.file_id, scoring.LLM_REVIEW_GENERATION_COLUMN]),
                insight.created_at,
            )


if __name__ == "__main__":
    unittest.main()
