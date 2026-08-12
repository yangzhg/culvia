from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Self

import pandas as pd

from culvia.cache_schema import SCORE_TABLE, ensure_cache_schema, is_sqlite_cache_path, sqlite_value

from culvia.job_text import TranslatableValueError


class FieldGroup(Protocol):
    cache_columns: tuple[str, ...]


class ScoreCacheCheckpointWriter:
    def __init__(self, store: ScoreCacheStore, cache_path: str | Path) -> None:
        self.store = store
        self.path = store._sqlite_path(cache_path)
        self.connection: sqlite3.Connection | None = None
        self.sql = ""

    def __enter__(self) -> Self:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.store.ensure_schema(self.connection)
        self.connection.commit()
        self.sql = self.store._upsert_sql()
        return self

    def upsert(self, records_df: pd.DataFrame) -> None:
        if self.connection is None:
            raise RuntimeError("Score cache checkpoint writer is not open")
        normalized = self.store._normalized_upsert_records(records_df)
        rows = self.store._sqlite_rows(normalized)
        self.connection.executemany(self.sql, rows)
        self.connection.commit()

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None


@dataclass(frozen=True)
class ScoreCacheStore:
    csv_columns: tuple[str, ...]
    text_columns: frozenset[str]
    field_groups: tuple[FieldGroup, ...]
    recommendation_column: str

    def empty_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame(columns=list(self.csv_columns))

    def normalize_dataframe(self, df: pd.DataFrame | None) -> pd.DataFrame:
        if df is None or df.empty:
            return self.empty_dataframe()

        normalized = df.copy()
        for column in self.csv_columns:
            if column not in normalized.columns:
                normalized[column] = "" if column in self.text_columns else pd.NA

        normalized = normalized[list(self.csv_columns)]
        for column in self.text_columns:
            if column == "error":
                normalized[column] = normalized[column].fillna("").astype(str)
            else:
                normalized[column] = normalized[column].fillna("").astype(str)
        normalized[self.recommendation_column] = pd.to_numeric(normalized[self.recommendation_column], errors="coerce")

        for group in self.field_groups:
            for column in group.cache_columns:
                normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

        return normalized.drop_duplicates(subset=["file_id"], keep="last")

    def ensure_schema(self, conn: sqlite3.Connection) -> None:
        ensure_cache_schema(conn, self.csv_columns, set(self.text_columns))

    def _sqlite_path(self, cache_path: str | Path) -> Path:
        path = Path(cache_path).expanduser()
        if not is_sqlite_cache_path(path):
            raise TranslatableValueError(
                "error.scoreCacheNotSqlite",
                fallback="评分缓存只支持 SQLite 文件（.sqlite、.sqlite3 或 .db）。CSV 仅用于导出。",
            )
        return path

    def load_sqlite(self, cache_path: str | Path) -> pd.DataFrame:
        path = self._sqlite_path(cache_path)
        if not path.exists():
            return self.empty_dataframe()

        try:
            with sqlite3.connect(path) as conn:
                self.ensure_schema(conn)
                available = {row[1] for row in conn.execute(f"PRAGMA table_info({SCORE_TABLE})").fetchall()}
                selected_columns = [column for column in self.csv_columns if column in available]
                if not selected_columns:
                    return self.empty_dataframe()
                columns = ", ".join(f'"{column}"' for column in selected_columns)
                return self.normalize_dataframe(pd.read_sql_query(f"SELECT {columns} FROM {SCORE_TABLE}", conn))
        except Exception:
            return self.empty_dataframe()

    def save_sqlite(
        self,
        current_df: pd.DataFrame,
        cache_path: str | Path,
        existing_df: pd.DataFrame | None = None,
    ) -> None:
        path = self._sqlite_path(cache_path)
        merged = self._merged_dataframe(current_df, existing_df)
        self._write_sqlite_rows(merged, path)

    def upsert_sqlite(self, records_df: pd.DataFrame, cache_path: str | Path) -> None:
        path = self._sqlite_path(cache_path)
        normalized = self._normalized_upsert_records(records_df)
        self._write_sqlite_rows(normalized, path)

    def checkpoint_writer(self, cache_path: str | Path) -> ScoreCacheCheckpointWriter:
        return ScoreCacheCheckpointWriter(self, cache_path)

    def _normalized_upsert_records(self, records_df: pd.DataFrame) -> pd.DataFrame:
        normalized = self.normalize_dataframe(records_df)
        if normalized["file_id"].str.strip().eq("").any():
            raise ValueError("Score cache records require a non-empty file_id")
        return normalized

    def _write_sqlite_rows(self, records_df: pd.DataFrame, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = self._sqlite_rows(records_df)
        with sqlite3.connect(path) as conn:
            self.ensure_schema(conn)
            conn.executemany(self._upsert_sql(), rows)
            conn.commit()

    def _upsert_sql(self) -> str:
        columns = list(self.csv_columns)
        insert_columns = columns + ["updated_at"]
        placeholders = ", ".join(["?"] * len(insert_columns))
        quoted_insert_columns = ", ".join(f'"{column}"' for column in insert_columns)
        update_columns = [column for column in insert_columns if column != "file_id"]
        update_clause = ", ".join(f'"{column}" = excluded."{column}"' for column in update_columns)
        return (
            f"INSERT INTO {SCORE_TABLE} ({quoted_insert_columns}) VALUES ({placeholders}) "
            f'ON CONFLICT("file_id") DO UPDATE SET {update_clause}'
        )

    def _sqlite_rows(self, records_df: pd.DataFrame) -> list[list[object]]:
        columns = list(self.csv_columns)
        now = time.time()
        return [
            [sqlite_value(row.get(column)) for column in columns] + [now]
            for row in records_df.to_dict(orient="records")
        ]

    def load(self, cache_path: str | Path) -> pd.DataFrame:
        return self.load_sqlite(cache_path)

    def save(
        self,
        current_df: pd.DataFrame,
        cache_path: str | Path,
        existing_df: pd.DataFrame | None = None,
    ) -> None:
        self.save_sqlite(current_df, cache_path, existing_df)

    def upsert(self, records_df: pd.DataFrame, cache_path: str | Path) -> None:
        self.upsert_sqlite(records_df, cache_path)

    def _merged_dataframe(self, current_df: pd.DataFrame, existing_df: pd.DataFrame | None = None) -> pd.DataFrame:
        pieces = []
        if existing_df is not None and not existing_df.empty:
            pieces.append(self.normalize_dataframe(existing_df))
        pieces.append(self.normalize_dataframe(current_df))
        return self.normalize_dataframe(pd.concat(pieces, ignore_index=True))
