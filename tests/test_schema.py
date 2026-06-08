from __future__ import annotations

import unittest

from culvia import schema


class SchemaTests(unittest.TestCase):
    def test_schema_describes_llm_review_as_optional_model(self) -> None:
        self.assertNotIn(schema.MODEL_LLM_REVIEW, schema.DEFAULT_SELECTED_MODELS)
        self.assertIn("llm_review_overall_0_10", schema.CSV_COLUMNS)
        self.assertIn("llm_composition_0_10", schema.CSV_COLUMNS)
        self.assertEqual(schema.MODEL_CAPABILITIES[schema.MODEL_LLM_REVIEW].provider, "openai-compatible")
        self.assertTrue(schema.MODEL_CAPABILITIES[schema.MODEL_LLM_REVIEW].supports_text_insights)


if __name__ == "__main__":
    unittest.main()
