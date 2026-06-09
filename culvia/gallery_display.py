from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import pandas as pd

from culvia.curation import PhotoMark, normalize_color_label, normalize_pick_status
from culvia.recommendation import FILTER_THRESHOLD_COLUMNS, apply_threshold_filters


def manual_status_matches(mark: PhotoMark | None, mode: str) -> bool:
    status = normalize_pick_status(mark.status if mark else "")
    if mode == "all":
        return True
    if mode == "pending":
        return not status or status == "hold"
    return status == mode


def apply_manual_status_filter(
    df: pd.DataFrame,
    marks: Mapping[str, PhotoMark],
    mode: str,
    *,
    valid_modes: set[str],
) -> pd.DataFrame:
    normalized_mode = mode if mode in valid_modes else "all"
    if normalized_mode == "all" or df.empty or "file_id" not in df.columns:
        return df
    mask = df["file_id"].astype(str).map(lambda file_id: manual_status_matches(marks.get(file_id), normalized_mode))
    return df[mask].copy()


def color_label_matches(mark: PhotoMark | None, mode: str) -> bool:
    color_label = normalize_color_label(mark.color_label if mark else "")
    if mode == "all":
        return True
    if mode == "labeled":
        return bool(color_label)
    if mode == "none":
        return not color_label
    return color_label == mode


def apply_color_label_filter(
    df: pd.DataFrame,
    marks: Mapping[str, PhotoMark],
    mode: str,
    *,
    valid_modes: set[str],
) -> pd.DataFrame:
    normalized_mode = mode if mode in valid_modes else "all"
    if normalized_mode == "all" or df.empty or "file_id" not in df.columns:
        return df
    mask = df["file_id"].astype(str).map(lambda file_id: color_label_matches(marks.get(file_id), normalized_mode))
    return df[mask].copy()


def dataframe_for_display(
    df: pd.DataFrame,
    filters: Mapping[str, Any],
    mark_by_file_id: Mapping[str, PhotoMark] | None,
    *,
    enrich_scores: Callable[[pd.DataFrame, Mapping[str, Any]], pd.DataFrame],
    apply_model_agreement: Callable[[pd.DataFrame, str], pd.DataFrame],
    sort_fields: set[str],
    manual_status_filter_values: set[str],
    color_label_filter_values: set[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    working = enrich_scores(df, filters)

    errors = working[working["error"].fillna("").ne("")].copy()
    successful = working[working["error"].fillna("").eq("")].copy()
    scored = successful.dropna(subset=["recommendation_0_10"]).copy()
    unscored = successful[successful["recommendation_0_10"].isna()].copy()

    model_agreement = str(filters.get("modelAgreement") or "all")
    sort_field = str(filters.get("sortField") or "recommendation_0_10")
    if sort_field not in sort_fields:
        sort_field = "recommendation_0_10"
    limit = int(filters.get("limit", 80) or 80)
    marks = mark_by_file_id or {}

    filtered = apply_threshold_filters(scored, filters, FILTER_THRESHOLD_COLUMNS)
    filtered = apply_model_agreement(filtered, model_agreement)
    filtered = apply_manual_status_filter(
        filtered,
        marks,
        str(filters.get("manualStatus") or "all"),
        valid_modes=manual_status_filter_values,
    )
    filtered = apply_color_label_filter(
        filtered,
        marks,
        str(filters.get("colorLabel") or "all"),
        valid_modes=color_label_filter_values,
    )
    if (
        not unscored.empty
        and model_agreement == "all"
        and all(float(filters.get(filter_key, 0.0) or 0.0) <= 0 for filter_key in FILTER_THRESHOLD_COLUMNS)
    ):
        unscored = apply_manual_status_filter(
            unscored,
            marks,
            str(filters.get("manualStatus") or "all"),
            valid_modes=manual_status_filter_values,
        )
        unscored = apply_color_label_filter(
            unscored,
            marks,
            str(filters.get("colorLabel") or "all"),
            valid_modes=color_label_filter_values,
        )
        filtered = pd.concat([filtered, unscored], ignore_index=True)
    filtered = filtered.sort_values(sort_field, ascending=False, na_position="last")
    filtered = filtered.head(max(limit, 1))
    return working, filtered, errors


def selected_preview_for_display(
    working: pd.DataFrame,
    marks: Mapping[str, PhotoMark],
    *,
    limit: int = 80,
) -> pd.DataFrame:
    if working.empty or "file_id" not in working.columns:
        return working.head(0).copy()
    selected_file_ids = set()
    for file_id in working["file_id"].fillna("").astype(str):
        mark = marks.get(file_id)
        if mark and mark.status == "pick":
            selected_file_ids.add(file_id)
    if not selected_file_ids:
        return working.head(0).copy()
    selected_preview = working[working["file_id"].astype(str).isin(selected_file_ids)].copy()
    if selected_preview.empty:
        return selected_preview
    if "recommendation_0_10" in selected_preview.columns:
        selected_preview = selected_preview.sort_values("recommendation_0_10", ascending=False, na_position="last")
    return selected_preview.head(max(limit, 1))
