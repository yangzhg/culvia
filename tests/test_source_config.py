from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from culvia.cache_schema import APP_CONFIG_TABLE
from culvia.scoring import load_source_config_from_sqlite, save_source_config_to_sqlite


class SourceConfigTests(unittest.TestCase):
    def test_source_config_round_trips_without_secret_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"

            saved = save_source_config_to_sqlite(
                {
                    "mode": "folders",
                    "folders": [str(Path(tmp) / "photos"), str(Path(tmp) / "photos" / "nested")],
                    "cachePath": str(cache_path),
                    "apiKey": "must-not-store",
                },
                cache_path,
            )
            loaded = load_source_config_from_sqlite(cache_path)

            with sqlite3.connect(cache_path) as conn:
                rows = dict(conn.execute(f'SELECT "key", "value" FROM {APP_CONFIG_TABLE}').fetchall())

        self.assertEqual(saved, loaded)
        self.assertEqual(saved["folders"], [str((Path(tmp) / "photos").absolute())])
        self.assertNotIn("apiKey", rows)
        self.assertIn("source_folders_json", rows)


if __name__ == "__main__":
    unittest.main()
