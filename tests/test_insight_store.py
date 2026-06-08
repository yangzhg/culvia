from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Mapping

from culvia.cache_schema import APP_CONFIG_TABLE, ensure_cache_schema
from culvia.insight_store import AnalysisInsight, AnalysisInsightStore, AppConfigStore


SCORE_COLUMNS = ("file_id", "path", "folder", "filename", "error")
TEXT_COLUMNS = {"file_id", "path", "folder", "filename", "error"}


def ensure_test_schema(conn: sqlite3.Connection) -> None:
    ensure_cache_schema(conn, SCORE_COLUMNS, TEXT_COLUMNS)


def clean_config(config: Mapping[str, object] | None) -> dict[str, str]:
    if not config:
        return {}
    return {str(key): str(value).strip() for key, value in config.items() if str(value).strip()}


class InsightStoreTests(unittest.TestCase):
    def test_analysis_insight_store_roundtrips_and_updates_same_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            store = AnalysisInsightStore(schema_ensurer=ensure_test_schema)
            first = AnalysisInsight(
                file_id="image-1",
                analyzer_key="llm_evaluator",
                provider="unit",
                model="mock-vlm",
                model_version="1",
                prompt_version="v1",
                score=6.0,
                summary="first",
                suggestions=("crop",),
                raw_json={"round": 1},
            )
            second = AnalysisInsight(
                file_id="image-1",
                analyzer_key="llm_evaluator",
                provider="unit",
                model="mock-vlm",
                model_version="1",
                prompt_version="v1",
                score=8.5,
                summary="updated",
                suggestions=("light", "tone"),
                raw_json={"round": 2},
            )

            store.save([first], cache_path)
            store.save([second], cache_path)
            loaded = store.load(cache_path, file_ids=["image-1"])

        self.assertEqual(len(loaded), 1)
        self.assertAlmostEqual(float(loaded[0].score or 0), 8.5)
        self.assertEqual(loaded[0].summary, "updated")
        self.assertEqual(loaded[0].suggestions, ("light", "tone"))
        self.assertEqual(dict(loaded[0].raw_json or {}).get("round"), 2)

    def test_analysis_insight_store_ignores_non_sqlite_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.csv"
            store = AnalysisInsightStore(schema_ensurer=ensure_test_schema)

            store.save(
                [
                    AnalysisInsight(
                        file_id="image-1",
                        analyzer_key="llm_evaluator",
                        provider="unit",
                        model="mock",
                    )
                ],
                cache_path,
            )

            self.assertEqual(store.load(cache_path), [])
            self.assertFalse(cache_path.exists())

    def test_app_config_store_does_not_persist_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            store = AppConfigStore(schema_ensurer=ensure_test_schema, clean_config=clean_config)

            saved = store.save(
                {
                    "api_key": "secret",
                    "model": "mock-vlm",
                    "base_url": "https://example.test/v1",
                },
                cache_path,
            )
            self.assertNotIn("api_key", saved)

            loaded = store.save({"model": "mock-vlm-2"}, cache_path)

            self.assertEqual(loaded["model"], "mock-vlm-2")
            self.assertNotIn("api_key", loaded)
            with sqlite3.connect(cache_path) as conn:
                keys = {row[0] for row in conn.execute(f'SELECT "key" FROM {APP_CONFIG_TABLE}').fetchall()}
            self.assertNotIn("api_key", keys)


if __name__ == "__main__":
    unittest.main()
