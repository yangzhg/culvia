from __future__ import annotations

import unittest

import pandas as pd

from culvia.acceptance import (
    AcceptancePolicy,
    acceptance_mark_plan,
    acceptance_score,
    acceptance_source,
    manual_rating_from_score,
    normalize_acceptance_basis,
    pick_status_from_score,
)


class AcceptanceTests(unittest.TestCase):
    def test_acceptance_score_maps_to_manual_decision(self) -> None:
        row = pd.Series({"recommendation_0_10": 7.4, "llm_review_overall_0_10": 4.9})

        self.assertEqual(manual_rating_from_score(7.4), 4)
        self.assertEqual(pick_status_from_score(7.4), "pick")
        self.assertEqual(acceptance_score(row, "model"), 7.4)
        self.assertEqual(pick_status_from_score(acceptance_score(row, "llm")), "reject")

    def test_acceptance_basis_and_source_are_normalized(self) -> None:
        self.assertEqual(normalize_acceptance_basis("llm"), "llm")
        self.assertEqual(normalize_acceptance_basis("unknown"), "model")
        self.assertEqual(acceptance_source("model", "current"), "model")
        self.assertEqual(acceptance_source("llm", "current"), "llm")
        self.assertEqual(acceptance_source("model", "filtered"), "model_batch")
        self.assertEqual(acceptance_source("llm", "selected"), "llm_batch")

    def test_acceptance_mark_plan_builds_marks_and_counts_skips(self) -> None:
        rows = pd.DataFrame(
            [
                {"file_id": "photo-1", "recommendation_0_10": 8.2, "llm_review_overall_0_10": 6.1},
                {"file_id": "photo-2", "recommendation_0_10": None, "llm_review_overall_0_10": 7.4},
            ]
        )

        model_plan = acceptance_mark_plan(rows, "model", "filtered")
        llm_plan = acceptance_mark_plan(rows, "llm", "selected")

        self.assertEqual(model_plan.source, "model_batch")
        self.assertEqual(model_plan.skipped, 1)
        self.assertEqual(len(model_plan.marks), 1)
        self.assertEqual(model_plan.marks[0]["file_id"], "photo-1")
        self.assertEqual(model_plan.marks[0]["status"], "pick")
        self.assertEqual(model_plan.marks[0]["rating"], 4)
        self.assertEqual(llm_plan.source, "llm_batch")
        self.assertEqual(llm_plan.skipped, 0)
        self.assertEqual([mark["file_id"] for mark in llm_plan.marks], ["photo-1", "photo-2"])
        self.assertEqual(llm_plan.marks[0]["status"], "")
        self.assertEqual(llm_plan.marks[1]["status"], "pick")

    def test_acceptance_policy_can_adjust_thresholds_and_rating_scale(self) -> None:
        policy = AcceptancePolicy(pick_threshold=8.0, reject_threshold=6.0, star_scale=2.5)
        rows = pd.DataFrame(
            [
                {"file_id": "photo-1", "recommendation_0_10": 7.4},
                {"file_id": "photo-2", "recommendation_0_10": 5.9},
                {"file_id": "photo-3", "recommendation_0_10": 8.8},
            ]
        )

        plan = acceptance_mark_plan(rows, "model", "filtered", policy)

        self.assertEqual(manual_rating_from_score(7.4, policy), 3)
        self.assertEqual(pick_status_from_score(7.4, policy), "")
        self.assertEqual(pick_status_from_score(5.9, policy), "reject")
        self.assertEqual([mark["status"] for mark in plan.marks], ["", "reject", "pick"])
        self.assertEqual([mark["rating"] for mark in plan.marks], [3, 2, 4])

    def test_acceptance_policy_uses_safe_rating_scale(self) -> None:
        policy = AcceptancePolicy(star_scale=0)

        self.assertEqual(manual_rating_from_score(7.4, policy), 4)


if __name__ == "__main__":
    unittest.main()
