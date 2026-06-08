from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Mapping
from pathlib import Path
from typing import TypeVar

from culvia.curation import PhotoMark, load_photo_marks, save_photo_mark
from culvia.curation_payloads import mark_history_payload

MutationResult = TypeVar("MutationResult")


def mark_snapshot_payload(file_id: str, mark: PhotoMark | None) -> dict[str, object]:
    if mark is None:
        return {
            "fileId": file_id,
            "rating": 0,
            "status": "",
            "colorLabel": "",
            "note": "",
            "source": "manual",
            "acceptedScore": None,
        }
    return {
        "fileId": mark.file_id,
        "rating": mark.rating,
        "status": mark.status,
        "colorLabel": mark.color_label,
        "note": mark.note,
        "source": mark.source,
        "acceptedScore": mark.accepted_score,
    }


def mark_snapshot_payloads(file_ids: Iterable[str], marks: Mapping[str, PhotoMark]) -> list[dict[str, object]]:
    return [mark_snapshot_payload(str(file_id), marks.get(str(file_id))) for file_id in file_ids]


def apply_mark_mutation_history_payload(
    cache_path: str | Path,
    file_ids: Iterable[str],
    mutate: Callable[[], MutationResult],
    payload_factory: Callable[[MutationResult], dict[str, object]],
) -> tuple[dict[str, object], MutationResult]:
    target_ids = _normalized_file_ids(file_ids)
    before_by_file_id = load_photo_marks(cache_path, target_ids) if cache_path else {}
    before_marks = mark_snapshot_payloads(target_ids, before_by_file_id)
    result = mutate()
    after_by_file_id = load_photo_marks(cache_path, target_ids) if cache_path else {}
    after_marks = mark_snapshot_payloads(target_ids, after_by_file_id)
    return mark_history_payload(payload_factory(result), before_marks=before_marks, after_marks=after_marks), result


def apply_color_label_to_marks(
    cache_path: str | Path,
    file_ids: Iterable[str],
    color_label: object,
    *,
    source: object = "manual",
) -> int:
    saved = 0
    for file_id in _normalized_file_ids(file_ids):
        save_photo_mark(cache_path, file_id, color_label=color_label, source=source)
        saved += 1
    return saved


def apply_status_to_marks(
    cache_path: str | Path,
    file_ids: Iterable[str],
    status: object,
    *,
    source: object = "manual",
) -> int:
    saved = 0
    for file_id in _normalized_file_ids(file_ids):
        save_photo_mark(cache_path, file_id, status=status, source=source, accepted_score=None)
        saved += 1
    return saved


def restore_photo_marks_from_payload(
    cache_path: str | Path,
    raw_marks: Iterable[object],
    valid_file_ids: Collection[str],
) -> int:
    valid_ids = {str(file_id) for file_id in valid_file_ids}
    restored = 0
    for item in raw_marks:
        if not isinstance(item, Mapping):
            continue
        file_id = str(item.get("fileId") or item.get("file_id") or "").strip()
        if not file_id or file_id not in valid_ids:
            continue
        color_label = item["colorLabel"] if "colorLabel" in item else item.get("color_label")
        accepted_score = item["acceptedScore"] if "acceptedScore" in item else item.get("accepted_score")
        save_photo_mark(
            cache_path,
            file_id,
            rating=item.get("rating"),
            status=item.get("status"),
            color_label=color_label,
            note=item.get("note"),
            source=item.get("source") or "manual",
            accepted_score=accepted_score,
        )
        restored += 1
    return restored


def _normalized_file_ids(file_ids: Iterable[str]) -> list[str]:
    return [file_id for file_id in (str(value).strip() for value in file_ids) if file_id]
