from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from culvia.acceptance import acceptance_mark_plan, normalize_acceptance_basis
from culvia.curation import (
    color_label_text,
    load_photo_marks,
    manual_status_label,
    normalize_color_label,
    normalize_pick_status,
    save_photo_mark,
    save_photo_marks,
)
from culvia.curation_actions import (
    apply_color_label_to_marks,
    apply_mark_mutation_history_payload,
    apply_status_to_marks,
    mark_snapshot_payloads,
    restore_photo_marks_from_payload,
)
from culvia.curation_context import DisplayDataframeBuilder, build_curation_display_context
from culvia.curation_history import append_curation_action, load_curation_actions
from culvia.curation_payloads import mark_history_payload, serialize_curation_action
from culvia.curation_targets import MarkTargetResolution, frame_file_id_set
from culvia.curation_undo import (
    curation_undo_conflicts,
    mark_file_ids,
    resolve_curation_undo_target,
    undone_history_ids,
)


class CurationServiceError(Exception):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        status_code: int = 400,
        params: Mapping[str, object] | None = None,
        conflicts: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.params = dict(params or {})
        self.conflicts = list(conflicts or [])


def mark_target_error(targets: MarkTargetResolution) -> CurationServiceError:
    return CurationServiceError(
        targets.error_code or "markTargetInvalid",
        targets.error_message or "选片目标不可用。",
        status_code=targets.status_code,
        params={"reason": targets.error_message or "", "scope": targets.scope},
    )


def mark_photo_action(cache_path: str, source_df: pd.DataFrame, payload: dict[str, Any]) -> dict[str, object]:
    file_id = str(payload.get("fileId") or "").strip()
    if not file_id:
        raise CurationServiceError("photoIdMissing", "缺少照片标识。", status_code=400)
    if file_id not in frame_file_id_set(source_df):
        raise CurationServiceError("photoNotFound", "没有找到这张照片。", status_code=404)

    mark_kwargs = {
        "rating": payload.get("rating"),
        "status": payload.get("status"),
        "note": payload.get("note"),
        "source": payload.get("source") or "manual",
    }
    if "colorLabel" in payload:
        mark_kwargs["color_label"] = payload.get("colorLabel")
    elif "color_label" in payload:
        mark_kwargs["color_label"] = payload.get("color_label")
    if "acceptedScore" in payload:
        mark_kwargs["accepted_score"] = payload.get("acceptedScore")

    action, _saved_mark = apply_mark_mutation_history_payload(
        cache_path,
        [file_id],
        lambda: save_photo_mark(cache_path, file_id, **mark_kwargs),
        lambda mark: {
            "marked": 1,
            "scope": "current",
            "fileId": file_id,
            "rating": mark.rating,
            "status": mark.status,
            "statusLabel": manual_status_label(mark.status),
            "colorLabel": mark.color_label,
        },
    )
    history = append_curation_action(
        cache_path,
        "mark",
        scope="current",
        summary="更新人工判断 1 张",
        payload=action,
    )
    action["historyId"] = history.id
    return action


def color_targets_action(
    cache_path: str,
    source_df: pd.DataFrame,
    filters: dict[str, Any],
    payload: dict[str, Any],
    dataframe_builder: DisplayDataframeBuilder,
) -> dict[str, object]:
    color_label = normalize_color_label(payload.get("colorLabel") or payload.get("color_label"))
    context = build_curation_display_context(source_df, filters, cache_path, dataframe_builder)
    targets = context.resolve_targets(payload)
    if not targets.ok:
        raise mark_target_error(targets)

    scope, target_ids = targets.scope, targets.target_ids
    action, colored = apply_mark_mutation_history_payload(
        cache_path,
        target_ids,
        lambda: apply_color_label_to_marks(cache_path, target_ids, color_label, source="manual"),
        lambda colored: {
            "colored": colored,
            "scope": scope,
            "colorLabel": color_label,
            "colorLabelText": color_label_text(color_label),
        },
    )
    history = append_curation_action(
        cache_path,
        "color",
        scope=scope,
        summary=f"{color_label_text(color_label) or '清除色标'} {colored} 张",
        payload=action,
    )
    action["historyId"] = history.id
    return action


def status_targets_action(
    cache_path: str,
    source_df: pd.DataFrame,
    filters: dict[str, Any],
    payload: dict[str, Any],
    dataframe_builder: DisplayDataframeBuilder,
) -> dict[str, object]:
    status = normalize_pick_status(payload.get("status"))
    context = build_curation_display_context(source_df, filters, cache_path, dataframe_builder)
    targets = context.resolve_targets(payload)
    if not targets.ok:
        raise mark_target_error(targets)

    scope, target_ids = targets.scope, targets.target_ids
    action, marked = apply_mark_mutation_history_payload(
        cache_path,
        target_ids,
        lambda: apply_status_to_marks(cache_path, target_ids, status, source="manual"),
        lambda marked: {
            "marked": marked,
            "scope": scope,
            "status": status,
            "statusLabel": manual_status_label(status),
        },
    )
    history = append_curation_action(
        cache_path,
        "status",
        scope=scope,
        summary=f"{manual_status_label(status)} {marked} 张",
        payload=action,
    )
    action["historyId"] = history.id
    return action


