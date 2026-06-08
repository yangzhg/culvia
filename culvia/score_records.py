from __future__ import annotations

from pathlib import Path
from typing import Iterable, Mapping, Protocol

import pandas as pd


class FieldGroup(Protocol):
    cache_columns: tuple[str, ...]


def make_empty_score_record(
    path: str | Path,
    file_id: str,
    *,
    recommendation_column: str,
    field_groups: Iterable[FieldGroup],
    error: str = "",
) -> dict[str, object]:
    source = Path(path)
    record: dict[str, object] = {
        "file_id": file_id,
        "path": str(source),
        "folder": str(source.parent),
        "filename": source.name,
        "error": error,
        recommendation_column: pd.NA,
    }
    for group in field_groups:
        for column in group.cache_columns:
            record[column] = pd.NA
    return record


def apply_dual_scale_scores(
    record: Mapping[str, object],
    *,
    fields: Iterable[str],
    scores: Mapping[str, float],
    source_scale: str,
    target_scale: str,
    multiplier: float,
) -> dict[str, object]:
    updated = dict(record)
    for field in fields:
        raw_score = float(scores[field])
        updated[f"{field}_{source_scale}"] = round(raw_score, 4)
        updated[f"{field}_{target_scale}"] = round(raw_score * multiplier, 4)
    return updated


def apply_single_scale_scores(
    record: Mapping[str, object],
    *,
    fields: Iterable[str],
    scores: Mapping[str, float],
    scale: str = "0_10",
    only_present: bool = False,
) -> dict[str, object]:
    updated = dict(record)
    for field in fields:
        if only_present and field not in scores:
            continue
        updated[f"{field}_{scale}"] = round(float(scores[field]), 4)
    return updated
