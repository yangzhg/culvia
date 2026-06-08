from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from culvia.curation import PhotoMark, load_photo_marks
from culvia.curation_targets import MarkTargetResolution, frame_file_id_set, frame_file_ids, resolve_mark_targets

DisplayDataframeBuilder = Callable[
    [pd.DataFrame, dict[str, Any], dict[str, PhotoMark]],
    tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame],
]


@dataclass(frozen=True)
class CurationDisplayContext:
    source_df: pd.DataFrame
    filters: dict[str, Any]
    cache_path: str
    mark_by_file_id: dict[str, PhotoMark]
    working: pd.DataFrame
    filtered: pd.DataFrame
    errors: pd.DataFrame

    @property
    def source_file_ids(self) -> list[str]:
        return frame_file_ids(self.source_df)

    @property
    def valid_file_ids(self) -> set[str]:
        return frame_file_id_set(self.source_df)

    def resolve_targets(self, payload: dict[str, Any]) -> MarkTargetResolution:
        return resolve_mark_targets(payload, self.working, self.filtered)

    def rows_for_targets(self, targets: MarkTargetResolution) -> pd.DataFrame:
        if targets.scope == "filtered":
            return self.filtered.copy()
        if not targets.target_ids or "file_id" not in self.working:
            return self.working.iloc[0:0].copy()
        file_ids = self.working["file_id"].astype(str)
        if targets.scope == "selected":
            return self.working[file_ids.isin(targets.target_ids)].copy()
        return self.working[file_ids.eq(targets.target_ids[0])].copy()


def build_curation_display_context(
    source_df: pd.DataFrame,
    filters: dict[str, Any],
    cache_path: str,
    dataframe_builder: DisplayDataframeBuilder,
) -> CurationDisplayContext:
    normalized_cache_path = str(cache_path or "")
    source_file_ids = frame_file_ids(source_df)
    mark_by_file_id = load_photo_marks(normalized_cache_path, source_file_ids) if normalized_cache_path else {}
    working, filtered, errors = dataframe_builder(source_df, filters, mark_by_file_id)
    return CurationDisplayContext(
        source_df=source_df,
        filters=dict(filters),
        cache_path=normalized_cache_path,
        mark_by_file_id=mark_by_file_id,
        working=working,
        filtered=filtered,
        errors=errors,
    )
