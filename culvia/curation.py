from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping

import pandas as pd

from culvia.cache_schema import is_sqlite_cache_path

CURATION_TABLE = "photo_curation_marks"
VALID_PICK_STATUSES = {"", "hold", "pick", "reject"}
VALID_MARK_SOURCES = {"manual", "model", "llm", "model_batch", "llm_batch"}
COLOR_LABELS = {
    "red": "红色",
    "yellow": "黄色",
    "green": "绿色",
    "blue": "蓝色",
    "purple": "紫色",
}
VALID_COLOR_LABELS = {"", *COLOR_LABELS.keys()}
_UNSET = object()


@dataclass(frozen=True)
class PhotoMark:
    file_id: str
    rating: int = 0
    status: str = ""
    color_label: str = ""
    note: str = ""
    source: str = "manual"
    accepted_score: float | None = None
    updated_at: float = 0.0


def curation_db_path(cache_path: str | Path) -> Path:
    path = Path(cache_path).expanduser()
    if is_sqlite_cache_path(path):
        return path
    suffix = path.suffix or ".cache"
    return path.with_suffix(f"{suffix}.curation.sqlite")


def normalize_manual_rating(value: object) -> int:
    if value is None or value == "":
        return 0
    try:
        return max(0, min(int(round(float(value))), 5))
    except (TypeError, ValueError):
        return 0


def normalize_pick_status(value: object) -> str:
    status = str(value or "").strip().lower()
    return status if status in VALID_PICK_STATUSES else ""


def normalize_mark_source(value: object) -> str:
    source = str(value or "").strip().lower()
    return source if source in VALID_MARK_SOURCES else "manual"


def normalize_color_label(value: object) -> str:
    color_label = str(value or "").strip().lower()
    return color_label if color_label in VALID_COLOR_LABELS else ""


def color_label_text(value: object) -> str:
    return COLOR_LABELS.get(normalize_color_label(value), "")


def manual_status_label(status: str) -> str:
    return {"pick": "入选", "reject": "淘汰", "hold": "待定"}.get(normalize_pick_status(status), "未判断")


def export_flag_label(status: str) -> str:
    return {"pick": "Pick", "reject": "Reject"}.get(normalize_pick_status(status), "Unflagged")


def export_color_label(color_label: str) -> str:
    return {
        "red": "Red",
        "yellow": "Yellow",
        "green": "Green",
        "blue": "Blue",
        "purple": "Purple",
    }.get(normalize_color_label(color_label), "")


def mark_source_label(source: str) -> str:
    return {
        "manual": "人工",
        "model": "综合模型",
        "llm": "大模型",
        "model_batch": "批量综合",
        "llm_batch": "批量大模型",
    }.get(str(source or ""), "人工")


