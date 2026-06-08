from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import pandas as pd

from culvia.llm_config import normalize_llm_prompt_preset as _normalize_llm_prompt_preset
from culvia.model_files import (
    CLIP_REFERENCE_MODEL_ID,
    CLIP_REFERENCE_MODEL_REPO_DIR,
    MODEL_CACHE_REPO_DIR,
    MODEL_ID,
)

DEFAULT_LLM_MODEL = "gpt-4o-mini"
LLM_REVIEW_PROMPT_VERSION = "photo-review-v3"
LLM_OVERALL_AESTHETIC_WEIGHT = 0.75
LLM_OVERALL_TECHNICAL_WEIGHT = 0.25
DEFAULT_LLM_PROMPT_PRESET = "balanced"
LLM_PROMPT_PRESETS = {
    "balanced": {
        "label": "综合评审",
        "description": "艺术表达优先，技术作为辅助判断",
        "prompt": "请以专业但克制的选片顾问视角，把艺术性、情绪感染力、主体表达、构图关系、光影氛围和色彩气质作为主要判断；技术完成度用于识别会削弱表达的硬伤，不要让清晰度、曝光均匀、噪点等技术项压过有意图的审美表达。",
    },
    "technical": {
        "label": "严格技术",
        "description": "更重视清晰、曝光、噪点和瑕疵",
        "prompt": "请更严格检查清晰度、曝光、对比、噪点、伪影和失焦风险，明确指出技术扣分依据；不要把强反差、局部光或不均匀光影本身视为缺陷。",
    },
    "retouching": {
        "label": "精修建议",
        "description": "更重视可修空间和后期方向",
        "prompt": "请把重点放在这张照片是否值得精修，以及具体可执行的调色、裁切、局部明暗和瑕疵处理建议；保留服务画面气质的光影风格。",
    },
}

MODEL_CORE_AESTHETIC = "rsinema_aesthetic"
MODEL_CLIP_IQA = "clip_iqa"
MODEL_CLIP_AESTHETIC = "clip_aesthetic"
MODEL_BASIC_TECHNICAL = "basic_technical"
MODEL_LLM_REVIEW = "llm_review"
RUNTIME_CORE_AESTHETIC = MODEL_CORE_AESTHETIC
RUNTIME_CLIP_REFERENCE = "clip_reference"
RUNTIME_LOCAL = "local"
RUNTIME_LLM_REVIEW = MODEL_LLM_REVIEW


@dataclass(frozen=True)
class ScoreFieldGroup:
    key: str
    fields: tuple[str, ...]
    labels: Mapping[str, str]
    store_zero_to_five: bool = False

    @property
    def cache_columns(self) -> tuple[str, ...]:
        columns: list[str] = []
        for field in self.fields:
            if self.store_zero_to_five:
                columns.append(score_column(field, "0_5"))
            columns.append(score_column(field, "0_10"))
        return tuple(columns)

    @property
    def required_columns(self) -> tuple[str, ...]:
        return tuple(score_column(field, "0_10") for field in self.fields)


@dataclass(frozen=True)
class ModelCapability:
    key: str
    label: str
    subtitle: str
    model_id: str
    field_group_key: str
    runtime_key: str
    requires_download: bool
    repo_cache_dir: str | None = None
    default_enabled: bool = True
    provider: str = "local"
    model_version: str = ""
    prompt_version: str = ""
    supports_text_insights: bool = False


def score_column(field: str, scale: str = "0_10") -> str:
    return f"{field}_{scale}"


