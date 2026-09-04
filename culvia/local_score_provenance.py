from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd

from culvia.schema import (
    MODEL_CAPABILITIES,
    MODEL_RESULT_STATE_COLUMNS,
    MODEL_RESULT_VERSION_COLUMNS,
    RECOMMENDATION_COLUMN,
    VERSIONED_LOCAL_MODEL_KEYS,
    field_group_for_model,
    model_result_state,
)


RESULT_STATES = ("current", "legacy", "stale", "incomplete", "missing")


@dataclass(frozen=True)
class LocalScoreResolution:
    dataframe: pd.DataFrame
    summary: dict[str, dict[str, int]]


def resolve_local_score_dataframe(source_df: pd.DataFrame) -> LocalScoreResolution:
    resolved = source_df.copy()
    summary: dict[str, dict[str, int]] = {
        model_key: {state: 0 for state in RESULT_STATES} for model_key in VERSIONED_LOCAL_MODEL_KEYS
    }
    if resolved.empty:
        for model_key, state_column in MODEL_RESULT_STATE_COLUMNS.items():
            resolved[state_column] = pd.Series(dtype="object")
        return LocalScoreResolution(resolved, summary)

    for model_key in VERSIONED_LOCAL_MODEL_KEYS:
        group = field_group_for_model(model_key)
        required_columns = list(group.required_columns)
        for column in (*group.cache_columns, MODEL_RESULT_VERSION_COLUMNS[model_key]):
            if column not in resolved.columns:
                resolved[column] = "" if column == MODEL_RESULT_VERSION_COLUMNS[model_key] else pd.NA

        required_present = resolved[required_columns].notna()
        all_present = required_present.all(axis=1)
        any_present = resolved[list(group.cache_columns)].notna().any(axis=1)
        stored_versions = resolved[MODEL_RESULT_VERSION_COLUMNS[model_key]].fillna("").astype(str).str.strip()
        expected_version = MODEL_CAPABILITIES[model_key].result_version

        states = pd.Series("incomplete", index=resolved.index, dtype="object")
        states.loc[~any_present & stored_versions.eq("")] = "missing"
        states.loc[all_present & stored_versions.eq("")] = "legacy"
        states.loc[all_present & stored_versions.ne("") & stored_versions.ne(expected_version)] = "stale"
        states.loc[all_present & stored_versions.eq(expected_version)] = "current"

        state_column = MODEL_RESULT_STATE_COLUMNS[model_key]
        resolved[state_column] = states
        counts = states.value_counts()
        summary[model_key] = {state: int(counts.get(state, 0)) for state in RESULT_STATES}

        not_current = states.ne("current")
        for column in group.cache_columns:
            resolved.loc[not_current, column] = pd.NA

    if RECOMMENDATION_COLUMN in resolved.columns:
        current_columns = [MODEL_RESULT_STATE_COLUMNS[key] for key in VERSIONED_LOCAL_MODEL_KEYS]
        invalidated = resolved[current_columns].isin(("legacy", "stale", "incomplete")).any(axis=1)
        resolved.loc[invalidated, RECOMMENDATION_COLUMN] = pd.NA
    return LocalScoreResolution(resolved, summary)


def current_local_score_context(record: Mapping[str, object]) -> dict[str, object]:
    resolved = dict(record)
    invalidate_recommendation = False
    for model_key in VERSIONED_LOCAL_MODEL_KEYS:
        state = model_result_state(record, model_key)
        resolved[MODEL_RESULT_STATE_COLUMNS[model_key]] = state
        if state != "current":
            for column in field_group_for_model(model_key).cache_columns:
                resolved[column] = pd.NA
        if state in {"legacy", "stale", "incomplete"}:
            invalidate_recommendation = True
    if invalidate_recommendation and RECOMMENDATION_COLUMN in resolved:
        resolved[RECOMMENDATION_COLUMN] = pd.NA
    return resolved


def preserve_local_result_states(source_df: pd.DataFrame, normalized_df: pd.DataFrame) -> pd.DataFrame:
    output = normalized_df.copy()
    for state_column in MODEL_RESULT_STATE_COLUMNS.values():
        if state_column not in output.columns:
            output[state_column] = pd.Series("missing", index=output.index, dtype="object")
    if source_df.empty or "file_id" not in source_df.columns or "file_id" not in output.columns:
        return output
    state_columns = [column for column in MODEL_RESULT_STATE_COLUMNS.values() if column in source_df.columns]
    if not state_columns:
        return output
    states = source_df[["file_id", *state_columns]].copy()
    states["file_id"] = states["file_id"].fillna("").astype(str)
    states = states.drop_duplicates(subset=["file_id"], keep="last").set_index("file_id")
    output_ids = output["file_id"].fillna("").astype(str)
    for column in state_columns:
        output[column] = output_ids.map(states[column]).fillna("missing")
    return output


def local_score_provenance_payload(row: pd.Series) -> dict[str, dict[str, str]]:
    payload: dict[str, dict[str, str]] = {}
    for model_key in VERSIONED_LOCAL_MODEL_KEYS:
        stored_value = row.get(MODEL_RESULT_VERSION_COLUMNS[model_key])
        stored_version = "" if stored_value is None or pd.isna(stored_value) else str(stored_value)
        state_value = row.get(MODEL_RESULT_STATE_COLUMNS[model_key])
        state_text = "" if state_value is None or pd.isna(state_value) else str(state_value)
        state = state_text if state_text in RESULT_STATES else "missing"
        payload[model_key] = {
            "state": state,
            "storedResultVersion": stored_version,
        }
    return payload