def ensure_curation_schema(cache_path: str | Path) -> Path:
    path = curation_db_path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {CURATION_TABLE} (
                file_id TEXT PRIMARY KEY,
                manual_rating INTEGER NOT NULL DEFAULT 0,
                pick_status TEXT NOT NULL DEFAULT '',
                color_label TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'manual',
                accepted_score_0_10 REAL,
                updated_at REAL NOT NULL
            )
            """
        )
    return path


def _photo_mark_from_row(row: sqlite3.Row) -> PhotoMark:
    return PhotoMark(
        file_id=str(row["file_id"] or ""),
        rating=normalize_manual_rating(row["manual_rating"]),
        status=normalize_pick_status(row["pick_status"]),
        color_label=normalize_color_label(row["color_label"]),
        note=str(row["note"] or ""),
        source=normalize_mark_source(row["source"]),
        accepted_score=float(row["accepted_score_0_10"]) if row["accepted_score_0_10"] is not None else None,
        updated_at=float(row["updated_at"] or 0.0),
    )


def load_photo_marks(cache_path: str | Path, file_ids: Iterable[str] | None = None) -> dict[str, PhotoMark]:
    path = curation_db_path(cache_path)
    if not path.exists():
        return {}
    ensure_curation_schema(path)
    normalized_ids = [str(file_id) for file_id in file_ids if str(file_id)] if file_ids is not None else []
    if file_ids is not None and not normalized_ids:
        return {}
    marks: dict[str, PhotoMark] = {}
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        if not normalized_ids:
            rows = conn.execute(f"SELECT * FROM {CURATION_TABLE}").fetchall()
            return {_photo_mark_from_row(row).file_id: _photo_mark_from_row(row) for row in rows}
        for start in range(0, len(normalized_ids), 800):
            chunk = normalized_ids[start : start + 800]
            placeholders = ",".join("?" for _ in chunk)
            rows = conn.execute(
                f"SELECT * FROM {CURATION_TABLE} WHERE file_id IN ({placeholders})",
                chunk,
            ).fetchall()
            for row in rows:
                mark = _photo_mark_from_row(row)
                marks[mark.file_id] = mark
    return marks


def save_photo_mark(
    cache_path: str | Path,
    file_id: str,
    *,
    rating: object | None = None,
    status: object | None = None,
    color_label: object | None = None,
    note: object | None = None,
    source: object = "manual",
    accepted_score: object = _UNSET,
) -> PhotoMark:
    existing = load_photo_marks(cache_path, [file_id]).get(file_id)
    mark = PhotoMark(
        file_id=str(file_id),
        rating=existing.rating if rating is None and existing else normalize_manual_rating(rating),
        status=existing.status if status is None and existing else normalize_pick_status(status),
        color_label=existing.color_label if color_label is None and existing else normalize_color_label(color_label),
        note=existing.note if note is None and existing else str(note or "").strip(),
        source=normalize_mark_source(source),
        accepted_score=existing.accepted_score
        if accepted_score is _UNSET and existing
        else _normalize_score(accepted_score),
        updated_at=time.time(),
    )
    path = ensure_curation_schema(cache_path)
    with sqlite3.connect(path) as conn:
        if mark.rating <= 0 and not mark.status and not mark.color_label and not mark.note:
            conn.execute(f"DELETE FROM {CURATION_TABLE} WHERE file_id = ?", (mark.file_id,))
        else:
            conn.execute(
                f"""
                INSERT INTO {CURATION_TABLE}
                    (file_id, manual_rating, pick_status, color_label, note, source, accepted_score_0_10, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_id) DO UPDATE SET
                    manual_rating = excluded.manual_rating,
                    pick_status = excluded.pick_status,
                    color_label = excluded.color_label,
                    note = excluded.note,
                    source = excluded.source,
                    accepted_score_0_10 = excluded.accepted_score_0_10,
                    updated_at = excluded.updated_at
                """,
                (
                    mark.file_id,
                    mark.rating,
                    mark.status,
                    mark.color_label,
                    mark.note,
                    mark.source,
                    mark.accepted_score,
                    mark.updated_at,
                ),
            )
    return mark


def save_photo_marks(cache_path: str | Path, marks: Iterable[Mapping[str, object]]) -> int:
    normalized_marks = [
        PhotoMark(
            file_id=str(mark.get("file_id") or ""),
            rating=normalize_manual_rating(mark.get("rating")),
            status=normalize_pick_status(mark.get("status")),
            color_label=normalize_color_label(mark.get("color_label") or mark.get("colorLabel")),
            note=str(mark.get("note") or "").strip(),
            source=normalize_mark_source(mark.get("source")),
            accepted_score=_normalize_score(mark.get("accepted_score")),
            updated_at=time.time(),
        )
        for mark in marks
        if str(mark.get("file_id") or "")
    ]
    if not normalized_marks:
        return 0
    path = ensure_curation_schema(cache_path)
    with sqlite3.connect(path) as conn:
        conn.executemany(
            f"""
            INSERT INTO {CURATION_TABLE}
                (file_id, manual_rating, pick_status, color_label, note, source, accepted_score_0_10, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_id) DO UPDATE SET
                manual_rating = excluded.manual_rating,
                pick_status = excluded.pick_status,
                color_label = excluded.color_label,
                note = excluded.note,
                source = excluded.source,
                accepted_score_0_10 = excluded.accepted_score_0_10,
                updated_at = excluded.updated_at
            """,
            [
                (
                    mark.file_id,
                    mark.rating,
                    mark.status,
                    mark.color_label,
                    mark.note,
                    mark.source,
                    mark.accepted_score,
                    mark.updated_at,
                )
                for mark in normalized_marks
            ],
        )
    return len(normalized_marks)


def curation_summary(marks: Mapping[str, PhotoMark], file_ids: Iterable[str]) -> dict[str, int]:
    scoped_marks = [marks[file_id] for file_id in file_ids if file_id in marks]
    return {
        "selected": sum(1 for mark in scoped_marks if mark.status == "pick"),
        "rejected": sum(1 for mark in scoped_marks if mark.status == "reject"),
        "rated": sum(1 for mark in scoped_marks if mark.rating > 0),
        "colorLabeled": sum(1 for mark in scoped_marks if mark.color_label),
    }


def curation_export_dataframe(
    df: pd.DataFrame,
    marks: Mapping[str, PhotoMark],
    *,
    normalize_dataframe: Callable[[pd.DataFrame], pd.DataFrame],
) -> pd.DataFrame:
    output = normalize_dataframe(df).copy()
    output["manual_rating"] = output["file_id"].map(
        lambda file_id: marks.get(str(file_id), PhotoMark(str(file_id))).rating
    )
    output["manual_status"] = output["file_id"].map(
        lambda file_id: marks.get(str(file_id), PhotoMark(str(file_id))).status
    )
    output["manual_status_label"] = output["manual_status"].map(manual_status_label)
    output["manual_color_label"] = output["file_id"].map(
        lambda file_id: marks.get(str(file_id), PhotoMark(str(file_id))).color_label
    )
    output["manual_color_label_text"] = output["manual_color_label"].map(color_label_text)
    output["lightroom_rating"] = output["manual_rating"]
    output["lightroom_flag"] = output["manual_status"].map(export_flag_label)
    output["lightroom_color_label"] = output["manual_color_label"].map(export_color_label)
    output["capture_one_rating"] = output["manual_rating"]
    output["capture_one_color_tag"] = output["manual_color_label"].map(export_color_label)
    output["manual_source"] = output["file_id"].map(
        lambda file_id: mark_source_label(marks[str(file_id)].source) if str(file_id) in marks else ""
    )
    output["accepted_score_0_10"] = output["file_id"].map(
        lambda file_id: marks[str(file_id)].accepted_score if str(file_id) in marks else None
    )
    return output


def _normalize_score(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(score, 10.0))
