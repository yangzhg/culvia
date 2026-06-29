from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from culvia import curation


class CurationModuleTests(unittest.TestCase):
    def test_package_entrypoint_roundtrips_marks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"

            saved = curation.save_photo_mark(
                cache_path,
                "photo-1",
                rating=4,
                status="pick",
                color_label="green",
                source="model",
                accepted_score=8.3,
            )
            loaded = curation.load_photo_marks(cache_path, ["photo-1"])

        self.assertEqual(saved.rating, 4)
        self.assertEqual(loaded["photo-1"].status, "pick")
        self.assertEqual(loaded["photo-1"].color_label, "green")
        self.assertAlmostEqual(loaded["photo-1"].accepted_score or 0, 8.3)

    def test_package_export_dataframe_adds_external_tool_columns(self) -> None:
        source = pd.DataFrame(
            [
                {
                    "file_id": "photo-1",
                    "path": "/photos/a.jpg",
                    "folder": "/photos",
                    "filename": "a.jpg",
                    "error": "",
                    "overall_0_10": 8.0,
                },
                {
                    "file_id": "photo-2",
                    "path": "/photos/b.jpg",
                    "folder": "/photos",
                    "filename": "b.jpg",
                    "error": "",
                    "overall_0_10": 6.0,
                },
            ]
        )
        marks = {
            "photo-1": curation.PhotoMark(
                "photo-1",
                rating=5,
                status="pick",
                color_label="purple",
                source="llm_batch",
                accepted_score=8.7,
            )
        }

        exported = curation.curation_export_dataframe(source, marks, normalize_dataframe=lambda df: df.copy())

        self.assertEqual(exported.loc[0, "manual_rating"], 5)
        self.assertEqual(exported.loc[0, "manual_status_label"], "入选")
        self.assertEqual(exported.loc[0, "lightroom_flag"], "Pick")
        self.assertEqual(exported.loc[0, "lightroom_color_label"], "Purple")
        self.assertEqual(exported.loc[0, "capture_one_color_tag"], "Purple")
        self.assertEqual(exported.loc[0, "manual_source"], "批量大模型")
        self.assertAlmostEqual(exported.loc[0, "accepted_score_0_10"], 8.7)
        self.assertEqual(exported.loc[1, "manual_rating"], 0)
        self.assertEqual(exported.loc[1, "manual_status_label"], "未判断")

    def test_hold_status_is_a_persisted_pending_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"

            saved = curation.save_photo_mark(cache_path, "photo-1", status="hold")
            loaded = curation.load_photo_marks(cache_path, ["photo-1"])["photo-1"]

        self.assertEqual(saved.status, "hold")
        self.assertEqual(loaded.status, "hold")
        self.assertEqual(curation.manual_status_label("hold"), "待定")
        self.assertEqual(curation.manual_status_label(""), "未判断")
        self.assertEqual(curation.export_flag_label("hold"), "Unflagged")


if __name__ == "__main__":
    unittest.main()
