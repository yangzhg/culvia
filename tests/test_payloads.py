from __future__ import annotations

import unittest

import pandas as pd

from culvia.curation import PhotoMark
from culvia.insight_store import AnalysisInsight
from culvia.payloads import (
    PhotoPayloadFields,
    compact_text_list,
    manual_rating_stars,
    score_level,
    score_text,
    serialize_insight,
    serialize_mark,
    serialize_photo,
    star_rating,
    summarize_scores,
    technical_tags,
)


class PayloadTests(unittest.TestCase):
    def test_score_labels_and_stars_are_human_readable(self) -> None:
        self.assertEqual(score_text(None), "暂无")
        self.assertEqual(score_text(7.234), "7.2")
        self.assertEqual(star_rating(None), "☆☆☆☆☆")
        self.assertEqual(star_rating(8.0), "★★★★☆")
        self.assertEqual(score_level(None), "未评分")
        self.assertEqual(score_level(8.2), "封面候选")
        self.assertEqual(score_level(6.4), "保留观察")

    def test_manual_mark_payload_normalizes_labels(self) -> None:
        self.assertEqual(manual_rating_stars(3), "★★★☆☆")

        empty = serialize_mark(None)
        self.assertEqual(empty["statusLabel"], "未判断")
        self.assertEqual(empty["acceptedScoreText"], "暂无")

        mark = PhotoMark(
            file_id="photo-1",
            rating=4,
            status="pick",
            color_label="green",
            source="llm",
            accepted_score=8.25,
            updated_at=123.0,
        )

        payload = serialize_mark(mark)

        self.assertEqual(payload["stars"], "★★★★☆")
        self.assertEqual(payload["statusLabel"], "入选")
        self.assertEqual(payload["colorLabelText"], "绿色")
        self.assertEqual(payload["sourceLabel"], "大模型")
        self.assertEqual(payload["acceptedScoreText"], "8.2")

    def test_insight_payload_keeps_compact_text_suggestions(self) -> None:
        insight = AnalysisInsight(
            file_id="photo-1",
            analyzer_key="llm_review",
            provider="dashscope",
            model="qwen-test",
            prompt_version="v1",
            score=7.6,
            confidence=0.82,
            title="有情绪的街景",
            summary="画面有不错的氛围。",
            explanation="主体明确，背景略散。",
            suggestions=("保留高光层次",),
            raw_json={
                "photography_suggestions": ["靠近主体", "等待更干净的背景", ""],
                "retouching_suggestions": "压暗边缘",
            },
        )

        payload = serialize_insight(insight)

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["title"], "有情绪的街景")
        self.assertEqual(payload["photographySuggestions"], ["靠近主体", "等待更干净的背景"])
        self.assertEqual(payload["retouchingSuggestions"], ["压暗边缘"])
        self.assertEqual(payload["promptVersion"], "v1")
        self.assertEqual(compact_text_list([" a ", "", "b"]), ["a", "b"])

    def test_photo_payload_uses_injected_urls_and_field_sets(self) -> None:
        fields = PhotoPayloadFields(
            score_fields=("overall", "composition"),
            technical_fields=("sharpness", "exposure", "contrast", "cleanliness"),
            model_quality_fields=("clip_iqa_overall",),
            aesthetic_reference_fields=("clip_aesthetic",),
            llm_review_fields=("llm_review_overall", "llm_aesthetic_overall", "llm_technical_overall"),
        )
        row = pd.Series(
            {
                "file_id": "photo-1",
                "path": "/photos/a.jpg",
                "recommendation_0_10": 7.8,
                "overall_0_10": 8.4,
                "composition_0_10": 7.1,
                "sharpness_0_10": 7.6,
                "exposure_0_10": 7.5,
                "contrast_0_10": 7.2,
                "cleanliness_0_10": 6.4,
                "clip_iqa_overall_0_10": 6.9,
                "clip_aesthetic_0_10": 7.4,
                "llm_review_overall_0_10": 7.7,
                "llm_aesthetic_overall_0_10": 8.1,
                "llm_technical_overall_0_10": 6.8,
            }
        )
        insight = AnalysisInsight(
            file_id="photo-1",
            analyzer_key="llm_review",
            provider="dashscope",
            model="qwen-test",
            title="标题",
        )
        mark = PhotoMark(file_id="photo-1", rating=5, status="pick", source="model", accepted_score=7.8)

        payload = serialize_photo(
            row,
            fields,
            image_url=lambda path, size, *, file_id="": f"/image?path={path}&size={size}&file_id={file_id}",
            thumbnail_url=lambda path, *, file_id="": f"/thumb?path={path}&file_id={file_id}",
            insight_by_file_id={"photo-1": insight},
            mark_by_file_id={"photo-1": mark},
        )

        self.assertEqual(payload["fileId"], "photo-1")
        self.assertEqual(payload["image"], "/image?path=/photos/a.jpg&size=1800&file_id=photo-1")
        self.assertEqual(payload["preview"], "/image?path=/photos/a.jpg&size=2400&file_id=photo-1")
        self.assertEqual(payload["thumb"], "/thumb?path=/photos/a.jpg&file_id=photo-1")
        self.assertEqual(payload["recommendationText"], "7.8")
        self.assertEqual(payload["recommendationStars"], "★★★★☆")
        self.assertEqual(payload["scoreTexts"]["overall"], "8.4")
        self.assertEqual(payload["technicalTexts"]["sharpness"], "7.6")
        self.assertEqual(payload["manual"]["sourceLabel"], "综合模型")
        self.assertEqual(payload["llmInsight"]["title"], "标题")
        self.assertIn("清晰稳定", payload["technicalTags"])
        self.assertIn("曝光稳定", payload["technicalTags"])

    def test_summary_payload_uses_injected_enrichment(self) -> None:
        source = pd.DataFrame([{"file_id": "a"}, {"file_id": "b"}, {"file_id": "c"}])
        filtered = pd.DataFrame([{"file_id": "a"}])
        errors = pd.DataFrame([{"file_id": "c"}])

        def enrich(df: pd.DataFrame, _filters: object) -> pd.DataFrame:
            return df.assign(recommendation_0_10=[8.0, 6.0, None], error=["", "", "bad"])

        payload = summarize_scores(
            source,
            filtered,
            errors,
            {},
            enrich_scores_for_display=enrich,
        )

        self.assertEqual(payload["scored"], 2)
        self.assertEqual(payload["showing"], 1)
        self.assertEqual(payload["errors"], 1)
        self.assertEqual(payload["best"], "8.0")
        self.assertEqual(payload["average"], "7.0")
        self.assertEqual(payload["median"], "7.0")

    def test_technical_tags_are_short_and_actionable(self) -> None:
        tags = technical_tags({"sharpness": 4.8, "exposure": 4.9, "contrast": 7.4, "cleanliness": 4.7})

        self.assertEqual(tags, ["清晰度风险", "曝光需检查", "噪点风险"])


if __name__ == "__main__":
    unittest.main()
