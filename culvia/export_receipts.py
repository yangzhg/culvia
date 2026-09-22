from __future__ import annotations

import csv
import errno
import io
import json
import os
import sqlite3
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pandas as pd

from culvia.export_service import (
    EXPORT_PAYLOAD_VERSION,
    SKIPPED_REASON_LABELS,
    ExportFileOutcome,
    ExportProgressError,
    ExportServiceError,
    export_selected_files_action,
)
from culvia.job_text import text_ref
from culvia.path_semantics import path_identity_key, stable_path


_PREVIEW_LIMIT = 20
_OPERATIONS = "export_receipts"
_FILES = "export_receipt_files"


class ExportReceiptError(ExportServiceError):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        status_code: int = 500,
        params: Mapping[str, object] | None = None,
        operation_id: str = "",
    ) -> None:
        super().__init__(error_code, message, status_code=status_code, params=params)
        self.operation_id = operation_id


class ExportReceiptStorageError(ExportReceiptError):
    def __init__(self, *, operation_id: str = "") -> None:
        super().__init__(
            "exportReceiptStorageFailed", "The delivery receipt could not be saved or read.", operation_id=operation_id
        )


class ExportReceiptBusyError(ExportReceiptError):
    def __init__(self) -> None:
        super().__init__("exportReceiptBusy", "A delivery operation is still running.", status_code=409)


