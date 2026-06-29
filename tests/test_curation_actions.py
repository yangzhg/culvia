from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from culvia.curation import PhotoMark, load_photo_marks, save_photo_mark
from culvia.curation_actions import (
    apply_color_label_to_marks,
    apply_mark_mutation_history_payload,
    apply_status_to_marks,
    mark_snapshot_payload,
    mark_snapshot_payloads,
    restore_photo_marks_from_payload,
)


class CurationActionTests(unittest.TestCase):
    def test_mark_snapshot_payload_preserves_restore_shape(self) -> None:
        empty = mark_snapshot_payload("photo-1", None)
        self.assertEqual(empty["fileId"], "photo-1")
        self.assertEqual(empty["status"], "")
        self.assertEqual(empty["colorLabel"], "")
        self.assertIsNone(empty["acceptedScore"])

        mark = PhotoMark(
            "photo-2",
            rating=5,
            status="pick",
            color_label="purple",
            note="keeper",
            source="llm_batch",
            accepted_score=8.6,
        )
        payload = mark_snapshot_payload("photo-2", mark)
        self.assertEqual(payload["fileId"], "photo-2")
        self.assertEqual(payload["rating"], 5)
        self.assertEqual(payload["status"], "pick")
        self.assertEqual(payload["colorLabel"], "purple")
        self.assertEqual(payload["source"], "llm_batch")
        self.assertAlmostEqual(float(payload["acceptedScore"] or 0), 8.6)

    def test_mark_snapshot_payloads_keep_target_order(self) -> None:
        marks = {"b": PhotoMark("b", status="reject")}

        payloads = mark_snapshot_payloads(["a", "b"], marks)

        self.assertEqual([payload["fileId"] for payload in payloads], ["a", "b"])
        self.assertEqual(payloads[0]["status"], "")
        self.assertEqual(payloads[1]["status"], "reject")

    def test_apply_color_label_preserves_existing_manual_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            save_photo_mark(cache_path, "photo-1", rating=5, status="pick", accepted_score=8.8)

            saved = apply_color_label_to_marks(cache_path, ["photo-1", "photo-2"], "Blue")
            marks = load_photo_marks(cache_path, ["photo-1", "photo-2"])

        self.assertEqual(saved, 2)
        self.assertEqual(marks["photo-1"].rating, 5)
        self.assertEqual(marks["photo-1"].status, "pick")
        self.assertEqual(marks["photo-1"].color_label, "blue")
        self.assertAlmostEqual(float(marks["photo-1"].accepted_score or 0), 8.8)
        self.assertEqual(marks["photo-2"].color_label, "blue")

    def test_apply_status_clears_accepted_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            save_photo_mark(cache_path, "photo-1", rating=5, status="pick", color_label="green", accepted_score=8.8)

            saved = apply_status_to_marks(cache_path, ["photo-1"], "reject")
            mark = load_photo_marks(cache_path, ["photo-1"])["photo-1"]

        self.assertEqual(saved, 1)
        self.assertEqual(mark.rating, 5)
        self.assertEqual(mark.status, "reject")
        self.assertEqual(mark.color_label, "green")
        self.assertIsNone(mark.accepted_score)

    def test_apply_mark_mutation_history_payload_records_before_and_after(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            save_photo_mark(cache_path, "photo-1", rating=5, status="pick")

            action, saved = apply_mark_mutation_history_payload(
                cache_path,
                ["photo-1"],
                lambda: apply_status_to_marks(cache_path, ["photo-1"], "reject"),
                lambda saved: {"marked": saved},
            )

        self.assertEqual(saved, 1)
        self.assertEqual(action["marked"], 1)
        self.assertEqual(action["beforeMarks"][0]["status"], "pick")
        self.assertEqual(action["afterMarks"][0]["status"], "reject")
        self.assertNotIn("previousMarks", action)

    def test_restore_photo_marks_from_payload_filters_and_clears_empty_marks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            save_photo_mark(cache_path, "photo-1", rating=5, status="pick", color_label="green", accepted_score=8.8)

            restored = restore_photo_marks_from_payload(
                cache_path,
                [
                    {
                        "fileId": "photo-1",
                        "rating": 0,
                        "status": "",
                        "colorLabel": "",
                        "note": "",
                        "source": "manual",
                        "acceptedScore": None,
                    },
                    {
                        "file_id": "photo-2",
                        "rating": 4,
                        "status": "pick",
                        "color_label": "red",
                        "source": "model_batch",
                        "accepted_score": 7.7,
                    },
                    {"fileId": "missing", "status": "pick"},
                    "not-a-mark",
                ],
                {"photo-1", "photo-2"},
            )
            marks = load_photo_marks(cache_path, ["photo-1", "photo-2", "missing"])

        self.assertEqual(restored, 2)
        self.assertNotIn("photo-1", marks)
        self.assertEqual(marks["photo-2"].rating, 4)
        self.assertEqual(marks["photo-2"].status, "pick")
        self.assertEqual(marks["photo-2"].color_label, "red")
        self.assertAlmostEqual(float(marks["photo-2"].accepted_score or 0), 7.7)
        self.assertNotIn("missing", marks)


if __name__ == "__main__":
    unittest.main()
