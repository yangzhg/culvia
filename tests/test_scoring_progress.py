from __future__ import annotations

import unittest

from culvia import schema
from culvia.scoring_progress import (
    active_evaluation,
    completed_evaluations,
    current_index,
    progress_title,
    scoring_progress,
)


class ScoringProgressTests(unittest.TestCase):
    def test_cached_state_reports_cache_read(self) -> None:
        progress = scoring_progress(
            3,
            10,
            "cached",
            [schema.MODEL_CORE_AESTHETIC, schema.MODEL_BASIC_TECHNICAL],
        )

        self.assertEqual(progress.title_key, "stage.readingCache")
        self.assertEqual(progress.current_index, 3)
        self.assertEqual(progress.active_evaluation, "stage.readingCache")
        self.assertEqual(progress.completed_evaluations, ["stage.cache"])

    def test_technical_done_moves_to_next_selected_model(self) -> None:
        selected = [
            schema.MODEL_CORE_AESTHETIC,
            schema.MODEL_BASIC_TECHNICAL,
            schema.MODEL_CLIP_IQA,
            schema.MODEL_LLM_REVIEW,
        ]

        progress = scoring_progress(0, 5, "technical_done", selected)

        self.assertEqual(progress.title_key, "jobText.inspecting")
        self.assertEqual(progress.current_index, 1)
        self.assertEqual(progress.active_evaluation, "stage.clipIqa")
        self.assertEqual(progress.completed_evaluations, ["stage.coreAesthetic", "stage.basicTechnical"])

    def test_llm_done_marks_all_selected_models_completed(self) -> None:
        selected = [
            schema.MODEL_CORE_AESTHETIC,
            schema.MODEL_BASIC_TECHNICAL,
            schema.MODEL_CLIP_IQA,
            schema.MODEL_CLIP_AESTHETIC,
            schema.MODEL_LLM_REVIEW,
        ]

        self.assertEqual(active_evaluation("llm_done", selected), "stage.finalizing")
        self.assertEqual(
            completed_evaluations("llm_done", selected),
            ["stage.coreAesthetic", "stage.basicTechnical", "stage.clipIqa", "stage.clipAesthetic", "stage.llmReview"],
        )

    def test_started_and_error_index_rules_match_previous_ui_behavior(self) -> None:
        self.assertEqual(progress_title("started"), "stage.preparingPhoto")
        self.assertEqual(active_evaluation("started", []), "stage.preparingPhoto")
        self.assertEqual(current_index(0, 7, "started"), 1)
        self.assertEqual(current_index(6, 7, "error"), 6)


if __name__ == "__main__":
    unittest.main()