CORE_AESTHETIC_GROUP = ScoreFieldGroup(
    key="core_aesthetic",
    fields=("overall", "quality", "composition", "lighting", "color", "depth_of_field", "content"),
    labels={
        "overall": "总分",
        "quality": "画质 / 技术质量",
        "composition": "构图",
        "lighting": "光线",
        "color": "色彩",
        "depth_of_field": "景深",
        "content": "内容",
    },
    store_zero_to_five=True,
)
TECHNICAL_GROUP = ScoreFieldGroup(
    key="technical",
    fields=("technical_overall", "sharpness", "exposure", "contrast", "cleanliness"),
    labels={
        "technical_overall": "技术质检",
        "sharpness": "清晰度",
        "exposure": "曝光稳定",
        "contrast": "层次 / 对比",
        "cleanliness": "画面洁净度",
    },
)
MODEL_QUALITY_GROUP = ScoreFieldGroup(
    key="clip_iqa",
    fields=("clip_iqa_overall", "clip_iqa_sharpness", "clip_iqa_exposure", "clip_iqa_cleanliness"),
    labels={
        "clip_iqa_overall": "模型画质",
        "clip_iqa_sharpness": "模型清晰感",
        "clip_iqa_exposure": "模型曝光感",
        "clip_iqa_cleanliness": "模型洁净感",
    },
)
AESTHETIC_REFERENCE_GROUP = ScoreFieldGroup(
    key="clip_aesthetic",
    fields=("clip_aesthetic",),
    labels={"clip_aesthetic": "CLIP 审美参考"},
)
LLM_REVIEW_GROUP = ScoreFieldGroup(
    key="llm_review",
    fields=(
        "llm_review_overall",
        "llm_aesthetic_overall",
        "llm_quality",
        "llm_composition",
        "llm_lighting",
        "llm_color",
        "llm_depth_of_field",
        "llm_content",
        "llm_technical_overall",
        "llm_sharpness",
        "llm_exposure",
        "llm_contrast",
        "llm_cleanliness",
    ),
    labels={
        "llm_review_overall": "大模型总评",
        "llm_aesthetic_overall": "大模型审美",
        "llm_quality": "大模型画质",
        "llm_composition": "大模型构图",
        "llm_lighting": "大模型光线",
        "llm_color": "大模型色彩",
        "llm_depth_of_field": "大模型景深",
        "llm_content": "大模型内容",
        "llm_technical_overall": "大模型技术",
        "llm_sharpness": "大模型清晰度",
        "llm_exposure": "大模型曝光",
        "llm_contrast": "大模型层次",
        "llm_cleanliness": "大模型洁净度",
    },
)
FIELD_GROUPS = (
    CORE_AESTHETIC_GROUP,
    TECHNICAL_GROUP,
    MODEL_QUALITY_GROUP,
    AESTHETIC_REFERENCE_GROUP,
    LLM_REVIEW_GROUP,
)
FIELD_GROUP_BY_KEY = {group.key: group for group in FIELD_GROUPS}

SCORE_FIELDS = list(CORE_AESTHETIC_GROUP.fields)
SCORE_LABELS = dict(CORE_AESTHETIC_GROUP.labels)
TECHNICAL_FIELDS = list(TECHNICAL_GROUP.fields)
TECHNICAL_LABELS = dict(TECHNICAL_GROUP.labels)
MODEL_QUALITY_FIELDS = list(MODEL_QUALITY_GROUP.fields)
MODEL_QUALITY_LABELS = dict(MODEL_QUALITY_GROUP.labels)
AESTHETIC_REFERENCE_FIELDS = list(AESTHETIC_REFERENCE_GROUP.fields)
AESTHETIC_REFERENCE_LABELS = dict(AESTHETIC_REFERENCE_GROUP.labels)
LLM_REVIEW_FIELDS = list(LLM_REVIEW_GROUP.fields)
LLM_REVIEW_LABELS = dict(LLM_REVIEW_GROUP.labels)

MODEL_CAPABILITIES = {
    MODEL_CORE_AESTHETIC: ModelCapability(
        key=MODEL_CORE_AESTHETIC,
        label="核心审美",
        subtitle="构图、光线、色彩等画像",
        model_id=MODEL_ID,
        field_group_key=CORE_AESTHETIC_GROUP.key,
        runtime_key=RUNTIME_CORE_AESTHETIC,
        requires_download=True,
        repo_cache_dir=MODEL_CACHE_REPO_DIR,
    ),
    MODEL_CLIP_IQA: ModelCapability(
        key=MODEL_CLIP_IQA,
        label="模型画质",
        subtitle="CLIP-IQA 感知画质",
        model_id=CLIP_REFERENCE_MODEL_ID,
        field_group_key=MODEL_QUALITY_GROUP.key,
        runtime_key=RUNTIME_CLIP_REFERENCE,
        requires_download=True,
        repo_cache_dir=CLIP_REFERENCE_MODEL_REPO_DIR,
        provider="openai",
    ),
    MODEL_CLIP_AESTHETIC: ModelCapability(
        key=MODEL_CLIP_AESTHETIC,
        label="审美参考",
        subtitle="CLIP 零样本参考",
        model_id=CLIP_REFERENCE_MODEL_ID,
        field_group_key=AESTHETIC_REFERENCE_GROUP.key,
        runtime_key=RUNTIME_CLIP_REFERENCE,
        requires_download=True,
        repo_cache_dir=CLIP_REFERENCE_MODEL_REPO_DIR,
        provider="openai",
    ),
    MODEL_BASIC_TECHNICAL: ModelCapability(
        key=MODEL_BASIC_TECHNICAL,
        label="基础质检",
        subtitle="清晰、曝光、噪点统计",
        model_id="本地规则",
        field_group_key=TECHNICAL_GROUP.key,
        runtime_key=RUNTIME_LOCAL,
        requires_download=False,
    ),
    MODEL_LLM_REVIEW: ModelCapability(
        key=MODEL_LLM_REVIEW,
        label="大模型评审",
        subtitle="审美、技术、评价与修图建议",
        model_id=DEFAULT_LLM_MODEL,
        field_group_key=LLM_REVIEW_GROUP.key,
        runtime_key=RUNTIME_LLM_REVIEW,
        requires_download=False,
        default_enabled=False,
        provider="openai-compatible",
        model_version=DEFAULT_LLM_MODEL,
        prompt_version=LLM_REVIEW_PROMPT_VERSION,
        supports_text_insights=True,
    ),
}
MODEL_KEYS = list(MODEL_CAPABILITIES)
DEFAULT_SELECTED_MODELS = [key for key, capability in MODEL_CAPABILITIES.items() if capability.default_enabled]
MODEL_REPO_CACHE_DIRS = sorted(
    {capability.repo_cache_dir for capability in MODEL_CAPABILITIES.values() if capability.repo_cache_dir}
)

