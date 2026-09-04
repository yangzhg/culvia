from __future__ import annotations

import unittest

from culvia import schema


class SchemaTests(unittest.TestCase):
    def test_schema_describes_llm_review_as_optional_model(self) -> None:
        self.assertNotIn(schema.MODEL_LLM_REVIEW, schema.DEFAULT_SELECTED_MODELS)
        self.assertIn("llm_review_overall_0_10", schema.CSV_COLUMNS)
        self.assertIn("llm_composition_0_10", schema.CSV_COLUMNS)
        self.assertIn(schema.LLM_REVIEW_GENERATION_COLUMN, schema.CSV_COLUMNS)
        self.assertEqual(schema.MODEL_CAPABILITIES[schema.MODEL_LLM_REVIEW].provider, "openai-compatible")
        self.assertTrue(schema.MODEL_CAPABILITIES[schema.MODEL_LLM_REVIEW].supports_text_insights)

    def test_local_model_capabilities_expose_pinned_revisions(self) -> None:
        self.assertEqual(
            schema.MODEL_CAPABILITIES[schema.MODEL_CORE_AESTHETIC].model_version,
            schema.MODEL_REVISION,
        )
        self.assertEqual(
            schema.MODEL_CAPABILITIES[schema.MODEL_CLIP_IQA].model_version,
            schema.CLIP_REFERENCE_MODEL_REVISION,
        )
        self.assertEqual(
            schema.MODEL_CAPABILITIES[schema.MODEL_CLIP_AESTHETIC].model_version,
            schema.CLIP_REFERENCE_MODEL_REVISION,
        )
        result_versions = {
            schema.MODEL_CAPABILITIES[model_key].result_version for model_key in schema.VERSIONED_LOCAL_MODEL_KEYS
        }
        self.assertEqual(len(result_versions), 3)
        self.assertTrue(all(version.startswith("score-v1:") for version in result_versions))
        self.assertEqual(
            set(schema.MODEL_RESULT_VERSION_COLUMNS.values()),
            {
                "core_aesthetic_result_version",
                "clip_iqa_result_version",
                "clip_aesthetic_result_version",
            },
        )
        self.assertTrue(set(schema.MODEL_RESULT_VERSION_COLUMNS.values()).issubset(schema.CSV_COLUMNS))

    def test_result_versions_bind_the_audited_scoring_contracts(self) -> None:
        self.assertEqual(
            {
                model_key: schema.MODEL_CAPABILITIES[model_key].result_version
                for model_key in schema.VERSIONED_LOCAL_MODEL_KEYS
            },
            {
                schema.MODEL_CORE_AESTHETIC: "score-v1:ec74e1bfa2dd790691d991178786ed0e5eb29e3dea4b2e2d74ae185e9ff9577a",
                schema.MODEL_CLIP_IQA: "score-v1:8514caeaf3f66f25fa09dfafb2a14435a3a419a244bbc861cc28c61f6437b1bd",
                schema.MODEL_CLIP_AESTHETIC: "score-v1:057e6799ab19f15e450a1bb3e74f3c2aac4078fba3b3c3eea8f472e82d23284a",
            },
        )

    def test_model_recompute_plan_requires_current_result_version_for_pinned_models(self) -> None:
        record = {"file_id": "image-1"}
        for column in schema.model_output_columns(schema.MODEL_CORE_AESTHETIC):
            record[column] = 8.0

        self.assertEqual(schema.model_result_state(record, schema.MODEL_CORE_AESTHETIC), "legacy")
        self.assertTrue(schema.model_recompute_plan(record, [schema.MODEL_CORE_AESTHETIC])[schema.MODEL_CORE_AESTHETIC])

        current = schema.stamp_model_result_version(record, schema.MODEL_CORE_AESTHETIC)

        self.assertEqual(schema.model_result_state(current, schema.MODEL_CORE_AESTHETIC), "current")
        self.assertFalse(
            schema.model_recompute_plan(current, [schema.MODEL_CORE_AESTHETIC])[schema.MODEL_CORE_AESTHETIC]
        )
        current[schema.model_output_columns(schema.MODEL_CORE_AESTHETIC)[0]] = None
        self.assertEqual(schema.model_result_state(current, schema.MODEL_CORE_AESTHETIC), "incomplete")
        self.assertTrue(
            schema.model_recompute_plan(current, [schema.MODEL_CORE_AESTHETIC])[schema.MODEL_CORE_AESTHETIC]
        )

        partial_legacy = {"overall_0_5": 4.0}
        self.assertEqual(schema.model_result_state(partial_legacy, schema.MODEL_CORE_AESTHETIC), "incomplete")


if __name__ == "__main__":
    unittest.main()
