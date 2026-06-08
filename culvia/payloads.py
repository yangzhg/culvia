from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd

from culvia.curation import (
    PhotoMark,
    color_label_text,
    manual_status_label,
    mark_source_label,
    normalize_color_label,
    normalize_manual_rating,
)
from culvia.recommendation import numeric_column, numeric_score


@dataclass(frozen=True)
class PhotoPayloadFields:
    score_fields: tuple[str, ...]
    technical_fields: tuple[str, ...]
    model_quality_fields: tuple[str, ...]
    aesthetic_reference_fields: tuple[str, ...]
    llm_review_fields: tuple[str, ...]


def score_text(value: float | None) -> str:
    return "暂无" if value is None else f"{value:.1f}"


def star_rating(value: float | None) -> str:
    if value is None:
        return "☆☆☆☆☆"
    stars = min(max(int(round(value / 10.0 * 5)), 0), 5)
    return "★" * stars + "☆" * (5 - stars)


def score_level(value: float | None) -> str:
    if value is None:
        return "未评分"
    if value >= 8.0:
        return "封面候选"
    if value >= 7.0:
        return "值得精修"
    if value >= 6.0:
        return "保留观察"
    return "谨慎保留"


def manual_rating_stars(value: int | None) -> str:
    rating = normalize_manual_rating(value)
    return "★" * rating + "☆" * (5 - rating)


def serialize_mark(mark: PhotoMark | None) -> dict[str, Any]:
    if mark is None:
        return {
            "rating": 0,
            "stars": manual_rating_stars(0),
            "status": "",
            "statusLabel": manual_status_label(""),
            "colorLabel": "",
            "colorLabelText": "",
            "source": "",
            "sourceLabel": "",
            "acceptedScore": None,
            "acceptedScoreText": "暂无",
            "updatedAt": None,
        }
    return {
        "rating": mark.rating,
        "stars": manual_rating_stars(mark.rating),
        "status": mark.status,
        "statusLabel": manual_status_label(mark.status),
        "colorLabel": normalize_color_label(mark.color_label),
        "colorLabelText": color_label_text(mark.color_label),
        "source": mark.source,
        "sourceLabel": mark_source_label(mark.source),
        "acceptedScore": mark.accepted_score,
        "acceptedScoreText": score_text(mark.accepted_score),
        "updatedAt": mark.updated_at,
    }


def technical_tags(scores: Mapping[str, float | None]) -> list[str]:
    tags: list[str] = []
    sharpness = scores.get("sharpness")
    exposure = scores.get("exposure")
    contrast = scores.get("contrast")
    cleanliness = scores.get("cleanliness")
    if sharpness is not None:
        tags.append("清晰稳定" if sharpness >= 7.2 else "清晰度风险" if sharpness < 5.0 else "清晰度一般")
    if exposure is not None and exposure < 5.2:
        tags.append("曝光需检查")
    elif exposure is not None and exposure >= 7.4:
        tags.append("曝光稳定")
    if cleanliness is not None and cleanliness < 5.4:
        tags.append("噪点风险")
    if contrast is not None and contrast >= 7.0:
        tags.append("层次清楚")
    return tags[:3]


def compact_text_list(value: object) -> list[str]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple)):
        items = [str(item) for item in value]
    else:
        items = []
    return [item.strip() for item in items if item.strip()][:6]


def serialize_insight(insight: Any | None) -> dict[str, Any] | None:
    if insight is None:
        return None
    raw = dict(insight.raw_json or {}) if isinstance(insight.raw_json, dict) else {}
    return {
        "title": insight.title,
        "summary": insight.summary,
        "explanation": insight.explanation,
        "suggestions": list(insight.suggestions),
        "photographySuggestions": compact_text_list(raw.get("photography_suggestions")),
        "retouchingSuggestions": compact_text_list(raw.get("retouching_suggestions")),
        "score": insight.score,
        "confidence": insight.confidence,
        "model": insight.model,
        "provider": insight.provider,
        "promptVersion": insight.prompt_version,
    }


