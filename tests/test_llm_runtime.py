from __future__ import annotations

import json
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import pandas as pd

from culvia.llm_runtime import (
    build_llm_review_request_payload,
    build_score_context_lines,
    llm_prompt_signature,
    score_llm_review_image,
)


@dataclass(frozen=True)
class DummyGroup:
    key: str
    fields: tuple[str, ...]
    labels: Mapping[str, str]


def score_column(field: str, scale: str = "0_10") -> str:
    return f"{field}_{scale}"


class LLMRuntimeTests(unittest.TestCase):
    def test_prompt_signature_changes_with_input_mode_and_prompt_text(self) -> None:
        first = llm_prompt_signature("photo-review-v3", "image", "balanced", "艺术表达优先")
        second = llm_prompt_signature("photo-review-v3", "text", "balanced", "艺术表达优先")
        third = llm_prompt_signature("photo-review-v3", "image", "balanced", "严格技术")

        self.assertTrue(first.startswith("photo-review-v3:image:balanced:"))
        self.assertNotEqual(first, second)
        self.assertNotEqual(first, third)

    def test_build_score_context_lines_skips_excluded_group_and_missing_scores(self) -> None:
        lines = build_score_context_lines(
            {
                "overall_0_10": 7.234,
                "technical_overall_0_10": 6.2,
                "llm_review_overall_0_10": 9.1,
                "missing_0_10": pd.NA,
            },
            field_groups=(
                DummyGroup("core", ("overall",), {"overall": "总分"}),
                DummyGroup("technical", ("technical_overall", "missing"), {"technical_overall": "技术"}),
                DummyGroup("llm_review", ("llm_review_overall",), {"llm_review_overall": "大模型"}),
            ),
            excluded_group_key="llm_review",
            score_column=score_column,
        )

        self.assertEqual(lines, ["- 总分: 7.2/10", "- 技术: 6.2/10"])

    def test_text_payload_does_not_request_image_data_url(self) -> None:
        calls: list[Path] = []

        payload = build_llm_review_request_payload(
            Path("/photos/a.jpg"),
            model="mock-vlm",
            input_mode="text",
            prompt_text="请评估",
            score_context={"overall_0_10": 7.0},
            score_context_lines=lambda _record: ["- 总分: 7.0/10"],
            image_data_url=lambda path: calls.append(Path(path)) or "data:image/jpeg;base64,abc",
        )

        user_content = payload["messages"][1]["content"]
        self.assertEqual(calls, [])
        self.assertIsInstance(user_content, str)
        self.assertIn("文件名：a.jpg", user_content)
        self.assertNotIn("image_url", user_content)

    def test_image_payload_includes_low_detail_image_url(self) -> None:
        payload = build_llm_review_request_payload(
            Path("/photos/a.jpg"),
            model="mock-vlm",
            input_mode="image",
            prompt_text="请评估",
            score_context=None,
            score_context_lines=lambda _record: [],
            image_data_url=lambda _path: "data:image/jpeg;base64,abc",
        )

        user_content = payload["messages"][1]["content"]
        self.assertIsInstance(user_content, list)
        self.assertEqual(user_content[1]["image_url"]["url"], "data:image/jpeg;base64,abc")
        self.assertEqual(user_content[1]["image_url"]["detail"], "low")

    def test_score_llm_review_image_returns_scores_and_insight(self) -> None:
        sent_payloads: list[dict[str, object]] = []

        def request_sender(payload: dict[str, object]) -> Mapping[str, object]:
            sent_payloads.append(payload)
            content = {
                "title": "画面有气质",
                "summary": "主体明确，色彩安静。",
                "explanation": "构图和情绪较好，技术问题轻微。",
                "confidence": 1.4,
                "scores": {
                    "aesthetic": {
                        "overall": 8.0,
                        "composition": 8.2,
                        "lighting": 7.5,
                    },
                    "technical": {
                        "overall": 6.0,
                    },
                },
                "retouching_suggestions": ["微调高光"],
            }
            return {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]}

        output = score_llm_review_image(
            Path("/photos/a.jpg"),
            file_id="file-1",
            score_context={"overall_0_10": 7.0},
            analyzer_key="llm_review",
            provider="unit-provider",
            model="mock-vlm",
            prompt_version="prompt-v1",
            prompt_text="请评估",
            input_mode="text",
            score_context_lines=lambda _record: ["- 总分: 7.0/10"],
            image_data_url=lambda _path: "unused",
            api_key="unit-key",
            endpoint="https://example.test/v1/chat/completions",
            timeout=3.0,
            aesthetic_weight=0.75,
            technical_weight=0.25,
            request_sender=request_sender,
        )

        self.assertEqual(len(sent_payloads), 1)
        self.assertAlmostEqual(output.scores["llm_review_overall"], 7.5)
        insight = output.insights[0]
        self.assertEqual(insight.file_id, "file-1")
        self.assertEqual(insight.provider, "unit-provider")
        self.assertEqual(insight.model, "mock-vlm")
        self.assertEqual(insight.prompt_version, "prompt-v1")
        self.assertEqual(insight.title, "画面有气质")
        self.assertEqual(insight.confidence, 1.0)
        self.assertEqual(insight.suggestions, ("修图：微调高光",))


if __name__ == "__main__":
    unittest.main()