class ExportReceiptStore:
    """Persistent delivery facts, separate from source scores and delivered files.

    Construction and reads do not create storage. Execution, recovery, and clearing
    share an OS lock; the adjacent lock file is deliberately never removed.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = stable_path(path)

    @property
    def lock_path(self) -> Path:
        path = self._storage_path()
        return path.with_name(f"{path.name}.lock")

    def _storage_path(self) -> Path:
        # Only storage identity is canonicalized; payload paths retain their aliases.
        try:
            return self.path.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise ExportReceiptStorageError() from exc

    def _has_database(self) -> bool:
        try:
            self.path.stat()
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise ExportReceiptStorageError() from exc

    def run_export(
        self,
        source_df: pd.DataFrame,
        cache_path: str | Path,
        destination_text: str,
        *,
        source_snapshot: Mapping[str, object],
        copy_action: Callable[..., object] = export_selected_files_action,
    ) -> dict[str, Any]:
        if path_identity_key(cache_path) == path_identity_key(self.path):
            raise ExportReceiptError(
                "exportReceiptPathConflict",
                "Delivery receipts must be stored separately from the score database.",
                status_code=400,
            )
        with self._execution_lock():
            self._ensure_schema()
            with self._connection(write=True) as conn:
                self._recover_interrupted(conn)
            observer = _ReceiptObserver(self, source_snapshot)
            try:
                copy_action(source_df, str(cache_path), destination_text, observer=observer)
                if not observer.started:
                    raise ExportReceiptStorageError()
                return self._complete(observer.operation_id)
            except Exception as exc:
                error = _export_error(exc, observer.operation_id)
                if observer.started:
                    try:
                        self._fail(observer.operation_id, error)
                    except ExportReceiptStorageError as storage_error:
                        raise ExportReceiptStorageError(operation_id=observer.operation_id) from storage_error
                raise error from exc

    def latest(self) -> dict[str, Any] | None:
        if not self._has_database():
            return None
        with self._connection() as conn:
            row = conn.execute(f"SELECT * FROM {_OPERATIONS} ORDER BY sequence DESC LIMIT 1").fetchone()
            return self._payload(conn, row) if row else None

    def get(self, operation_id: str) -> dict[str, Any] | None:
        if not operation_id or not self._has_database():
            return None
        with self._connection() as conn:
            row = conn.execute(f"SELECT * FROM {_OPERATIONS} WHERE operation_id = ?", (operation_id,)).fetchone()
            return self._payload(conn, row, include_entries=True) if row else None

    def manifest_csv(self, operation_id: str) -> bytes | None:
        receipt = self.get(operation_id)
        if receipt is None:
            return None
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            [
                "operationId",
                "sequence",
                "operationStatus",
                "destination",
                "index",
                "fileId",
                "source",
                "target",
                "status",
                "reason",
                "message",
                "startedAt",
                "finishedAt",
                "operationErrorCode",
            ]
        )
        for entry in receipt["entries"]:
            writer.writerow(
                [
                    _csv_cell(value)
                    for value in (
                        receipt["operationId"],
                        receipt["sequence"],
                        receipt["status"],
                        receipt["destination"],
                        entry["index"],
                        entry["fileId"],
                        entry["source"],
                        entry["target"],
                        entry["status"],
                        entry["reason"],
                        entry["message"],
                        entry["startedAt"],
                        entry["finishedAt"],
                        receipt["errorCode"],
                    )
                ]
            )
        return output.getvalue().encode("utf-8-sig")

    def recover_interrupted(self) -> int:
        """Mark abandoned work explicitly, without inspecting or changing photos."""
        if not self._has_database():
            return 0
        try:
            with self._execution_lock(), self._connection(write=True) as conn:
                return self._recover_interrupted(conn)
        except ExportReceiptBusyError:
            return 0

    def _recover_interrupted(self, conn: sqlite3.Connection) -> int:
        rows = conn.execute(f"SELECT operation_id FROM {_OPERATIONS} WHERE status = 'running'").fetchall()
        for row in rows:
            self._finish_incomplete(conn, row["operation_id"], "interrupted", "exportInterrupted", {})
        return len(rows)

    def clear(self) -> int:
        """Delete receipt records only; delivered photos and the lock remain untouched."""
        if not self._has_database():
            return 0
        with self._execution_lock(), self._connection(write=True) as conn:
            conn.execute("PRAGMA secure_delete = ON")
            count = int(conn.execute(f"SELECT COUNT(*) FROM {_OPERATIONS}").fetchone()[0])
            conn.execute(f"DELETE FROM {_OPERATIONS}")
            return count

    @contextmanager
    def _execution_lock(self) -> Iterator[None]:
        try:
            lock_path = self.lock_path
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            handle = lock_path.open("a+b")
        except OSError as exc:
            raise ExportReceiptStorageError() from exc
        locked = False
        try:
            if os.name == "nt":
                import msvcrt

                if os.fstat(handle.fileno()).st_size == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                        raise ExportReceiptBusyError() from exc
                    raise
            else:
                import fcntl

                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise ExportReceiptBusyError() from exc
            locked = True
            yield
        except OSError as exc:
            raise ExportReceiptStorageError() from exc
        finally:
            try:
                if locked:
                    if os.name == "nt":
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        try:
            path = self._storage_path()
            conn = sqlite3.connect(path if write else f"{path.as_uri()}?mode=ro", uri=not write)
            try:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA foreign_keys = ON")
                if write:
                    conn.execute("PRAGMA synchronous = FULL")
                else:
                    conn.execute("BEGIN")
                yield conn
                if write:
                    conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                conn.close()
        except (sqlite3.Error, OSError, ValueError, TypeError, LookupError) as exc:
            raise ExportReceiptStorageError() from exc

    def _ensure_schema(self) -> None:
        with self._connection(write=True) as conn:
            conn.execute(
                f"""CREATE TABLE IF NOT EXISTS {_OPERATIONS} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation_id TEXT NOT NULL UNIQUE,
                    revision INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    source_json TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    finished_at REAL,
                    total INTEGER NOT NULL,
                    error_code TEXT NOT NULL DEFAULT '',
                    error_text_json TEXT
                )"""
            )
            conn.execute(
                f"""CREATE TABLE IF NOT EXISTS {_FILES} (
                    operation_id TEXT NOT NULL REFERENCES {_OPERATIONS}(operation_id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL,
                    file_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    target TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    reason TEXT NOT NULL DEFAULT '',
                    message TEXT NOT NULL DEFAULT '',
                    message_text_json TEXT,
                    started_at REAL,
                    finished_at REAL,
                    PRIMARY KEY (operation_id, ordinal)
                )"""
            )

    def _begin(
        self,
        operation_id: str,
        selected_df: pd.DataFrame,
        destination: Path,
        source_snapshot: Mapping[str, object],
    ) -> None:
        now = time.time()
        with self._connection(write=True) as conn:
            conn.execute(
                f"""INSERT INTO {_OPERATIONS}
                    (operation_id, revision, status, destination, source_json, started_at, updated_at, total)
                    VALUES (?, 1, 'running', ?, ?, ?, ?, ?)""",
                (operation_id, str(stable_path(destination)), _json(source_snapshot), now, now, len(selected_df)),
            )
            conn.executemany(
                f"INSERT INTO {_FILES} (operation_id, ordinal, file_id, source) VALUES (?, ?, ?, ?)",
                [
                    (operation_id, index, str(row.get("file_id") or ""), str(stable_path(str(row.get("path") or ""))))
                    for index, (_, row) in enumerate(selected_df.iterrows())
                ],
            )

    def _file_started(self, operation_id: str, index: int, file_id: str, source: Path) -> None:
        with self._connection(write=True) as conn:
            changed = conn.execute(
                f"""UPDATE {_FILES} SET status = 'copying', started_at = ?
                    WHERE operation_id = ? AND ordinal = ? AND file_id = ? AND source = ? AND status = 'pending'""",
                (time.time(), operation_id, index, file_id, str(stable_path(source))),
            )
            self._touch(conn, operation_id, changed.rowcount)

    def _target_created(self, operation_id: str, index: int, target: Path) -> None:
        with self._connection(write=True) as conn:
            changed = conn.execute(
                f"""UPDATE {_FILES} SET target = ?
                    WHERE operation_id = ? AND ordinal = ? AND status = 'copying' AND target IS NULL""",
                (str(stable_path(target)), operation_id, index),
            )
            self._touch(conn, operation_id, changed.rowcount)

    def _file_finished(self, operation_id: str, outcome: ExportFileOutcome) -> None:
        if outcome.status not in {"copied", "missing", "copy_failed"}:
            raise ExportReceiptStorageError(operation_id=operation_id)
        if outcome.status == "copied" and outcome.target is None:
            raise ExportReceiptStorageError(operation_id=operation_id)
        with self._connection(write=True) as conn:
            changed = conn.execute(
                f"""UPDATE {_FILES} SET status = ?, target = COALESCE(?, target), reason = ?, message = ?,
                    message_text_json = ?, finished_at = ?
                    WHERE operation_id = ? AND ordinal = ? AND file_id = ? AND source = ? AND status = 'copying'""",
                (
                    outcome.status,
                    str(stable_path(outcome.target)) if outcome.target else None,
                    outcome.reason,
                    outcome.message,
                    _json(outcome.message_text),
                    time.time(),
                    operation_id,
                    outcome.index,
                    outcome.file_id,
                    str(stable_path(outcome.source)),
                ),
            )
            self._touch(conn, operation_id, changed.rowcount)

    def _touch(self, conn: sqlite3.Connection, operation_id: str, changed_items: int) -> None:
        if changed_items != 1:
            raise ExportReceiptStorageError(operation_id=operation_id)
        changed = conn.execute(
            f"UPDATE {_OPERATIONS} SET revision = revision + 1, updated_at = ? WHERE operation_id = ? AND status = 'running'",
            (time.time(), operation_id),
        )
        if changed.rowcount != 1:
            raise ExportReceiptStorageError(operation_id=operation_id)

    def _complete(self, operation_id: str) -> dict[str, Any]:
        with self._connection(write=True) as conn:
            row = conn.execute(f"SELECT * FROM {_OPERATIONS} WHERE operation_id = ?", (operation_id,)).fetchone()
            finished = conn.execute(
                f"SELECT COUNT(*) FROM {_FILES} WHERE operation_id = ? AND status IN ('copied', 'missing', 'copy_failed')",
                (operation_id,),
            ).fetchone()[0]
            if row is None or row["status"] != "running" or finished != row["total"]:
                raise ExportReceiptStorageError(operation_id=operation_id)
            now = time.time()
            conn.execute(
                f"UPDATE {_OPERATIONS} SET status = 'completed', revision = revision + 1, updated_at = ?, finished_at = ? WHERE operation_id = ?",
                (now, now, operation_id),
            )
            row = conn.execute(f"SELECT * FROM {_OPERATIONS} WHERE operation_id = ?", (operation_id,)).fetchone()
            return self._payload(conn, row)

    def _fail(self, operation_id: str, error: ExportReceiptError) -> None:
        with self._connection(write=True) as conn:
            self._finish_incomplete(conn, operation_id, "failed", error.error_code, error.params)

    def _finish_incomplete(
        self,
        conn: sqlite3.Connection,
        operation_id: str,
        status: str,
        error_code: str,
        params: Mapping[str, object],
    ) -> None:
        now = time.time()
        error_text = _json(text_ref(f"apiError.{error_code}", **params))
        conn.execute(
            f"""UPDATE {_FILES} SET status = CASE status WHEN 'copying' THEN 'unconfirmed' ELSE 'not_attempted' END,
                reason = ?, message_text_json = ?, finished_at = ?
                WHERE operation_id = ? AND status IN ('pending', 'copying')""",
            (error_code, error_text, now, operation_id),
        )
        conn.execute(
            f"""UPDATE {_OPERATIONS} SET status = ?, error_code = ?, error_text_json = ?,
                revision = revision + 1, updated_at = ?, finished_at = ?
                WHERE operation_id = ? AND status = 'running'""",
            (status, error_code, error_text, now, now, operation_id),
        )

    def _payload(self, conn: sqlite3.Connection, row: sqlite3.Row, *, include_entries: bool = False) -> dict[str, Any]:
        operation_id = row["operation_id"]
        counts = dict(
            conn.execute(
                f"SELECT status, COUNT(*) FROM {_FILES} WHERE operation_id = ? GROUP BY status", (operation_id,)
            ).fetchall()
        )
        copied = int(counts.get("copied", 0))
        skipped = int(counts.get("missing", 0) + counts.get("copy_failed", 0))
        preview = conn.execute(
            f"SELECT * FROM {_FILES} WHERE operation_id = ? ORDER BY ordinal LIMIT ?", (operation_id, _PREVIEW_LIMIT)
        ).fetchall()
        copied_files = conn.execute(
            f"SELECT target FROM {_FILES} WHERE operation_id = ? AND status = 'copied' ORDER BY ordinal LIMIT ?",
            (operation_id, _PREVIEW_LIMIT),
        ).fetchall()
        skipped_files = conn.execute(
            f"SELECT * FROM {_FILES} WHERE operation_id = ? AND status IN ('missing', 'copy_failed') ORDER BY ordinal LIMIT ?",
            (operation_id, _PREVIEW_LIMIT),
        ).fetchall()
        payload: dict[str, Any] = {
            "ok": row["status"] == "completed",
            "schemaVersion": EXPORT_PAYLOAD_VERSION,
            "operationId": operation_id,
            "sequence": row["sequence"],
            "revision": row["revision"],
            "status": row["status"],
            "destination": row["destination"],
            "source": json.loads(row["source_json"]),
            "startedAt": row["started_at"],
            "updatedAt": row["updated_at"],
            "finishedAt": row["finished_at"],
            "total": row["total"],
            "processed": copied + skipped,
            "copied": copied,
            "skipped": skipped,
            "unconfirmed": int(counts.get("unconfirmed", 0)),
            "notAttempted": int(counts.get("pending", 0) + counts.get("not_attempted", 0)),
            "copiedFiles": [item["target"] for item in copied_files],
            "skippedDetails": [
                {
                    "path": item["source"],
                    "reason": item["reason"],
                    "label": SKIPPED_REASON_LABELS.get(item["reason"], "未复制"),
                    "message": item["message"],
                    "messageText": json.loads(item["message_text_json"] or "null"),
                }
                for item in skipped_files
            ],
            "skippedReasonSummary": [
                {"reason": reason, "label": SKIPPED_REASON_LABELS[reason], "count": counts[reason]}
                for reason in ("missing", "copy_failed")
                if counts.get(reason)
            ],
            "previewEntries": [_entry_payload(item) for item in preview],
            "previewCount": len(preview),
            "totalEntryCount": row["total"],
            "errorCode": row["error_code"],
            "errorText": json.loads(row["error_text_json"] or "null"),
        }
        if include_entries:
            payload["entries"] = [
                _entry_payload(item)
                for item in conn.execute(
                    f"SELECT * FROM {_FILES} WHERE operation_id = ? ORDER BY ordinal", (operation_id,)
                )
            ]
        return payload


class _ReceiptObserver:
    def __init__(self, store: ExportReceiptStore, source_snapshot: Mapping[str, object]) -> None:
        self.store = store
        self.source_snapshot = source_snapshot
        self.operation_id = ""
        self.started = False

    def export_started(self, selected_df: pd.DataFrame, destination: Path) -> None:
        if self.operation_id:
            raise ExportReceiptStorageError(operation_id=self.operation_id)
        self.operation_id = uuid.uuid4().hex
        self.store._begin(self.operation_id, selected_df, destination, self.source_snapshot)
        self.started = True

    def file_started(self, index: int, file_id: str, source: Path) -> None:
        self.store._file_started(self.operation_id, index, file_id, source)

    def target_created(self, index: int, target: Path) -> None:
        self.store._target_created(self.operation_id, index, target)

    def file_finished(self, outcome: ExportFileOutcome) -> None:
        self.store._file_finished(self.operation_id, outcome)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _entry_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "index": row["ordinal"],
        "fileId": row["file_id"],
        "source": row["source"],
        "target": row["target"],
        "status": row["status"],
        "reason": row["reason"],
        "message": row["message"],
        "messageText": json.loads(row["message_text_json"] or "null"),
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
    }


def _export_error(error: Exception, operation_id: str) -> ExportReceiptError:
    if isinstance(error, (ExportProgressError, ExportReceiptStorageError)):
        return ExportReceiptStorageError(operation_id=operation_id)
    if isinstance(error, ExportServiceError):
        return ExportReceiptError(
            error.error_code,
            error.message,
            status_code=error.status_code,
            params=error.params,
            operation_id=operation_id,
        )
    return ExportReceiptError("exportFailed", "Photo delivery failed.", operation_id=operation_id)


def _csv_cell(value: object) -> object:
    if isinstance(value, str) and value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return "'" + value
    return value