def _score_texts(scores: Mapping[str, float | None], fields: tuple[str, ...]) -> dict[str, str]:
    return {field: score_text(scores[field]) for field in fields}


def _score_stars(scores: Mapping[str, float | None], fields: tuple[str, ...]) -> dict[str, str]:
    return {field: star_rating(scores[field]) for field in fields}


def serialize_photo(
    row: pd.Series,
    fields: PhotoPayloadFields,
    *,
    image_url: Callable[[str, int], str],
    thumbnail_url: Callable[[str], str],
    insight_by_file_id: Mapping[str, Any] | None = None,
    mark_by_file_id: Mapping[str, PhotoMark] | None = None,
) -> dict[str, Any]:
    path = str(row.get("path") or "")
    file_id = str(row.get("file_id") or "")
    scores = {field: numeric_score(row, field) for field in fields.score_fields}
    technical_scores = {field: numeric_score(row, field) for field in fields.technical_fields}
    model_quality_scores = {field: numeric_score(row, field) for field in fields.model_quality_fields}
    aesthetic_reference_scores = {field: numeric_score(row, field) for field in fields.aesthetic_reference_fields}
    llm_review_scores = {field: numeric_score(row, field) for field in fields.llm_review_fields}
    llm_insight = (insight_by_file_id or {}).get(file_id)
    overall = scores["overall"]
    recommendation = numeric_column(row, "recommendation_0_10")
    return {
        "id": photo_id(path),
        "fileId": file_id,
        "path": path,
        "image": image_url(path, 1800),
        "thumb": thumbnail_url(path),
        "preview": image_url(path, 2400),
        "recommendation": recommendation,
        "recommendationText": score_text(recommendation),
        "recommendationStars": star_rating(recommendation),
        "overall": overall,
        "overallText": score_text(overall),
        "stars": star_rating(overall),
        "level": score_level(recommendation),
        "scores": scores,
        "technicalScores": technical_scores,
        "modelQualityScores": model_quality_scores,
        "aestheticReferenceScores": aesthetic_reference_scores,
        "llmReviewScores": llm_review_scores,
        "scoreTexts": _score_texts(scores, fields.score_fields),
        "scoreStars": _score_stars(scores, fields.score_fields),
        "technicalTexts": _score_texts(technical_scores, fields.technical_fields),
        "technicalStars": _score_stars(technical_scores, fields.technical_fields),
        "modelQualityTexts": _score_texts(model_quality_scores, fields.model_quality_fields),
        "modelQualityStars": _score_stars(model_quality_scores, fields.model_quality_fields),
        "aestheticReferenceTexts": _score_texts(aesthetic_reference_scores, fields.aesthetic_reference_fields),
        "aestheticReferenceStars": _score_stars(aesthetic_reference_scores, fields.aesthetic_reference_fields),
        "llmReviewTexts": _score_texts(llm_review_scores, fields.llm_review_fields),
        "llmReviewStars": _score_stars(llm_review_scores, fields.llm_review_fields),
        "llmInsight": serialize_insight(llm_insight),
        "manual": serialize_mark((mark_by_file_id or {}).get(file_id)),
        "technicalTags": technical_tags(technical_scores),
    }


def summarize_scores(
    source_df: pd.DataFrame,
    filtered_df: pd.DataFrame,
    errors: pd.DataFrame,
    filters: Mapping[str, Any],
    *,
    enrich_scores_for_display: Callable[[pd.DataFrame, Mapping[str, Any]], pd.DataFrame],
) -> dict[str, Any]:
    successful = enrich_scores_for_display(source_df, filters)
    successful = successful[successful["error"].fillna("").eq("")].copy()
    scores = pd.to_numeric(successful["recommendation_0_10"], errors="coerce").dropna()
    return {
        "scored": int(len(scores)),
        "showing": int(len(filtered_df)),
        "errors": int(len(errors)),
        "best": score_text(None if scores.empty else float(scores.max())),
        "average": score_text(None if scores.empty else float(scores.mean())),
        "median": score_text(None if scores.empty else float(scores.median())),
    }


def photo_id(path: str) -> str:
    return hashlib.sha1(path.encode("utf-8")).hexdigest()[:16]
