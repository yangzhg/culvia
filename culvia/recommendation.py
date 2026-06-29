from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

import pandas as pd

RECOMMENDATION_COLUMN = "recommendation_0_10"
WEIGHT_PRESETS: dict[str, dict[str, object]] = {
    "balanced": {
        "label": "均衡",
        "weights": {"aesthetic": 0.65, "technical": 0.25, "compositionLight": 0.10},
    },
    "aesthetic": {
        "label": "审美优先",
        "weights": {"aesthetic": 0.82, "technical": 0.10, "compositionLight": 0.08},
    },
    "technical": {
        "label": "技术优先",
        "weights": {"aesthetic": 0.35, "technical": 0.55, "compositionLight": 0.10},
    },
    "composition_light": {
        "label": "构图光线",
        "weights": {"aesthetic": 0.40, "technical": 0.15, "compositionLight": 0.45},
    },
    "custom": {
        "label": "自定义",
        "weights": {"aesthetic": 0.60, "technical": 0.25, "compositionLight": 0.15},
    },
}
MODEL_AGREEMENT_OPTIONS = [
    {"value": "all", "label": "全部"},
    {"value": "aligned", "label": "评审接近"},
    {"value": "disagreement", "label": "明显分歧"},
    {"value": "llm_disagreement", "label": "大模型不同意"},
    {"value": "aesthetic_gap", "label": "有氛围但画质弱"},
    {"value": "quality_gap", "label": "画质稳但吸引弱"},
]
FILTER_DEFAULTS = {
    "sortField": RECOMMENDATION_COLUMN,
    "minScore": 0.0,
    "minModelQuality": 0.0,
    "minAestheticReference": 0.0,
    "minTechnical": 0.0,
    "minLlmReview": 0.0,
    "modelAgreement": "all",
    "manualStatus": "all",
    "colorLabel": "all",
    "limit": 80,
    "weightPreset": "balanced",
    "customWeights": {"aesthetic": 0.60, "technical": 0.25, "compositionLight": 0.15},
}
FILTER_THRESHOLD_COLUMNS = {
    "minScore": RECOMMENDATION_COLUMN,
    "minModelQuality": "clip_iqa_overall_0_10",
    "minAestheticReference": "clip_aesthetic_0_10",
    "minTechnical": "technical_overall_0_10",
    "minLlmReview": "llm_review_overall_0_10",
}


def numeric_column(row: pd.Series | Mapping[str, object], column: str) -> float | None:
    value = pd.to_numeric(row.get(column), errors="coerce")
    if pd.isna(value):
        return None
    return float(value)


def numeric_score(row: pd.Series | Mapping[str, object], field: str) -> float | None:
    return numeric_column(row, f"{field}_0_10")


def normalize_weight(value: object, fallback: float) -> float:
    try:
        return max(0.0, float(value))
    except Exception:
        return fallback


def active_weights(filters: Mapping[str, Any]) -> dict[str, float]:
    preset = str(filters.get("weightPreset") or "balanced")
    if preset == "custom":
        raw = filters.get("customWeights") or {}
        raw_weights = raw if isinstance(raw, Mapping) else {}
        weights = {
            "aesthetic": normalize_weight(raw_weights.get("aesthetic"), 0.60),
            "technical": normalize_weight(raw_weights.get("technical"), 0.25),
            "compositionLight": normalize_weight(raw_weights.get("compositionLight"), 0.15),
        }
    else:
        preset_config = WEIGHT_PRESETS.get(preset, WEIGHT_PRESETS["balanced"])
        weights = dict(preset_config["weights"])  # type: ignore[arg-type]
    total = sum(float(value) for value in weights.values()) or 1.0
    return {key: float(value) / total for key, value in weights.items()}


def weighted_average(parts: Iterable[tuple[float | None, float]]) -> float | None:
    usable = [(value, weight) for value, weight in parts if value is not None and weight > 0]
    if not usable:
        return None
    total = sum(weight for _value, weight in usable)
    return sum(float(value) * weight for value, weight in usable) / total


def calculate_recommendation(row: pd.Series | Mapping[str, object], filters: Mapping[str, Any]) -> float | None:
    weights = active_weights(filters)
    aesthetic = weighted_average(
        [
            (numeric_score(row, "overall"), 0.58),
            (numeric_score(row, "clip_aesthetic"), 0.22),
            (numeric_score(row, "llm_aesthetic_overall"), 0.20),
        ]
    )
    technical = weighted_average(
        [
            (numeric_score(row, "technical_overall"), 0.45),
            (numeric_score(row, "clip_iqa_overall"), 0.30),
            (numeric_score(row, "llm_technical_overall"), 0.25),
        ]
    )
    composition_light = weighted_average(
        [
            (numeric_score(row, "composition"), 0.5),
            (numeric_score(row, "lighting"), 0.5),
        ]
    )
    return weighted_average(
        [
            (aesthetic, weights["aesthetic"]),
            (technical, weights["technical"]),
            (composition_light, weights["compositionLight"]),
        ]
    )


