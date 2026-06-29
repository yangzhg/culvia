from __future__ import annotations

import unittest

from culvia.curation_history import CurationActionRecord
from culvia.curation_payloads import curation_action_undo_state, mark_history_payload, serialize_curation_action


class CurationPayloadTests(unittest.TestCase):
    def test_mark_history_payload_records_before_and_after_marks(self) -> None:
        before = [{"fileId": "photo-1", "status": ""}]
        after = [{"fileId": "photo-1", "status": "pick"}]

        payload = mark_history_payload({"marked": 1}, before_marks=before, after_marks=after)

        self.assertEqual(payload["beforeMarks"], before)
        self.assertEqual(payload["afterMarks"], after)
        self.assertEqual(payload["marked"], 1)
        self.assertNotIn("previousMarks", payload)

    def test_serialize_curation_action_includes_undo_state(self) -> None:
        record = CurationActionRecord(
            id="history-1",
            kind="status",
            scope="filtered",
            summary="淘汰 2 张",
            payload={"beforeMarks": [{"fileId": "photo-1"}]},
            created_at=123.0,
        )

        payload = serialize_curation_action(record)

        self.assertEqual(payload["id"], "history-1")
        self.assertEqual(payload["undoState"], "available")
        self.assertEqual(payload["createdAt"], 123.0)

    def test_curation_action_undo_state_marks_undone_actions(self) -> None:
        record = CurationActionRecord(
            id="history-1",
            kind="status",
            scope="filtered",
            summary="淘汰 2 张",
            payload={"beforeMarks": [{"fileId": "photo-1"}]},
            created_at=123.0,
        )

        self.assertEqual(curation_action_undo_state(record, {"history-1"}), "undone")

    def test_curation_action_undo_state_marks_undo_records(self) -> None:
        record = CurationActionRecord(
            id="undo-1",
            kind="undo",
            scope="filtered",
            summary="撤销：淘汰 2 张",
            payload={"targetHistoryId": "history-1"},
            created_at=124.0,
        )

        self.assertEqual(curation_action_undo_state(record), "undo")


if __name__ == "__main__":
    unittest.main()
