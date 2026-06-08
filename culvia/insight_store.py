from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from culvia.cache_schema import (
    APP_CONFIG_TABLE,
    INSIGHT_COLUMNS,
    INSIGHT_TABLE,
    LLM_CONFIG_STORAGE_KEYS,
    is_sqlite_cache_path,
    json_dumps,
    json_loads,
)


@dataclass(frozen=True)
class AnalysisInsight:
    file_id: str
    analyzer_key: str
    provider: str
    model: str
    model_version: str = ""
    prompt_version: str = ""
    score: float | None = None
    confidence: float | None = None
    title: str = ""
    summary: str = ""
    explanation: str = ""
    suggestions: tuple[str, ...] = ()
    raw_json: Mapping[str, object] | None = None
    created_at: float = field(default_factory=time.time)


SchemaEnsurer = Callable[[sqlite3.Connection], None]
ConfigCleaner = Callable[[Mapping[str, object] | None], dict[str, str]]


@dataclass(frozen=True)
class AnalysisInsightStore:
    schema_ensurer: SchemaEnsurer
    table_name: str = INSIGHT_TABLE
    columns: Mapping[str, str] = field(default_factory=lambda: INSIGHT_COLUMNS)

    def save(self, insights: Iterable[AnalysisInsight], cache_path: str | Path) -> None:
        path = Path(cache_path).expanduser()
        if not is_sqlite_cache_path(path):
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        columns = list(self.columns)
        placeholders = ", ".join(["?"] * len(columns))
        quoted_columns = ", ".join(f'"{column}"' for column in columns)
        update_columns = [
            column
            for column in columns
            if column not in {"file_id", "analyzer_key", "provider", "model", "model_version", "prompt_version"}
        ]
        update_clause = ", ".join(f'"{column}" = excluded."{column}"' for column in update_columns)
        sql = (
            f"INSERT INTO {self.table_name} ({quoted_columns}) VALUES ({placeholders}) "
            f'ON CONFLICT("file_id", "analyzer_key", "provider", "model", "model_version", "prompt_version") '
            f"DO UPDATE SET {update_clause}"
        )
        with sqlite3.connect(path) as conn:
            self.schema_ensurer(conn)
            for insight in insights:
                conn.execute(sql, self._to_values(insight))
            conn.commit()

    def load(self, cache_path: str | Path, file_ids: Iterable[str] | None = None) -> list[AnalysisInsight]:
        path = Path(cache_path).expanduser()
        if not is_sqlite_cache_path(path) or not path.exists():
            return []
        with sqlite3.connect(path) as conn:
            self.schema_ensurer(conn)
            if file_ids is None:
                rows = conn.execute(f"SELECT * FROM {self.table_name}").fetchall()
            else:
                ids = [str(file_id) for file_id in file_ids]
                if not ids:
                    return []
                placeholders = ", ".join(["?"] * len(ids))
                rows = conn.execute(
                    f"SELECT * FROM {self.table_name} WHERE file_id IN ({placeholders})", ids
                ).fetchall()
            columns = [row[1] for row in conn.execute(f"PRAGMA table_info({self.table_name})").fetchall()]
        return [self._from_mapping(dict(zip(columns, row))) for row in rows]

    def _to_values(self, insight: AnalysisInsight) -> list[object]:
        return [
            insight.file_id,
            insight.analyzer_key,
            insight.provider,
            insight.model,
            insight.model_version,
            insight.prompt_version,
            insight.score,
            insight.confidence,
            insight.title,
            insight.summary,
            insight.explanation,
            json_dumps(list(insight.suggestions)),
            json_dumps(insight.raw_json or {}),
            insight.created_at,
        ]

    def _from_mapping(self, row: Mapping[str, object]) -> AnalysisInsight:
        suggestions = json_loads(row.get("suggestions_json"), [])
        raw_json = json_loads(row.get("raw_json"), {})
        return AnalysisInsight(
            file_id=str(row.get("file_id") or ""),
            analyzer_key=str(row.get("analyzer_key") or ""),
            provider=str(row.get("provider") or ""),
            model=str(row.get("model") or ""),
            model_version=str(row.get("model_version") or ""),
            prompt_version=str(row.get("prompt_version") or ""),
            score=None if pd.isna(row.get("score")) else float(row.get("score")),
            confidence=None if pd.isna(row.get("confidence")) else float(row.get("confidence")),
            title=str(row.get("title") or ""),
            summary=str(row.get("summary") or ""),
            explanation=str(row.get("explanation") or ""),
            suggestions=tuple(str(item) for item in suggestions if str(item).strip())
            if isinstance(suggestions, list)
            else (),
            raw_json=raw_json if isinstance(raw_json, Mapping) else {},
            created_at=float(row.get("created_at") or 0.0),
        )


@dataclass(frozen=True)
class AppConfigStore:
    schema_ensurer: SchemaEnsurer
    clean_config: ConfigCleaner
    table_name: str = APP_CONFIG_TABLE
    storage_keys: Mapping[str, str] = field(default_factory=lambda: LLM_CONFIG_STORAGE_KEYS)

    def load(self, cache_path: str | Path) -> dict[str, str]:
        path = Path(cache_path).expanduser()
        if not is_sqlite_cache_path(path) or not path.exists():
            return {}
        reverse_keys = {stored: field for field, stored in self.storage_keys.items()}
        with sqlite3.connect(path) as conn:
            self.schema_ensurer(conn)
            rows = conn.execute(f'SELECT "key", "value" FROM {self.table_name}').fetchall()
        config: dict[str, str] = {}
        for key, value in rows:
            field_name = reverse_keys.get(str(key))
            value_text = str(value or "").strip()
            if field_name and value_text:
                config[field_name] = value_text
        return self.clean_config(config)

    def save(self, config: Mapping[str, object], cache_path: str | Path) -> dict[str, str]:
        path = Path(cache_path).expanduser()
        if not is_sqlite_cache_path(path):
            raise ValueError("大模型配置持久化需要 SQLite 缓存文件。")
        path.parent.mkdir(parents=True, exist_ok=True)
        cleaned = self.clean_config(config)
        now = time.time()
        with sqlite3.connect(path) as conn:
            self.schema_ensurer(conn)
            for field_name, storage_key in self.storage_keys.items():
                value = cleaned.get(field_name)
                if value:
                    conn.execute(
                        f'INSERT INTO {self.table_name} ("key", "value", "updated_at") VALUES (?, ?, ?) '
                        'ON CONFLICT("key") DO UPDATE SET "value" = excluded."value", "updated_at" = excluded."updated_at"',
                        (storage_key, value, now),
                    )
                elif field_name in config:
                    conn.execute(f'DELETE FROM {self.table_name} WHERE "key" = ?', (storage_key,))
            conn.commit()
        return self.load(path)
