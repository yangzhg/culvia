from __future__ import annotations

import unittest

import pandas as pd

from culvia.curation_targets import frame_file_id_set, frame_file_ids, resolve_mark_targets


class CurationTargetTests(unittest.TestCase):
    def test_frame_file_ids_are_route_safe_strings(self) -> None:
        frame = pd.DataFrame({"file_id": ["a", 2, None, ""]})

        self.assertEqual(frame_file_ids(frame), ["a", "2", ""])
        self.assertEqual(frame_file_id_set(frame), {"a", "2", ""})
        self.assertEqual(frame_file_ids(pd.DataFrame({"path": ["a.jpg"]})), [])

    def test_resolves_current_filtered_and_selected_targets(self) -> None:
        working = pd.DataFrame({"file_id": ["a", "b", "c"]})
        filtered = pd.DataFrame({"file_id": ["a", "b"]})

        current = resolve_mark_targets({"fileId": "b"}, working, filtered)
        self.assertTrue(current.ok)
        self.assertEqual(current.scope, "current")
        self.assertEqual(current.target_ids, ["b"])

        filtered_result = resolve_mark_targets({"scope": "filtered"}, working, filtered)
        self.assertTrue(filtered_result.ok)
        self.assertEqual(filtered_result.target_ids, ["a", "b"])

        selected = resolve_mark_targets({"scope": "selected", "fileIds": ["c", "missing", "b"]}, working, filtered)
        self.assertTrue(selected.ok)
        self.assertEqual(selected.scope, "selected")
        self.assertEqual(selected.target_ids, ["c", "b"])

    def test_returns_route_friendly_errors(self) -> None:
        working = pd.DataFrame({"file_id": ["a"]})
        filtered = pd.DataFrame({"file_id": ["a"]})

        missing_current = resolve_mark_targets({}, working, filtered)
        self.assertFalse(missing_current.ok)
        self.assertEqual(missing_current.error_message, "缺少照片标识。")
        self.assertEqual(missing_current.status_code, 400)
        self.assertEqual(missing_current.error_code, "photoIdMissing")

        unknown_current = resolve_mark_targets({"fileId": "missing"}, working, filtered)
        self.assertFalse(unknown_current.ok)
        self.assertEqual(unknown_current.error_message, "没有找到这张照片。")
        self.assertEqual(unknown_current.status_code, 404)
        self.assertEqual(unknown_current.error_code, "photoNotFound")

        empty_selected = resolve_mark_targets({"scope": "selected", "fileIds": ["missing"]}, working, filtered)
        self.assertFalse(empty_selected.ok)
        self.assertEqual(empty_selected.error_message, "缺少已选照片。")
        self.assertEqual(empty_selected.status_code, 400)
        self.assertEqual(empty_selected.error_code, "selectedPhotosMissing")


if __name__ == "__main__":
    unittest.main()
