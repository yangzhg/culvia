from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from culvia.curation_history import CurationActionRecord, load_curation_action, load_curation_actions

RESTORABLE_ACTION_KINDS = {"accept", "color", "mark", "status"}
UNDO_ACTION_KIND = "undo"


@dataclass(frozen=True)
class CurationUndoTarget:
    record: CurationActionRecord
    before_marks: list[Mapping[str, Any]]
    after_marks: list[Mapping[str, Any]]


@dataclass(frozen=True)
class CurationUndoResolution:
    target: CurationUndoTarget | None = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.target is not None and not self.error


def resolve_curation_undo_target(
    cache_path: str | Path,
    *,
    history_id: str = "",
    search_limit: int = 500,
) -> CurationUndoResolution:
    recent_records = load_curation_actions(cache_path, limit=search_limit)
    undone_ids = undone_history_ids(recent_records)
    normalized_history_id = str(history_id or "").strip()
    if normalized_history_id:
        if normalized_history_id in undone_ids:
            return CurationUndoResolution(error="already_undone")
        record = load_curation_action(cache_path, normalized_history_id)
        if record is None:
            return CurationUndoResolution(error="not_found")
        return _resolution_from_record(record)

    for record in recent_records:
        if record.id in undone_ids:
            continue
        resolution = _resolution_from_record(record)
        if resolution.ok:
            return resolution
    return CurationUndoResolution(error="no_restorable_action")


def undone_history_ids(records: Iterable[CurationActionRecord]) -> set[str]:
    ids: set[str] = set()
    for record in records:
        if record.kind != UNDO_ACTION_KIND:
            continue
        payload = record.payload
        history_id = str(
            payload.get("targetHistoryId") or payload.get("undoneHistoryId") or payload.get("historyId") or ""
        ).strip()
        if history_id:
            ids.add(history_id)
    return ids


def mark_file_ids(marks: Iterable[Mapping[str, Any]]) -> list[str]:
    ids: list[str] = []
    for mark in marks:
        file_id = str(mark.get("fileId") or mark.get("file_id") or "").strip()
        if file_id:
            ids.append(file_id)
    return ids


def curation_undo_conflicts(
    current_marks: Iterable[Mapping[str, Any]],
    expected_after_marks: Iterable[Mapping[str, Any]],
) -> list[str]:
    expected = _indexed_comparable_marks(expected_after_marks)
    if not expected:
        return []
    current = _indexed_comparable_marks(current_marks)
    return [file_id for file_id, expected_mark in expected.items() if current.get(file_id) != expected_mark]


def _resolution_from_record(record: CurationActionRecord) -> CurationUndoResolution:
    if record.kind not in RESTORABLE_ACTION_KINDS:
        return CurationUndoResolution(error="not_restorable")
    raw_before_marks = record.payload.get("beforeMarks")
    if not isinstance(raw_before_marks, list):
        return CurationUndoResolution(error="not_restorable")
    before_marks = [mark for mark in raw_before_marks if isinstance(mark, Mapping)]
    if not before_marks:
        return CurationUndoResolution(error="not_restorable")
    raw_after_marks = record.payload.get("afterMarks")
    after_marks = (
        [mark for mark in raw_after_marks if isinstance(mark, Mapping)] if isinstance(raw_after_marks, list) else []
    )
    return CurationUndoResolution(
        target=CurationUndoTarget(record=record, before_marks=before_marks, after_marks=after_marks)
    )


def _indexed_comparable_marks(marks: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, object]]:
    indexed: dict[str, dict[str, object]] = {}
    for mark in marks:
        comparable = _comparable_mark(mark)
        file_id = str(comparable["fileId"])
        if file_id:
            indexed[file_id] = comparable
    return indexed


def _comparable_mark(mark: Mapping[str, Any]) -> dict[str, object]:
    file_id = str(mark.get("fileId") or mark.get("file_id") or "").strip()
    color_label = mark.get("colorLabel") if "colorLabel" in mark else mark.get("color_label")
    return {
        "fileId": file_id,
        "rating": _safe_int(mark.get("rating")),
        "status": str(mark.get("status") or ""),
        "colorLabel": str(color_label or ""),
        "note": str(mark.get("note") or ""),
        "source": str(mark.get("source") or "manual"),
        "acceptedScore": _safe_score(
            mark.get("acceptedScore") if "acceptedScore" in mark else mark.get("accepted_score")
        ),
    }


def _safe_int(value: object) -> int:
    try:
        return int(round(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def _safe_score(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None