def enrich_scores_for_display(
    df: pd.DataFrame,
    filters: Mapping[str, Any],
    *,
    normalize_dataframe: Callable[[pd.DataFrame], pd.DataFrame],
    score_fields: Iterable[str],
    recommendation_column: str = RECOMMENDATION_COLUMN,
) -> pd.DataFrame:
    working = normalize_dataframe(df)
    for field in score_fields:
        column = f"{field}_0_10"
        if column not in working.columns:
            working[column] = pd.NA
        working[column] = pd.to_numeric(working[column], errors="coerce")
    working[recommendation_column] = working.apply(lambda row: calculate_recommendation(row, filters), axis=1)
    return working


def apply_threshold_filters(
    df: pd.DataFrame,
    filters: Mapping[str, Any],
    threshold_columns: Mapping[str, str] = FILTER_THRESHOLD_COLUMNS,
) -> pd.DataFrame:
    filtered = df
    for filter_key, column in threshold_columns.items():
        minimum = float(filters.get(filter_key, 0.0) or 0.0)
        if minimum > 0 or filter_key == "minScore":
            filtered = filtered[pd.to_numeric(filtered[column], errors="coerce") >= minimum]
    return filtered


def row_score_values(row: pd.Series | Mapping[str, object], columns: Iterable[str]) -> list[float]:
    values: list[float] = []
    for column in columns:
        value = numeric_column(row, column)
        if value is not None:
            values.append(value)
    return values


def model_agreement_matches(
    row: pd.Series | Mapping[str, object],
    mode: str,
    *,
    llm_aesthetic_weight: float,
    llm_technical_weight: float,
) -> bool:
    if mode == "all":
        return True

    local_aesthetic = weighted_average(
        [
            (numeric_column(row, "overall_0_10"), 0.70),
            (numeric_column(row, "clip_aesthetic_0_10"), 0.30),
        ]
    )
    local_quality = weighted_average(
        [
            (numeric_column(row, "clip_iqa_overall_0_10"), 0.45),
            (numeric_column(row, "technical_overall_0_10"), 0.55),
        ]
    )
    aesthetic = weighted_average(
        [
            (numeric_column(row, "overall_0_10"), 0.56),
            (numeric_column(row, "clip_aesthetic_0_10"), 0.24),
            (numeric_column(row, "llm_aesthetic_overall_0_10"), 0.20),
        ]
    )
    quality = weighted_average(
        [
            (numeric_column(row, "clip_iqa_overall_0_10"), 0.35),
            (numeric_column(row, "technical_overall_0_10"), 0.40),
            (numeric_column(row, "llm_technical_overall_0_10"), 0.25),
        ]
    )
    values = row_score_values(
        row,
        [
            "overall_0_10",
            "clip_aesthetic_0_10",
            "clip_iqa_overall_0_10",
            "technical_overall_0_10",
            "llm_aesthetic_overall_0_10",
            "llm_technical_overall_0_10",
        ],
    )

    if mode == "aligned":
        return len(values) >= 2 and max(values) - min(values) <= 1.0
    if mode == "disagreement":
        return len(values) >= 2 and max(values) - min(values) >= 1.8
    if mode == "llm_disagreement":
        llm_aesthetic = numeric_column(row, "llm_aesthetic_overall_0_10")
        llm_technical = numeric_column(row, "llm_technical_overall_0_10")
        llm_overall = weighted_average(
            [
                (llm_aesthetic, llm_aesthetic_weight),
                (llm_technical, llm_technical_weight),
            ]
        )
        local_overall = weighted_average([(local_aesthetic, 0.58), (local_quality, 0.42)])
        return llm_overall is not None and local_overall is not None and abs(llm_overall - local_overall) >= 1.4
    if mode == "aesthetic_gap":
        return aesthetic is not None and quality is not None and aesthetic >= 7.0 and quality < 6.0
    if mode == "quality_gap":
        return aesthetic is not None and quality is not None and quality >= 7.0 and aesthetic < 6.0
    return True


def apply_model_agreement_filter(
    df: pd.DataFrame,
    mode: str,
    *,
    llm_aesthetic_weight: float,
    llm_technical_weight: float,
    options: Iterable[Mapping[str, str]] = MODEL_AGREEMENT_OPTIONS,
) -> pd.DataFrame:
    allowed = {option["value"] for option in options}
    if mode not in allowed or mode == "all" or df.empty:
        return df
    mask = df.apply(
        lambda row: model_agreement_matches(
            row,
            mode,
            llm_aesthetic_weight=llm_aesthetic_weight,
            llm_technical_weight=llm_technical_weight,
        ),
        axis=1,
    )
    return df[mask].copy()
