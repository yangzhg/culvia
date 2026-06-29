from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from culvia.schema import (
    MODEL_BASIC_TECHNICAL,
    MODEL_CLIP_AESTHETIC,
    MODEL_CLIP_IQA,
    MODEL_CORE_AESTHETIC,
    MODEL_LLM_REVIEW,
)


EVALUATION_ORDER: tuple[tuple[str, str], ...] = (
    (MODEL_CORE_AESTHETIC, "stage.coreAesthetic"),
    (MODEL_BASIC_TECHNICAL, "stage.basicTechnical"),
    (MODEL_CLIP_IQA, "stage.clipIqa"),
    (MODEL_CLIP_AESTHETIC, "stage.clipAesthetic"),
    (MODEL_LLM_REVIEW, "stage.llmReview"),
)

STATE_COMPLETED_MODELS: dict[str, set[str]] = {
    "started": set(),
    "aesthetic_done": {MODEL_CORE_AESTHETIC},
    "technical_done": {MODEL_CORE_AESTHETIC, MODEL_BASIC_TECHNICAL},
    "clip_done": {MODEL_CORE_AESTHETIC, MODEL_BASIC_TECHNICAL, MODEL_CLIP_IQA, MODEL_CLIP_AESTHETIC},
    "llm_done": {MODEL_CORE_AESTHETIC, MODEL_BASIC_TECHNICAL, MODEL_CLIP_IQA, MODEL_CLIP_AESTHETIC, MODEL_LLM_REVIEW},
    "reviewed": {MODEL_CORE_AESTHETIC, MODEL_BASIC_TECHNICAL, MODEL_CLIP_IQA, MODEL_CLIP_AESTHETIC, MODEL_LLM_REVIEW},
    "scored": {MODEL_CORE_AESTHETIC, MODEL_BASIC_TECHNICAL, MODEL_CLIP_IQA, MODEL_CLIP_AESTHETIC},
    "inspected": {MODEL_BASIC_TECHNICAL},
}

ACTIVE_LABEL_BY_STATE = {
    "started": "stage.preparingPhoto",
    "cached": "stage.readingCache",
    "reviewed": "stage.reviewDone",
    "inspected": "stage.inspectDone",
    "error": "stage.failed",
}

DONE_INDEX_STATES = {"cached", "reviewed", "inspected", "scored", "error"}


@dataclass(frozen=True)
class ScoringProgress:
    # All text fields hold i18n keys resolved by the web UI, not display text.
    title_key: str
    current_index: int
    active_evaluation: str
    completed_evaluations: list[str]


def progress_title(state: str) -> str:
    if state == "cached":
        return "stage.readingCache"
    if state in {"reviewed", "llm_done", "clip_done"}:
        return "jobText.evaluating"
    if state in {"inspected", "technical_done"}:
        return "jobText.inspecting"
    if state == "started":
        return "stage.preparingPhoto"
    return "jobText.scoring"


def completed_evaluations(state: str, selected_models: Iterable[str]) -> list[str]:
    if state == "cached":
        return ["stage.cache"]
    selected = set(str(model_key) for model_key in selected_models)
    completed_keys = STATE_COMPLETED_MODELS.get(state, set())
    return [label for model_key, label in EVALUATION_ORDER if model_key in selected and model_key in completed_keys]


def active_evaluation(state: str, selected_models: Iterable[str]) -> str:
    if state in ACTIVE_LABEL_BY_STATE:
        return ACTIVE_LABEL_BY_STATE[state]
    completed_keys = STATE_COMPLETED_MODELS.get(state, set())
    selected = set(str(model_key) for model_key in selected_models)
    for model_key, label in EVALUATION_ORDER:
        if model_key in selected and model_key not in completed_keys:
            return label
    return "stage.finalizing"


def current_index(done: int, total: int, state: str) -> int:
    return done if state in DONE_INDEX_STATES else min(done + 1, total)


def scoring_progress(done: int, total: int, state: str, selected_models: Iterable[str]) -> ScoringProgress:
    state_text = str(state)
    return ScoringProgress(
        title_key=progress_title(state_text),
        current_index=current_index(done, total, state_text),
        active_evaluation=active_evaluation(state_text, selected_models),
        completed_evaluations=completed_evaluations(state_text, selected_models),
    )
