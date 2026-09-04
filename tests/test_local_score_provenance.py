from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from culvia.local_score_provenance import (
    current_local_score_context,
    local_score_provenance_payload,
    preserve_local_result_states,
    resolve_local_score_dataframe,
)
from culvia.recommendation import FILTER_DEFAULTS, enrich_scores_for_display
from culvia.schema import (
    MODEL_CAPABILITIES,
    MODEL_CLIP_AESTHETIC,
    MODEL_CLIP_IQA,
    MODEL_CORE_AESTHETIC,
    MODEL_RESULT_STATE_COLUMNS,
    MODEL_RESULT_VERSION_COLUMNS,
    field_group_for_model,
)


def complete_scores(model_key: str, value: float = 7.0) -> dict[str, float]:
    return {column: value for column in field_group_for_model(model_key).cache_columns}


class LocalScoreProvenanceTests(unittest.TestCase):
    def test_current_context_masks_a_copy_without_building_a_dataframe(self) -> None:
        source = {
            "file_id": "stale",
            **complete_scores(MODEL_CORE_AESTHETIC, 9.0),
            MODEL_RESULT_VERSION_COLUMNS[MODEL_CORE_AESTHETIC]: "score-v1:old",
        }

        with patch(
            "culvia.local_score_provenance.pd.DataFrame",
            side_effect=AssertionError("per-record context must not build a DataFrame"),
        ):
            context = current_local_score_context(source)

        self.assertEqual(float(source["overall_0_10"]), 9.0)
        self.assertTrue(pd.isna(context["overall_0_10"]))
        self.assertEqual(context[MODEL_RESULT_STATE_COLUMNS[MODEL_CORE_AESTHETIC]], "stale")

    def test_resolution_masks_noncurrent_scores_without_mutating_source(self) -> None:
        current_version = MODEL_CAPABILITIES[MODEL_CORE_AESTHETIC].result_version
        rows = [
            {
                "file_id": "current",
                **complete_scores(MODEL_CORE_AESTHETIC),
                MODEL_RESULT_VERSION_COLUMNS[MODEL_CORE_AESTHETIC]: current_version,
            },
            {"file_id": "legacy", **complete_scores(MODEL_CORE_AESTHETIC, 8.0)},
            {
                "file_id": "stale",
                **complete_scores(MODEL_CORE_AESTHETIC, 9.0),
                MODEL_RESULT_VERSION_COLUMNS[MODEL_CORE_AESTHETIC]: "score-v1:old",
            },
            {
                "file_id": "incomplete",
                "overall_0_10": 6.0,
                MODEL_RESULT_VERSION_COLUMNS[MODEL_CORE_AESTHETIC]: current_version,
            },
            {"file_id": "missing"},
        ]
        source = pd.DataFrame(rows)

        resolution = resolve_local_score_dataframe(source)
        resolved = resolution.dataframe.set_index("file_id")

        self.assertEqual(float(source.set_index("file_id").loc["legacy", "overall_0_10"]), 8.0)
        self.assertEqual(float(resolved.loc["current", "overall_0_10"]), 7.0)
        for file_id in ("legacy", "stale", "incomplete", "missing"):
            self.assertTrue(pd.isna(resolved.loc[file_id, "overall_0_10"]))
        self.assertEqual(
            resolution.summary[MODEL_CORE_AESTHETIC],
            {"current": 1, "legacy": 1, "stale": 1, "incomplete": 1, "missing": 1},
        )

    def test_shared_clip_capabilities_are_resolved_independently(self) -> None:
        row = {
            "file_id": "photo-1",
            **complete_scores(MODEL_CLIP_IQA, 8.0),
            **complete_scores(MODEL_CLIP_AESTHETIC, 6.0),
            MODEL_RESULT_VERSION_COLUMNS[MODEL_CLIP_IQA]: "score-v1:old",
            MODEL_RESULT_VERSION_COLUMNS[MODEL_CLIP_AESTHETIC]: MODEL_CAPABILITIES[MODEL_CLIP_AESTHETIC].result_version,
        }

        resolved = resolve_local_score_dataframe(pd.DataFrame([row])).dataframe.iloc[0]
        payload = local_score_provenance_payload(resolved)

        self.assertTrue(pd.isna(resolved["clip_iqa_overall_0_10"]))
        self.assertEqual(float(resolved["clip_aesthetic_0_10"]), 6.0)
        self.assertEqual(payload[MODEL_CLIP_IQA]["state"], "stale")
        self.assertEqual(payload[MODEL_CLIP_AESTHETIC]["state"], "current")
        self.assertEqual(payload[MODEL_CLIP_IQA]["storedResultVersion"], "score-v1:old")

    def test_state_columns_survive_strict_score_normalization(self) -> None:
        source = resolve_local_score_dataframe(
            pd.DataFrame([{"file_id": "legacy", **complete_scores(MODEL_CORE_AESTHETIC)}])
        ).dataframe
        normalized = pd.DataFrame([{"file_id": "legacy"}])

        preserved = preserve_local_result_states(source, normalized)

        self.assertEqual(
            preserved.loc[0, MODEL_RESULT_STATE_COLUMNS[MODEL_CORE_AESTHETIC]],
            "legacy",
        )

    def test_empty_export_still_declares_all_result_state_columns(self) -> None:
        preserved = preserve_local_result_states(
            pd.DataFrame(),
            pd.DataFrame(columns=["file_id"]),
        )

        self.assertTrue(set(MODEL_RESULT_STATE_COLUMNS.values()).issubset(preserved.columns))
        self.assertTrue(preserved.empty)

    def test_recommendation_recomputes_from_current_signals_when_other_models_are_missing(self) -> None:
        core_only = {
            "file_id": "core-only",
            "recommendation_0_10": 8.4,
            **complete_scores(MODEL_CORE_AESTHETIC, 8.0),
            MODEL_RESULT_VERSION_COLUMNS[MODEL_CORE_AESTHETIC]: MODEL_CAPABILITIES[MODEL_CORE_AESTHETIC].result_version,
        }
        core_only_resolved = resolve_local_score_dataframe(pd.DataFrame([core_only])).dataframe.iloc[0]
        self.assertEqual(float(core_only_resolved["recommendation_0_10"]), 8.4)

        row = {
            "file_id": "photo-1",
            **complete_scores(MODEL_CORE_AESTHETIC, 8.0),
            **complete_scores(MODEL_CLIP_IQA, 10.0),
            MODEL_RESULT_VERSION_COLUMNS[MODEL_CORE_AESTHETIC]: MODEL_CAPABILITIES[MODEL_CORE_AESTHETIC].result_version,
            MODEL_RESULT_VERSION_COLUMNS[MODEL_CLIP_IQA]: "score-v1:old",
        }
        resolved = resolve_local_score_dataframe(pd.DataFrame([row])).dataframe

        enriched = enrich_scores_for_display(
            resolved,
            FILTER_DEFAULTS,
            normalize_dataframe=lambda frame: frame.copy(),
            score_fields=(
                *field_group_for_model(MODEL_CORE_AESTHETIC).fields,
                *field_group_for_model(MODEL_CLIP_IQA).fields,
                *field_group_for_model(MODEL_CLIP_AESTHETIC).fields,
            ),
        )

        self.assertAlmostEqual(float(enriched.loc[0, "recommendation_0_10"]), 8.0)
        self.assertTrue(pd.isna(enriched.loc[0, "clip_iqa_overall_0_10"]))


if __name__ == "__main__":
    unittest.main()