RECOMMENDATION_COLUMN = "recommendation_0_10"
SORT_FIELD_LABELS = {
    RECOMMENDATION_COLUMN: "推荐指数",
    "overall_0_10": "综合表现",
    "clip_aesthetic_0_10": "审美参考",
    "clip_iqa_overall_0_10": "模型画质",
    "quality_0_10": "画质",
    "composition_0_10": "构图",
    "lighting_0_10": "光线",
    "color_0_10": "色彩",
    "depth_of_field_0_10": "景深",
    "content_0_10": "内容",
    "technical_overall_0_10": "技术质检",
    "llm_review_overall_0_10": "大模型总评",
    "llm_aesthetic_overall_0_10": "大模型审美",
    "llm_technical_overall_0_10": "大模型技术",
    "sharpness_0_10": "清晰度",
    "exposure_0_10": "曝光",
    "contrast_0_10": "层次",
    "cleanliness_0_10": "洁净度",
}
SORT_FIELDS = list(SORT_FIELD_LABELS)

BASE_RECORD_COLUMNS = ("file_id", "path", "folder", "filename", "error")
CSV_COLUMNS = [
    *BASE_RECORD_COLUMNS,
    RECOMMENDATION_COLUMN,
    *(column for group in FIELD_GROUPS for column in group.cache_columns),
]


def field_group_for_model(model_key: str) -> ScoreFieldGroup:
    capability = MODEL_CAPABILITIES[model_key]
    return FIELD_GROUP_BY_KEY[capability.field_group_key]


def model_output_fields(model_key: str) -> tuple[str, ...]:
    return field_group_for_model(model_key).fields


def model_output_columns(model_key: str) -> tuple[str, ...]:
    return field_group_for_model(model_key).required_columns


def score_columns_for_fields(fields: Iterable[str], scale: str = "0_10") -> tuple[str, ...]:
    return tuple(score_column(field, scale) for field in fields)


def missing_score_columns(record: Mapping[str, object] | pd.Series | None, columns: Iterable[str]) -> list[str]:
    if record is None:
        return list(columns)
    missing: list[str] = []
    for column in columns:
        value = record.get(column)
        if pd.isna(value):
            missing.append(column)
    return missing


def has_score_columns(record: Mapping[str, object] | pd.Series | None, columns: Iterable[str]) -> bool:
    return not missing_score_columns(record, columns)


def missing_model_output_columns(record: Mapping[str, object] | pd.Series | None, model_key: str) -> list[str]:
    return missing_score_columns(record, model_output_columns(model_key))


def normalize_selected_models(selected_models: Iterable[str] | None = None) -> list[str]:
    if selected_models is None:
        return DEFAULT_SELECTED_MODELS.copy()
    if isinstance(selected_models, str):
        selected_models = [selected_models]
    selected: list[str] = []
    for key in selected_models:
        key_text = str(key)
        if key_text in MODEL_KEYS and key_text not in selected:
            selected.append(key_text)
    return selected or DEFAULT_SELECTED_MODELS.copy()


def model_recompute_plan(
    record: Mapping[str, object] | pd.Series | None,
    selected_models: Iterable[str] | None,
) -> dict[str, bool]:
    active_models = set(normalize_selected_models(selected_models))
    return {
        model_key: model_key in active_models and bool(missing_model_output_columns(record, model_key))
        for model_key in MODEL_KEYS
    }


def normalize_llm_prompt_preset(value: object) -> str:
    return _normalize_llm_prompt_preset(value, LLM_PROMPT_PRESETS, DEFAULT_LLM_PROMPT_PRESET)
