from __future__ import annotations

import unittest

from culvia.llm_prompt import (
    LLM_REVIEW_USER_PROMPT,
    build_image_prompt,
    build_llm_review_payload,
    build_text_only_prompt,
)


class LLMReviewPromptTests(unittest.TestCase):
    def test_default_prompt_prioritizes_aesthetic_expression_over_flat_technical_rules(self) -> None:
        self.assertIn("艺术性", LLM_REVIEW_USER_PROMPT)
        self.assertIn("情绪感染力", LLM_REVIEW_USER_PROMPT)
        self.assertIn("75%", LLM_REVIEW_USER_PROMPT)
        self.assertIn("光影是否均匀不是固定好坏标准", LLM_REVIEW_USER_PROMPT)

    def test_text_only_prompt_includes_filename_and_score_context_without_image_claims(self) -> None:
        prompt = build_text_only_prompt(
            filename="portrait.jpg",
            score_context_lines=["- 总分: 7.2/10", "- 技术质检: 6.3/10"],
            prompt_text="额外关注主体表达",
        )

        self.assertIn("请不要声称你直接看到了照片", prompt)
        self.assertIn("文件名：portrait.jpg", prompt)
        self.assertIn("- 总分: 7.2/10", prompt)
        self.assertIn("额外关注主体表达", prompt)

    def test_image_payload_uses_image_url_content(self) -> None:
        payload = build_llm_review_payload(
            model="mock-vlm",
            input_mode="image",
            prompt_text="综合评审",
            image_data_url="data:image/jpeg;base64,abc",
        )
        user_content = payload["messages"][1]["content"]

        self.assertEqual(payload["model"], "mock-vlm")
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertIsInstance(user_content, list)
        self.assertEqual(user_content[1]["image_url"]["url"], "data:image/jpeg;base64,abc")
        self.assertIn("综合评审", build_image_prompt("综合评审"))

    def test_text_payload_uses_text_system_prompt_and_no_image_url(self) -> None:
        payload = build_llm_review_payload(
            model="mock-vlm",
            input_mode="text",
            prompt_text="严格一点",
            filename="photo.jpg",
            score_context_lines=["- 总分: 7.0/10"],
        )
        user_content = payload["messages"][1]["content"]

        self.assertIsInstance(user_content, str)
        self.assertIn("不是照片本身", payload["messages"][0]["content"])
        self.assertIn("文件名：photo.jpg", user_content)
        self.assertNotIn("image_url", user_content)


if __name__ == "__main__":
    unittest.main()
