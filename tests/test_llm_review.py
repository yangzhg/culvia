from __future__ import annotations

import unittest

from culvia.llm_review import (
    extract_json_mapping,
    first_text_choice,
    llm_review_scores,
    llm_suggestions,
    strip_json_fence,
)


class LLMReviewParsingTests(unittest.TestCase):
    def test_extract_json_mapping_accepts_fenced_and_wrapped_json(self) -> None:
        self.assertEqual(strip_json_fence('```json\n{"score": 7}\n```'), '{"score": 7}')
        self.assertEqual(
            extract_json_mapping('模型输出：{"score": 7, "title": "测试"} 结束')["score"],
            7,
        )

    def test_first_text_choice_supports_chat_and_content_parts(self) -> None:
        self.assertEqual(
            first_text_choice({"choices": [{"message": {"content": "hello"}}]}),
            "hello",
        )
        self.assertEqual(
            first_text_choice({"choices": [{"message": {"content": [{"text": "a"}, {"text": "b"}]}}]}),
            "a\nb",
        )
        self.assertEqual(first_text_choice({"choices": [{"text": "plain"}]}), "plain")

    def test_llm_suggestions_keep_photography_and_retouching_context(self) -> None:
        suggestions = llm_suggestions(
            {
                "photography_suggestions": ["靠近主体"],
                "retouching_suggestions": ["压暗背景"],
            }
        )

        self.assertEqual(suggestions, ("拍摄：靠近主体", "修图：压暗背景"))

    def test_llm_review_scores_parse_dimensions_and_aesthetic_weighted_fallback(self) -> None:
        scores = llm_review_scores(
            {
                "scores": {
                    "aesthetic": {"overall": 8.0, "composition": 8.5},
                    "technical": {"overall": 4.0, "sharpness": 3.5},
                }
            }
        )

        self.assertAlmostEqual(scores["llm_review_overall"], 7.0)
        self.assertAlmostEqual(scores["llm_aesthetic_overall"], 8.0)
        self.assertAlmostEqual(scores["llm_composition"], 8.5)
        self.assertAlmostEqual(scores["llm_technical_overall"], 4.0)
        self.assertAlmostEqual(scores["llm_sharpness"], 3.5)


if __name__ == "__main__":
    unittest.main()
