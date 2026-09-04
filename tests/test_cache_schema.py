from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from culvia.cache_schema import (
    APP_CONFIG_TABLE,
    INSIGHT_TABLE,
    SCORE_TABLE,
    ensure_cache_schema,
    is_sqlite_cache_path,
    json_dumps,
    json_loads,
    sqlite_value,
)


class CacheSchemaHelperTests(unittest.TestCase):
    def test_sqlite_path_detection_accepts_known_extensions(self) -> None:
        self.assertTrue(is_sqlite_cache_path("/tmp/scores.sqlite"))
        self.assertTrue(is_sqlite_cache_path("/tmp/scores.sqlite3"))
        self.assertTrue(is_sqlite_cache_path("/tmp/scores.db"))
        self.assertFalse(is_sqlite_cache_path("/tmp/scores.csv"))

    def test_ensure_cache_schema_creates_current_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            with sqlite3.connect(cache_path) as conn:
                ensure_cache_schema(
                    conn,
                    ["file_id", "path", "overall_0_10"],
                    {"file_id", "path"},
                )

                score_columns = {row[1]: row[2] for row in conn.execute(f"PRAGMA table_info({SCORE_TABLE})").fetchall()}
                tables = {
                    row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
                }

        self.assertEqual(score_columns["file_id"], "TEXT")
        self.assertEqual(score_columns["path"], "TEXT")
        self.assertEqual(score_columns["overall_0_10"], "REAL")
        self.assertEqual(score_columns["updated_at"], "REAL")
        self.assertIn(INSIGHT_TABLE, tables)
        self.assertIn(APP_CONFIG_TABLE, tables)

    def test_ensure_cache_schema_adds_new_score_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            with sqlite3.connect(cache_path) as conn:
                ensure_cache_schema(conn, ["file_id", "path"], {"file_id", "path"})
                ensure_cache_schema(
                    conn,
                    ["file_id", "path", "llm_review_generation"],
                    {"file_id", "path"},
                )
                columns = {row[1]: row[2] for row in conn.execute(f"PRAGMA table_info({SCORE_TABLE})").fetchall()}

        self.assertEqual(columns["llm_review_generation"], "REAL")

    def test_result_version_migration_is_nullable_and_does_not_bless_legacy_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            with sqlite3.connect(cache_path) as conn:
                ensure_cache_schema(conn, ["file_id", "overall_0_10"], {"file_id"})
                conn.execute(
                    "INSERT INTO culvia_scores (file_id, overall_0_10) VALUES (?, ?)",
                    ("legacy-photo", 8.2),
                )
                ensure_cache_schema(
                    conn,
                    ["file_id", "overall_0_10", "core_aesthetic_result_version"],
                    {"file_id", "core_aesthetic_result_version"},
                )
                row = conn.execute("SELECT overall_0_10, core_aesthetic_result_version FROM culvia_scores").fetchone()
                column_type = {
                    item[1]: item[2] for item in conn.execute("PRAGMA table_info(culvia_scores)").fetchall()
                }["core_aesthetic_result_version"]

        self.assertEqual(row, (8.2, None))
        self.assertEqual(column_type, "TEXT")

    def test_readonly_legacy_schema_remains_readable_without_migration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            with sqlite3.connect(cache_path) as conn:
                ensure_cache_schema(conn, ["file_id", "path"], {"file_id", "path"})
            with sqlite3.connect(f"file:{cache_path}?mode=ro", uri=True) as conn:
                ensure_cache_schema(
                    conn,
                    ["file_id", "path", "llm_review_generation"],
                    {"file_id", "path"},
                )
                columns = {row[1] for row in conn.execute(f"PRAGMA table_info({SCORE_TABLE})").fetchall()}

        self.assertNotIn("llm_review_generation", columns)

    def test_json_helpers_and_sqlite_value(self) -> None:
        payload = {"z": 1, "a": ["建议"]}

        encoded = json_dumps(payload)

        self.assertEqual(json_loads(encoded, {}), payload)
        self.assertEqual(json_loads("", []), [])
        self.assertIsNone(sqlite_value(pd.NA))
        self.assertEqual(sqlite_value(7.2), 7.2)


if __name__ == "__main__":
    unittest.main()
