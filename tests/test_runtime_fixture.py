from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from culvia import scoring
from tools.prepare_runtime_fixture import write_fixture


class RuntimeFixtureTests(unittest.TestCase):
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
