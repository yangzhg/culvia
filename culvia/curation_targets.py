from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class MarkTargetResolution:
    scope: str
    target_ids: list[str]
    error_message: str = ""
    status_code: int = 200
    error_code: str = ""

    @property
    def ok(self) -> bool:
        return not self.error_message


def frame_file_ids(frame: pd.DataFrame) -> list[str]:
    if "file_id" not in frame:
        return []
    return [str(value) for value in frame.get("file_id", pd.Series(dtype=str)).dropna().tolist()]


def frame_file_id_set(frame: pd.DataFrame) -> set[str]:
    return set(frame_file_ids(frame))


def _selected_file_ids(payload: dict[str, Any]) -> list[str]:
    raw_ids = payload.get("fileIds", [])
    if not isinstance(raw_ids, list | tuple):
        return []
    return [str(value).strip() for value in raw_ids if str(value).strip()]


def resolve_mark_targets(
    payload: dict[str, Any],
    working: pd.DataFrame,
    filtered: pd.DataFrame,
) -> MarkTargetResolution:
    raw_scope = payload.get("scope")
    scope = raw_scope if raw_scope in {"filtered", "selected"} else "current"
    if scope == "filtered":
        return MarkTargetResolution(scope=scope, target_ids=frame_file_ids(filtered))

    working_ids = frame_file_id_set(working)
    if scope == "selected":
        target_ids = [file_id for file_id in _selected_file_ids(payload) if file_id in working_ids]
        if not target_ids:
            return MarkTargetResolution(
                scope=scope,
                target_ids=[],
                error_message="缺少已选照片。",
                status_code=400,
                error_code="selectedPhotosMissing",
            )
        return MarkTargetResolution(scope=scope, target_ids=target_ids)

    file_id = str(payload.get("fileId") or "").strip()
    if not file_id:
        return MarkTargetResolution(
            scope=scope,
            target_ids=[],
            error_message="缺少照片标识。",
            status_code=400,
            error_code="photoIdMissing",
        )
    if file_id not in working_ids:
        return MarkTargetResolution(
            scope=scope,
            target_ids=[],
            error_message="没有找到这张照片。",
            status_code=404,
            error_code="photoNotFound",
        )
    return MarkTargetResolution(scope=scope, target_ids=[file_id])
