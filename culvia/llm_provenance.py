from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pandas as pd

from culvia.insight_store import AnalysisInsightMatch


@dataclass(frozen=True)
class LlmScoreResolution:
    dataframe: pd.DataFrame
    current_file_ids: frozenset[str]


def resolve_llm_score_dataframe(
    source_df: pd.DataFrame,
    matches: Mapping[str, AnalysisInsightMatch],
    *,
    generation_column: str,
    score_columns: Sequence[str],
    derived_columns: Sequence[str] = (),
) -> LlmScoreResolution:
    resolved = source_df.copy()
    if resolved.empty or "file_id" not in resolved.columns:
        return LlmScoreResolution(resolved, frozenset())
    if generation_column not in resolved.columns:
        resolved[generation_column] = pd.NA

    current_file_ids: set[str] = set()
    for index, row in resolved.iterrows():
        file_id = str(row.get("file_id") or "")
        match = matches.get(file_id)
        if match is None:
            continue
        generation = pd.to_numeric(row.get(generation_column), errors="coerce")
        if not pd.isna(generation) and float(generation) == match.generation:
            current_file_ids.add(file_id)

    current_mask = resolved["file_id"].astype(str).isin(current_file_ids)
    stale_llm_mask = ~current_mask & resolved[
        [column for column in (*score_columns, generation_column) if column in resolved.columns]
    ].notna().any(axis=1)
    for column in (*score_columns, generation_column):
        if column in resolved.columns:
            resolved.loc[~current_mask, column] = pd.NA
    for column in derived_columns:
        if column in resolved.columns:
            resolved.loc[stale_llm_mask, column] = pd.NA
    return LlmScoreResolution(
        resolved,
        frozenset(current_file_ids),
    )
