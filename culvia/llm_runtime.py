from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import pandas as pd

from culvia.insight_store import AnalysisInsight
from culvia.llm_client import post_openai_compatible_chat
from culvia.llm_prompt import build_image_prompt, build_llm_review_payload, build_text_only_prompt
from culvia.llm_review import (
    extract_json_mapping,
    first_text_choice,
    llm_float,
    llm_review_scores,
    llm_suggestions,
)


class ScoreFieldGroup(Protocol):
    key: str
    fields: tuple[str, ...]
    labels: Mapping[str, str]


ScoreColumn = Callable[[str, str], str]
ImageDataUrl = Callable[[str | Path], str]
RequestSender = Callable[[dict[str, object]], Mapping[str, object]]


@dataclass(frozen=True)
class AnalyzerOutput:
    scores: Mapping[str, float] = field(default_factory=dict)
    insights: tuple[AnalysisInsight, ...] = ()


def llm_prompt_signature(base_version: str, input_mode: str, prompt_preset: str, prompt_text: str) -> str:
    prompt_hash = hashlib.sha1(prompt_text.encode("utf-8")).hexdigest()[:10]
    return f"{base_version}:{input_mode}:{prompt_preset}:{prompt_hash}"


def build_score_context_lines(
    record: Mapping[str, object] | None,
    *,
    field_groups: Iterable[ScoreFieldGroup],
    excluded_group_key: str,
    score_column: ScoreColumn,
) -> list[str]:
    if not record:
        return []

    lines: list[str] = []
    for group in field_groups:
        if group.key == excluded_group_key:
            continue
        for field_name in group.fields:
            column = score_column(field_name, "0_10")
            value = record.get(column)
            try:
                numeric = float(value)
            except Exception:
                continue
            if pd.isna(numeric):
                continue
            label = str(group.labels.get(field_name) or field_name)
            lines.append(f"- {label}: {numeric:.1f}/10")
    return lines


def build_llm_text_only_prompt(
    path: str | Path,
    *,
    score_context: Mapping[str, object] | None,
    score_context_lines: Callable[[Mapping[str, object] | None], list[str]],
    prompt_text: str,
) -> str:
    return build_text_only_prompt(
        filename=Path(path).name,
        score_context_lines=score_context_lines(score_context),
        prompt_text=prompt_text,
    )


def build_llm_image_prompt(prompt_text: str) -> str:
    return build_image_prompt(prompt_text)


def build_llm_review_request_payload(
    path: str | Path,
    *,
    model: str,
    input_mode: str,
    prompt_text: str,
    score_context: Mapping[str, object] | None,
    score_context_lines: Callable[[Mapping[str, object] | None], list[str]],
    image_data_url: ImageDataUrl,
) -> dict[str, object]:
    return build_llm_review_payload(
        model=model,
        input_mode=input_mode,
        prompt_text=prompt_text,
        filename=Path(path).name,
        score_context_lines=score_context_lines(score_context),
        image_data_url="" if input_mode == "text" else image_data_url(path),
    )


def post_llm_review_request(
    payload: dict[str, object],
    *,
    api_key: str,
    endpoint: str,
    timeout: float,
) -> dict[str, object]:
    return post_openai_compatible_chat(
        payload,
        api_key=api_key,
        endpoint=endpoint,
        timeout=timeout,
    )


def score_llm_review_image(
    path: str | Path,
    *,
    file_id: str,
    score_context: Mapping[str, object] | None,
    analyzer_key: str,
    provider: str,
    model: str,
    prompt_version: str,
    prompt_text: str,
    input_mode: str,
    score_context_lines: Callable[[Mapping[str, object] | None], list[str]],
    image_data_url: ImageDataUrl,
    api_key: str,
    endpoint: str,
    timeout: float,
    aesthetic_weight: float,
    technical_weight: float,
    request_sender: RequestSender | None = None,
) -> AnalyzerOutput:
    payload = build_llm_review_request_payload(
        path,
        model=model,
        input_mode=input_mode,
        prompt_text=prompt_text,
        score_context=score_context,
        score_context_lines=score_context_lines,
        image_data_url=image_data_url,
    )
    if request_sender is None:
        response_json = post_llm_review_request(payload, api_key=api_key, endpoint=endpoint, timeout=timeout)
    else:
        response_json = request_sender(payload)

    review_json = extract_json_mapping(first_text_choice(response_json))
    scores = llm_review_scores(
        review_json,
        aesthetic_weight=aesthetic_weight,
        technical_weight=technical_weight,
    )
    confidence = llm_float(review_json.get("confidence"))
    overall = scores.get("llm_review_overall")
    insight = AnalysisInsight(
        file_id=file_id,
        analyzer_key=analyzer_key,
        provider=provider,
        model=model,
        model_version=model,
        prompt_version=prompt_version,
        score=None if overall is None else round(float(overall), 4),
        confidence=None if confidence is None else max(0.0, min(confidence, 1.0)),
        title=str(review_json.get("title") or "大模型评价").strip(),
        summary=str(review_json.get("summary") or "").strip(),
        explanation=str(review_json.get("explanation") or "").strip(),
        suggestions=llm_suggestions(review_json),
        raw_json=review_json,
    )
    return AnalyzerOutput(scores=scores, insights=(insight,))