def accept_targets_action(
    cache_path: str,
    source_df: pd.DataFrame,
    filters: dict[str, Any],
    payload: dict[str, Any],
    dataframe_builder: DisplayDataframeBuilder,
) -> dict[str, object]:
    basis = normalize_acceptance_basis(payload.get("basis"))
    context = build_curation_display_context(source_df, filters, cache_path, dataframe_builder)
    targets = context.resolve_targets(payload)
    if not targets.ok:
        raise mark_target_error(targets)

    scope = targets.scope
    rows = context.rows_for_targets(targets)
    plan = acceptance_mark_plan(rows, basis, scope)
    plan_file_ids = [str(mark["file_id"]) for mark in plan.marks]
    action, saved = apply_mark_mutation_history_payload(
        cache_path,
        plan_file_ids,
        lambda: save_photo_marks(cache_path, plan.marks),
        lambda saved: {
            "accepted": saved,
            "skipped": plan.skipped,
            "basis": basis,
            "scope": scope,
        },
    )
    history = append_curation_action(
        cache_path,
        "accept",
        scope=scope,
        summary=f"{'大模型' if basis == 'llm' else '综合模型'}采纳 {saved} 张",
        payload=action,
    )
    action["historyId"] = history.id
    return action


def restore_marks_action(cache_path: str, source_df: pd.DataFrame, payload: dict[str, Any]) -> dict[str, object]:
    raw_marks = payload.get("marks")
    if not isinstance(raw_marks, list) or not raw_marks:
        raise CurationServiceError("restoreMarksMissing", "缺少要恢复的照片判断。", status_code=400)

    valid_file_ids = frame_file_id_set(source_df)
    target_file_ids = [file_id for file_id in mark_file_ids(raw_marks) if file_id in valid_file_ids]
    action, restored = apply_mark_mutation_history_payload(
        cache_path,
        target_file_ids,
        lambda: restore_photo_marks_from_payload(cache_path, raw_marks, valid_file_ids),
        lambda restored: {"restored": restored},
    )
    history = append_curation_action(
        cache_path,
        "restore",
        summary=f"恢复 {restored} 张",
        payload=action,
    )
    action["historyId"] = history.id
    return action


def curation_history_payload(cache_path: str, *, limit: int = 50) -> dict[str, object]:
    records = load_curation_actions(cache_path, limit=limit)
    undone_ids = undone_history_ids(records)
    return {"actions": [serialize_curation_action(record, undone_ids) for record in records]}


def undo_curation_action(cache_path: str, source_df: pd.DataFrame, payload: dict[str, Any]) -> dict[str, object]:
    history_id = str(payload.get("historyId") or payload.get("history_id") or "").strip()
    resolution = resolve_curation_undo_target(cache_path, history_id=history_id)
    if not resolution.ok or resolution.target is None:
        messages = {
            "already_undone": ("curationUndoAlreadyUndone", "这次操作已经恢复过。", 409),
            "not_found": ("curationUndoNotFound", "没有找到这次操作。", 404),
            "not_restorable": ("curationUndoNotRestorable", "这次操作不能恢复。", 409),
            "no_restorable_action": ("curationUndoNoRestorableAction", "没有可恢复的最近操作。", 404),
        }
        error_code, message, status_code = messages.get(
            resolution.error,
            ("curationUndoNoRestorableAction", "没有可恢复的最近操作。", 404),
        )
        raise CurationServiceError(
            error_code, message, status_code=status_code, params={"reason": resolution.error or ""}
        )

    valid_file_ids = frame_file_id_set(source_df)
    target_file_ids = mark_file_ids(resolution.target.before_marks)
    if not target_file_ids:
        raise CurationServiceError("curationUndoNotRestorable", "这次操作不能恢复。", status_code=409)
    if any(file_id not in valid_file_ids for file_id in target_file_ids):
        raise CurationServiceError(
            "curationUndoOutsideSource", "这次操作涉及的照片不在当前来源中，无法安全恢复。", status_code=409
        )

    current_mark_by_file_id = load_photo_marks(cache_path, target_file_ids) if cache_path else {}
    current_marks = mark_snapshot_payloads(target_file_ids, current_mark_by_file_id)
    conflicts = curation_undo_conflicts(current_marks, resolution.target.after_marks)
    if conflicts:
        raise CurationServiceError(
            "curationUndoConflict",
            "这些照片已被后续操作修改，无法直接撤销。",
            status_code=409,
            params={"conflictCount": len(conflicts)},
            conflicts=conflicts,
        )

    restored = restore_photo_marks_from_payload(cache_path, resolution.target.before_marks, valid_file_ids)
    after_mark_by_file_id = load_photo_marks(cache_path, target_file_ids) if cache_path else {}
    after_marks = mark_snapshot_payloads(target_file_ids, after_mark_by_file_id)
    target_record = resolution.target.record
    action = mark_history_payload(
        {
            "restored": restored,
            "kind": "undo",
            "targetHistoryId": target_record.id,
            "undoneHistoryId": target_record.id,
            "undoneKind": target_record.kind,
            "targetSummary": target_record.summary,
        },
        before_marks=current_marks,
        after_marks=after_marks,
    )
    history = append_curation_action(
        cache_path,
        "undo",
        scope=target_record.scope,
        summary=f"撤销：{target_record.summary or '最近操作'}",
        payload=action,
    )
    action["historyId"] = history.id
    return action
