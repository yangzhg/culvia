from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from culvia.curation_history import append_curation_action
from culvia.curation_undo import curation_undo_conflicts, resolve_curation_undo_target


class CurationUndoTests(unittest.TestCase):
    def test_resolve_target_reads_before_marks_and_keeps_after_marks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            record = append_curation_action(
                cache_path,
                "status",
                payload={
                    "beforeMarks": [{"fileId": "photo-1", "status": ""}],
                    "afterMarks": [{"fileId": "photo-1", "status": "reject"}],
                },
            )

            resolution = resolve_curation_undo_target(cache_path, history_id=record.id)

        self.assertTrue(resolution.ok)
        self.assertEqual(resolution.target.record.id, record.id)
        self.assertEqual(resolution.target.before_marks[0]["fileId"], "photo-1")
        self.assertEqual(resolution.target.after_marks[0]["status"], "reject")

    def test_curation_undo_conflicts_compares_after_marks(self) -> None:
        conflicts = curation_undo_conflicts(
            current_marks=[
                {"fileId": "photo-1", "status": "pick"},
                {"fileId": "photo-2", "status": "reject"},
            ],
            expected_after_marks=[
                {"fileId": "photo-1", "status": "reject"},
                {"fileId": "photo-2", "status": "reject"},
            ],
        )

        self.assertEqual(conflicts, ["photo-1"])


if __name__ == "__main__":
    unittest.main()
