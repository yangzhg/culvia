from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

import pandas as pd


SQLITE_CACHE_EXTENSIONS = {".sqlite", ".sqlite3", ".db"}
SCORE_TABLE = "culvia_scores"
INSIGHT_TABLE = "photo_analysis_insights"
APP_CONFIG_TABLE = "photo_app_config"
LLM_CONFIG_STORAGE_KEYS = {
    "base_url": "llm_base_url",
    "endpoint": "llm_endpoint",
    "model": "llm_model",
    "provider": "llm_provider",
    "input_mode": "llm_input_mode",
    "prompt_preset": "llm_prompt_preset",
    "custom_prompt": "llm_custom_prompt",
}
INSIGHT_COLUMNS = {
    "file_id": "TEXT NOT NULL",
    "analyzer_key": "TEXT NOT NULL",
    "provider": "TEXT NOT NULL",
    "model": "TEXT NOT NULL",
    "model_version": "TEXT NOT NULL",
    "prompt_version": "TEXT NOT NULL",
    "score": "REAL",
    "confidence": "REAL",
    "title": "TEXT",
    "summary": "TEXT",
    "explanation": "TEXT",
    "suggestions_json": "TEXT",
    "raw_json": "TEXT",
    "created_at": "REAL",
}


def is_sqlite_cache_path(path: str | Path) -> bool:
    return Path(path).expanduser().suffix.lower() in SQLITE_CACHE_EXTENSIONS


def ensure_cache_schema(
    conn: sqlite3.Connection,
    score_columns: Iterable[str],
    text_columns: set[str],
) -> None:
    ensure_scores_table(conn, score_columns, text_columns)
    ensure_insights_table(conn)
    ensure_app_config_table(conn)


def ensure_scores_table(
    conn: sqlite3.Connection,
    score_columns: Iterable[str],
    text_columns: set[str],
) -> None:
    columns = list(score_columns)
    column_defs = []
    for column in columns:
        column_type = "TEXT" if column in text_columns else "REAL"
        primary = " PRIMARY KEY" if column == "file_id" else ""
        column_defs.append(f'"{column}" {column_type}{primary}')
    column_defs.append('"updated_at" REAL')
    conn.execute(f"CREATE TABLE IF NOT EXISTS {SCORE_TABLE} ({', '.join(column_defs)})")


def ensure_insights_table(conn: sqlite3.Connection) -> None:
    column_defs = [f'"{column}" {column_type}' for column, column_type in INSIGHT_COLUMNS.items()]
    column_defs.append(
        'PRIMARY KEY ("file_id", "analyzer_key", "provider", "model", "model_version", "prompt_version")'
    )
    conn.execute(f"CREATE TABLE IF NOT EXISTS {INSIGHT_TABLE} ({', '.join(column_defs)})")


def ensure_app_config_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {APP_CONFIG_TABLE} "
        '("key" TEXT PRIMARY KEY, "value" TEXT NOT NULL, "updated_at" REAL NOT NULL)'
    )


def sqlite_value(value: object) -> object:
    if pd.isna(value):
        return None
    return value


def json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def json_loads(value: object, fallback: object) -> object:
    if value is None or pd.isna(value):
        return fallback
    try:
        return json.loads(str(value))
    except Exception:
        return fallback
