from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

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
        ),
        text_columns=frozenset({"file_id", "path", "folder", "filename", "error"}),
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
        self.assertAlmostEqual(float(second["quality_0_10"]), 7.5)

    def test_cache_store_rejects_csv_cache_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store()
            cache_path = Path(tmp) / "scores.csv"

            with self.assertRaisesRegex(ValueError, "SQLite"):
                store.load(cache_path)

            with self.assertRaisesRegex(ValueError, "SQLite"):
                store.save(pd.DataFrame([{"file_id": "image-1"}]), cache_path)


if __name__ == "__main__":
    unittest.main()
