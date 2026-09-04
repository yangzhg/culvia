from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
import sqlite3

import pandas as pd

from culvia.cache_records import ScoreCacheStore


@dataclass(frozen=True)
class DummyFieldGroup:
    cache_columns: tuple[str, ...]


def make_store() -> ScoreCacheStore:
    return ScoreCacheStore(
        csv_columns=(
            "file_id",
            "path",
            "folder",
            "filename",
            "error",
            "recommendation_0_10",
            "overall_0_10",
            "quality_0_10",
            "core_aesthetic_result_version",
        ),
        text_columns=frozenset({"file_id", "path", "folder", "filename", "error", "core_aesthetic_result_version"}),
        field_groups=(DummyFieldGroup(("overall_0_10", "quality_0_10")),),
        recommendation_column="recommendation_0_10",
    )


class CacheRecordStoreTests(unittest.TestCase):
    def test_normalize_dataframe_orders_columns_and_keeps_last_duplicate(self) -> None:
        store = make_store()
        source = pd.DataFrame(
            [
                {"file_id": "image-1", "path": "/a.jpg", "overall_0_10": "6.1"},
                {"file_id": "image-1", "path": "/b.jpg", "overall_0_10": "8.2"},
            ]
        )

        normalized = store.normalize_dataframe(source)

        self.assertEqual(list(normalized.columns), list(store.csv_columns))
        self.assertEqual(len(normalized), 1)
        row = normalized.iloc[0]
        self.assertEqual(row["path"], "/b.jpg")
        self.assertEqual(row["error"], "")
        self.assertAlmostEqual(float(row["overall_0_10"]), 8.2)
        self.assertTrue(pd.isna(row["quality_0_10"]))
        self.assertEqual(row["core_aesthetic_result_version"], "")

    def test_sqlite_roundtrip_merges_existing_and_current_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store()
            cache_path = Path(tmp) / "scores.sqlite"
            existing = pd.DataFrame(
                [{"file_id": "image-1", "path": "/old.jpg", "folder": "/", "filename": "old.jpg", "overall_0_10": 4.0}]
            )
            current = pd.DataFrame(
                [
                    {
                        "file_id": "image-1",
                        "path": "/new.jpg",
                        "folder": "/",
                        "filename": "new.jpg",
                        "overall_0_10": 9.0,
                        "core_aesthetic_result_version": "score-v1:current",
                    },
                    {
                        "file_id": "image-2",
                        "path": "/two.jpg",
                        "folder": "/",
                        "filename": "two.jpg",
                        "quality_0_10": 7.5,
                    },
                ]
            )

            store.save(current, cache_path, existing)
            loaded = store.load(cache_path)

        self.assertEqual(set(loaded["file_id"]), {"image-1", "image-2"})
        first = loaded.set_index("file_id").loc["image-1"]
        second = loaded.set_index("file_id").loc["image-2"]
        self.assertEqual(first["path"], "/new.jpg")
        self.assertAlmostEqual(float(first["overall_0_10"]), 9.0)
        self.assertEqual(first["core_aesthetic_result_version"], "score-v1:current")
        self.assertAlmostEqual(float(second["quality_0_10"]), 7.5)

    def test_upsert_updates_only_the_supplied_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store()
            cache_path = Path(tmp) / "scores.sqlite"
            store.save(
                pd.DataFrame(
                    [
                        {"file_id": "image-1", "path": "/one.jpg", "overall_0_10": 4.0},
                        {"file_id": "image-2", "path": "/two.jpg", "overall_0_10": 7.0},
                    ]
                ),
                cache_path,
            )
            with sqlite3.connect(cache_path) as conn:
                conn.execute("UPDATE culvia_scores SET updated_at = 10 WHERE file_id = 'image-1'")
                conn.execute("UPDATE culvia_scores SET updated_at = 20 WHERE file_id = 'image-2'")
                conn.commit()

            store.upsert(
                pd.DataFrame([{"file_id": "image-1", "path": "/one-new.jpg", "overall_0_10": 9.0}]),
                cache_path,
            )

            with sqlite3.connect(cache_path) as conn:
                rows = {
                    row[0]: row[1:]
                    for row in conn.execute(
                        "SELECT file_id, path, overall_0_10, updated_at FROM culvia_scores ORDER BY file_id"
                    )
                }

        self.assertEqual(rows["image-1"][0], "/one-new.jpg")
        self.assertAlmostEqual(float(rows["image-1"][1]), 9.0)
        self.assertNotEqual(rows["image-1"][2], 10)
        self.assertEqual(rows["image-2"], ("/two.jpg", 7.0, 20.0))

    def test_upsert_can_clear_scores_without_accepting_blank_file_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store()
            cache_path = Path(tmp) / "scores.sqlite"
            store.save(
                pd.DataFrame([{"file_id": "image-1", "path": "/one.jpg", "overall_0_10": 8.0}]),
                cache_path,
            )

            store.upsert(
                pd.DataFrame([{"file_id": "image-1", "path": "/one.jpg", "overall_0_10": pd.NA}]),
                cache_path,
            )
            with self.assertRaisesRegex(ValueError, "non-empty file_id"):
                store.upsert(
                    pd.DataFrame(
                        [
                            {"file_id": "image-1", "path": "/should-not-write.jpg"},
                            {"file_id": " ", "path": "/blank.jpg"},
                        ]
                    ),
                    cache_path,
                )
            loaded = store.load(cache_path).set_index("file_id")

        self.assertTrue(pd.isna(loaded.loc["image-1", "overall_0_10"]))
        self.assertEqual(loaded.loc["image-1", "path"], "/one.jpg")

    def test_cache_store_rejects_csv_cache_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store()
            cache_path = Path(tmp) / "scores.csv"

            with self.assertRaisesRegex(ValueError, "SQLite"):
                store.load(cache_path)

            with self.assertRaisesRegex(ValueError, "SQLite"):
                store.save(pd.DataFrame([{"file_id": "image-1"}]), cache_path)

    def test_load_backfills_columns_missing_from_an_older_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            with sqlite3.connect(cache_path) as conn:
                conn.execute("CREATE TABLE culvia_scores (file_id TEXT PRIMARY KEY, path TEXT, updated_at REAL)")
                conn.execute(
                    "INSERT INTO culvia_scores (file_id, path, updated_at) VALUES (?, ?, ?)",
                    ("image-1", "/legacy.jpg", 1.0),
                )
            loaded = make_store().load(cache_path)

        self.assertEqual(loaded.loc[0, "file_id"], "image-1")
        self.assertEqual(loaded.loc[0, "path"], "/legacy.jpg")
        self.assertTrue(pd.isna(loaded.loc[0, "overall_0_10"]))


if __name__ == "__main__":
    unittest.main()
