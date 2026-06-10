from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pandas as pd

from culvia.cache_schema import SCORE_TABLE, ensure_cache_schema, is_sqlite_cache_path, sqlite_value

from culvia.job_text import TranslatableValueError


class FieldGroup(Protocol):
    cache_columns: tuple[str, ...]


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
                normalized[column] = normalized[column].astype(str)
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
                columns = ", ".join(f'"{column}"' for column in self.csv_columns)
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
        path.parent.mkdir(parents=True, exist_ok=True)

        merged = self._merged_dataframe(current_df, existing_df)
        columns = list(self.csv_columns)
        insert_columns = columns + ["updated_at"]
        placeholders = ", ".join(["?"] * len(insert_columns))
        quoted_insert_columns = ", ".join(f'"{column}"' for column in insert_columns)
        update_columns = [column for column in insert_columns if column != "file_id"]
        update_clause = ", ".join(f'"{column}" = excluded."{column}"' for column in update_columns)
        sql = (
            f"INSERT INTO {SCORE_TABLE} ({quoted_insert_columns}) VALUES ({placeholders}) "
            f'ON CONFLICT("file_id") DO UPDATE SET {update_clause}'
        )

        now = time.time()
        with sqlite3.connect(path) as conn:
            self.ensure_schema(conn)
            for row in merged.to_dict(orient="records"):
                values = [sqlite_value(row.get(column)) for column in columns]
                conn.execute(sql, values + [now])
            conn.commit()

    def load(self, cache_path: str | Path) -> pd.DataFrame:
        return self.load_sqlite(cache_path)

    def save(
        self,
        current_df: pd.DataFrame,
        cache_path: str | Path,
        existing_df: pd.DataFrame | None = None,
    ) -> None:
        self.save_sqlite(current_df, cache_path, existing_df)

    def _merged_dataframe(self, current_df: pd.DataFrame, existing_df: pd.DataFrame | None = None) -> pd.DataFrame:
        pieces = []
        if existing_df is not None and not existing_df.empty:
            pieces.append(self.normalize_dataframe(existing_df))
        pieces.append(self.normalize_dataframe(current_df))
        return self.normalize_dataframe(pd.concat(pieces, ignore_index=True))
