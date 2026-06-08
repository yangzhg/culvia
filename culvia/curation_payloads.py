from __future__ import annotations

from typing import Any

from culvia.curation_history import CurationActionRecord
from culvia.curation_undo import RESTORABLE_ACTION_KINDS, UNDO_ACTION_KIND


def curation_action_undo_state(record: CurationActionRecord, undone_ids: set[str] | None = None) -> str:
    if record.kind == UNDO_ACTION_KIND:
        return "undo"
    if record.id in (undone_ids or set()):
        return "undone"
    before_marks = record.payload.get("beforeMarks")
    if record.kind in RESTORABLE_ACTION_KINDS and isinstance(before_marks, list) and before_marks:
        return "available"
    return "unavailable"


def serialize_curation_action(record: CurationActionRecord, undone_ids: set[str] | None = None) -> dict[str, Any]:
    return {
        "id": record.id,
        "kind": record.kind,
        "scope": record.scope,
        "summary": record.summary,
        "payload": record.payload,
        "undoState": curation_action_undo_state(record, undone_ids),
        "createdAt": record.created_at,
    }


def mark_history_payload(
    payload: dict[str, Any],
    *,
    before_marks: list[dict[str, object]],
    after_marks: list[dict[str, object]],
) -> dict[str, Any]:
    data = dict(payload)
    data["beforeMarks"] = before_marks
    data["afterMarks"] = after_marks
    return data
