from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from culvia.curation import curation_db_path

CURATION_ACTIONS_TABLE = "photo_curation_actions"
CURATION_ACTION_PAYLOAD_VERSION = 1


@dataclass(frozen=True)
class CurationActionRecord:
    id: str
    kind: str
    scope: str
    summary: str
    payload: dict[str, Any]
    created_at: float


def ensure_curation_history_schema(cache_path: str | Path) -> Path:
    path = curation_db_path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {CURATION_ACTIONS_TABLE} (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{{}}',
                created_at REAL NOT NULL
            )
            """
        )
    return path


def append_curation_action(
    cache_path: str | Path,
    kind: str,
    *,
    scope: str = "",
    summary: str = "",
    payload: dict[str, Any] | None = None,
) -> CurationActionRecord:
    record = CurationActionRecord(
        id=str(uuid.uuid4()),
        kind=str(kind or "").strip(),
        scope=str(scope or "").strip(),
        summary=str(summary or "").strip(),
        payload=versioned_curation_action_payload(payload),
        created_at=time.time(),
    )
    path = ensure_curation_history_schema(cache_path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            f"""
            INSERT INTO {CURATION_ACTIONS_TABLE}
                (id, kind, scope, summary, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.kind,
                record.scope,
                record.summary,
                json.dumps(record.payload, ensure_ascii=False, sort_keys=True),
                record.created_at,
            ),
        )
    return record


def versioned_curation_action_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(payload or {})
    data.setdefault("schemaVersion", CURATION_ACTION_PAYLOAD_VERSION)
    return data


def load_curation_action(cache_path: str | Path, action_id: str) -> CurationActionRecord | None:
    normalized_id = str(action_id or "").strip()
    if not normalized_id:
        return None
    path = curation_db_path(cache_path)
    if not path.exists():
        return None
    ensure_curation_history_schema(path)
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            f"""
            SELECT * FROM {CURATION_ACTIONS_TABLE}
            WHERE id = ?
            LIMIT 1
            """,
            (normalized_id,),
        ).fetchone()
    return _record_from_row(row) if row else None


def load_curation_actions(cache_path: str | Path, limit: int = 50) -> list[CurationActionRecord]:
    path = curation_db_path(cache_path)
    if not path.exists():
        return []
    ensure_curation_history_schema(path)
    safe_limit = max(1, min(int(limit or 50), 500))
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT * FROM {CURATION_ACTIONS_TABLE}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return [_record_from_row(row) for row in rows]


def _record_from_row(row: sqlite3.Row) -> CurationActionRecord:
    try:
        payload = json.loads(str(row["payload_json"] or "{}"))
    except json.JSONDecodeError:
        payload = {}
    return CurationActionRecord(
        id=str(row["id"] or ""),
        kind=str(row["kind"] or ""),
        scope=str(row["scope"] or ""),
        summary=str(row["summary"] or ""),
        payload=payload if isinstance(payload, dict) else {},
        created_at=float(row["created_at"] or 0.0),
    )
