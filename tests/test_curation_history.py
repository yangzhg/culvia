from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from culvia.curation_history import append_curation_action, load_curation_action, load_curation_actions


class CurationHistoryTests(unittest.TestCase):
    def test_append_and_load_curation_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"

            first = append_curation_action(
                cache_path,
                "status",
                scope="filtered",
                summary="淘汰 2 张",
                payload={"marked": 2, "beforeMarks": [{"fileId": "photo-1"}]},
            )
            second = append_curation_action(cache_path, "restore", summary="恢复 1 张", payload={"restored": 1})
            records = load_curation_actions(cache_path)
            loaded_first = load_curation_action(cache_path, first.id)

        self.assertEqual([record.id for record in records], [second.id, first.id])
        self.assertEqual(records[0].kind, "restore")
        self.assertEqual(records[0].payload["restored"], 1)
        self.assertEqual(records[1].scope, "filtered")
        self.assertEqual(records[1].payload["schemaVersion"], 1)
        self.assertEqual(records[1].payload["beforeMarks"][0]["fileId"], "photo-1")
        self.assertEqual(loaded_first, first)

    def test_load_curation_actions_handles_missing_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "missing.sqlite"

            records = load_curation_actions(cache_path)

        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
