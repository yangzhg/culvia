from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from culvia.curation import PhotoMark
from culvia.curation import save_photo_mark
from culvia.export_service import (
    EXPORT_PAYLOAD_VERSION,
    ExportServiceError,
    copy_selected_photo_files,
    destination_write_issue,
    export_preflight_action,
    export_selected_files_action,
    export_csv_bytes,
    filtered_export_csv_action,
    preflight_selected_export,
    selected_curation_dataframe,
    selected_export_context,
    selected_export_csv_action,
    selected_export_csv_bytes,
    unique_destination_path,
)


class ExportServiceTests(unittest.TestCase):
    def test_filtered_export_csv_action_uses_display_context_and_marks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = str(Path(temp_dir) / "scores.sqlite")
            source_df = pd.DataFrame(
                [
                    {"file_id": "a", "path": "/a.jpg", "filename": "a.jpg"},
                    {"file_id": "b", "path": "/b.jpg", "filename": "b.jpg"},
                ]
            )
            save_photo_mark(cache_path, "a", rating=5, status="pick")

            def dataframe_builder(source: pd.DataFrame, filters: dict[str, object], marks: dict[str, PhotoMark]):
                filtered = source[source["file_id"].eq("a")].copy() if filters.get("only") == "a" else source.copy()
                return source.copy(), filtered, source.iloc[0:0].copy()

            csv_text = filtered_export_csv_action(
                source_df,
                {"only": "a"},
                cache_path,
                dataframe_builder,
                normalize_dataframe=lambda df: df.copy(),
            ).decode("utf-8-sig")

            self.assertIn("manual_status_label", csv_text)
            self.assertIn("入选", csv_text)
            self.assertIn("a.jpg", csv_text)
            self.assertNotIn("b.jpg", csv_text)

    def test_selected_export_csv_action_loads_marks_from_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = str(Path(temp_dir) / "scores.sqlite")
            source_df = pd.DataFrame(
                [
                    {"file_id": "a", "path": "/a.jpg", "filename": "a.jpg"},
                    {"file_id": "b", "path": "/b.jpg", "filename": "b.jpg"},
                    {"file_id": "c", "path": "/c.jpg", "filename": "c.jpg"},
                ]
            )
            save_photo_mark(cache_path, "b", rating=5, status="pick")
            save_photo_mark(cache_path, "c", rating=4, status="hold")
            save_photo_mark(cache_path, "outside-source", rating=5, status="pick")

            context = selected_export_context(source_df, cache_path)
            csv_text = selected_export_csv_action(
                source_df, cache_path, normalize_dataframe=lambda df: df.copy()
            ).decode("utf-8-sig")

            self.assertEqual(context.selected_df["file_id"].tolist(), ["b"])
            self.assertNotIn("outside-source", context.marks)
            self.assertIn("b.jpg", csv_text)
            self.assertNotIn("a.jpg", csv_text)
            self.assertNotIn("c.jpg", csv_text)

    def test_selected_dataframe_and_csv_use_pick_marks(self) -> None:
        source_df = pd.DataFrame(
            [
                {"file_id": "a", "path": "/a.jpg", "filename": "a.jpg"},
                {"file_id": "b", "path": "/b.jpg", "filename": "b.jpg"},
            ]
        )
        marks = {
            "a": PhotoMark(file_id="a", rating=5, status="pick"),
            "b": PhotoMark(file_id="b", rating=1, status="reject"),
        }

        selected = selected_curation_dataframe(source_df, marks)
        csv_text = selected_export_csv_bytes(source_df, marks, normalize_dataframe=lambda df: df.copy()).decode(
            "utf-8-sig"
        )

        self.assertEqual(selected["file_id"].tolist(), ["a"])
        self.assertIn("manual_status_label", csv_text)
        self.assertIn("入选", csv_text)
        self.assertNotIn("b.jpg", csv_text)

    def test_export_csv_bytes_adds_curation_columns(self) -> None:
        source_df = pd.DataFrame([{"file_id": "a", "path": "/a.jpg"}])
        marks = {"a": PhotoMark(file_id="a", rating=4, color_label="green")}

        csv_text = export_csv_bytes(source_df, marks, normalize_dataframe=lambda df: df.copy()).decode("utf-8-sig")

        self.assertIn("manual_rating", csv_text)
        self.assertIn("绿色", csv_text)

    def test_unique_destination_path_avoids_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir)
            (destination / "photo.jpg").write_bytes(b"existing")

            self.assertEqual(unique_destination_path(destination, "photo.jpg"), destination / "photo-2.jpg")
            self.assertEqual(
                unique_destination_path(destination, "fresh.jpg", reserved_names={"fresh.jpg"}),
                destination / "fresh-2.jpg",
            )

    def test_preflight_selected_export_reports_missing_and_renamed_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_a = root / "a" / "photo.jpg"
            source_b = root / "b" / "photo.jpg"
            source_a.parent.mkdir()
            source_b.parent.mkdir()
            source_a.write_bytes(b"a")
            source_b.write_bytes(b"b")
            destination = root / "export"
            destination.mkdir()
            (destination / "photo.jpg").write_bytes(b"existing")
            selected_df = pd.DataFrame(
                [
                    {"file_id": "a", "path": str(source_a)},
                    {"file_id": "b", "path": str(source_b)},
                    {"file_id": "missing", "path": str(root / "missing.jpg")},
                ]
            )

            result = preflight_selected_export(selected_df, destination)
            payload = result.to_payload()

            self.assertEqual(result.total, 3)
            self.assertEqual(result.ready, 2)
            self.assertEqual(result.missing, 1)
            self.assertEqual(result.renamed, 2)
            self.assertEqual([path.name for path in result.ready_paths], ["photo-2.jpg", "photo-3.jpg"])
            self.assertEqual(payload["schemaVersion"], EXPORT_PAYLOAD_VERSION)
            self.assertTrue(payload["destinationWritable"])
            self.assertEqual(payload["destinationIssue"], "")
            self.assertEqual(payload["missing"], 1)
            self.assertEqual(len(payload["renamedFiles"]), 2)

    def test_preflight_selected_export_reports_destination_issue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "photo.jpg"
            source.write_bytes(b"photo")
            selected_df = pd.DataFrame([{"file_id": "a", "path": str(source)}])

            result = preflight_selected_export(
                selected_df,
                root / "export",
                destination_issue="导出目录不可写：权限不足",
            )
            payload = result.to_payload()

            self.assertFalse(payload["destinationWritable"])
            self.assertEqual(payload["schemaVersion"], EXPORT_PAYLOAD_VERSION)
            self.assertEqual(payload["destinationIssue"], "导出目录不可写：权限不足")
            self.assertEqual(payload["ready"], 1)

    def test_export_preflight_action_validates_destination_and_uses_selected_marks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_path = str(root / "scores.sqlite")
            source = root / "photo.jpg"
            source.write_bytes(b"photo")
            destination = root / "export"
            destination.mkdir()
            source_df = pd.DataFrame(
                [
                    {"file_id": "a", "path": str(source)},
                    {"file_id": "b", "path": str(root / "not-picked.jpg")},
                ]
            )
            save_photo_mark(cache_path, "a", status="pick")

            result = export_preflight_action(source_df, cache_path, str(destination))

            self.assertEqual(result.total, 1)
            self.assertEqual(result.ready, 1)
            self.assertEqual(result.missing, 0)

            with self.assertRaises(ExportServiceError) as missing:
                export_preflight_action(source_df, cache_path, "")
            self.assertEqual(missing.exception.error_code, "exportDestinationRequired")

            with self.assertRaises(ExportServiceError) as unavailable:
                export_preflight_action(source_df, cache_path, str(root / "missing-dir"))
            self.assertEqual(unavailable.exception.error_code, "exportDestinationUnavailable")
            self.assertEqual(unavailable.exception.params["path"], str(root / "missing-dir"))

    def test_destination_write_issue_reports_file_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination_file = Path(temp_dir) / "not-a-directory"
            destination_file.write_text("file", encoding="utf-8")

            self.assertIn("导出目录不可写", destination_write_issue(destination_file))

    def test_copy_selected_photo_files_reports_copied_and_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "photo.jpg"
            source.write_bytes(b"photo")
            destination = root / "export"
            destination.mkdir()
            selected_df = pd.DataFrame(
                [
                    {"file_id": "a", "path": str(source)},
                    {"file_id": "missing", "path": str(root / "missing.jpg")},
                ]
            )

            result = copy_selected_photo_files(selected_df, destination)
            payload = result.to_payload()

            self.assertEqual(result.copied, 1)
            self.assertEqual(result.skipped, 1)
            self.assertEqual(payload["schemaVersion"], EXPORT_PAYLOAD_VERSION)
            self.assertEqual(payload["copied"], 1)
            self.assertEqual(payload["skipped"], 1)
            self.assertEqual(payload["copiedFiles"], [str(destination / "photo.jpg")])
            self.assertNotIn("files", payload)
            self.assertNotIn("skippedFiles", payload)
            self.assertEqual(payload["skippedDetails"][0]["path"], str(root / "missing.jpg"))
            self.assertEqual(payload["skippedDetails"][0]["reason"], "missing")
            self.assertEqual(payload["skippedDetails"][0]["label"], "源文件缺失")
            self.assertEqual(
                payload["skippedReasonSummary"], [{"reason": "missing", "label": "源文件缺失", "count": 1}]
            )
            self.assertTrue((destination / "photo.jpg").exists())

    def test_copy_selected_photo_files_reports_copy_failure_reason(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "photo.jpg"
            source.write_bytes(b"photo")
            destination = root / "export"
            destination.mkdir()
            selected_df = pd.DataFrame([{"file_id": "a", "path": str(source)}])

            with patch("culvia.export_service.shutil.copy2", side_effect=OSError("permission denied")):
                payload = copy_selected_photo_files(selected_df, destination).to_payload()

            self.assertEqual(payload["copied"], 0)
            self.assertEqual(payload["schemaVersion"], EXPORT_PAYLOAD_VERSION)
            self.assertEqual(payload["skipped"], 1)
            self.assertEqual(payload["skippedDetails"][0]["reason"], "copy_failed")
            self.assertEqual(payload["skippedDetails"][0]["label"], "复制失败")
            self.assertIn("permission denied", payload["skippedDetails"][0]["message"])
            self.assertEqual(
                payload["skippedReasonSummary"],
                [{"reason": "copy_failed", "label": "复制失败", "count": 1}],
            )

    def test_export_selected_files_action_creates_destination_and_rejects_empty_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_path = str(root / "scores.sqlite")
            source = root / "photo.jpg"
            source.write_bytes(b"photo")
            source_df = pd.DataFrame([{"file_id": "a", "path": str(source)}])
            destination = root / "nested" / "export"
            save_photo_mark(cache_path, "a", status="pick")

            result = export_selected_files_action(source_df, cache_path, str(destination))

            self.assertEqual(result.copied, 1)
            self.assertTrue((destination / "photo.jpg").exists())

            save_photo_mark(cache_path, "a", status="reject")
            with self.assertRaises(ExportServiceError) as no_picks:
                export_selected_files_action(source_df, cache_path, str(destination))
            self.assertEqual(no_picks.exception.error_code, "exportNoPicks")

            with self.assertRaises(ExportServiceError) as missing_destination:
                export_selected_files_action(source_df, cache_path, "")
            self.assertEqual(missing_destination.exception.error_code, "exportDestinationRequired")

    def test_export_actions_share_duplicate_basename_target_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_path = str(root / "scores.sqlite")
            source_a = root / "a" / "photo.jpg"
            source_b = root / "b" / "photo.jpg"
            source_a.parent.mkdir()
            source_b.parent.mkdir()
            source_a.write_bytes(b"a")
            source_b.write_bytes(b"b")
            destination = root / "export"
            destination.mkdir()
            (destination / "photo.jpg").write_bytes(b"existing")
            source_df = pd.DataFrame(
                [
                    {"file_id": "a", "path": str(source_a)},
                    {"file_id": "b", "path": str(source_b)},
                ]
            )
            save_photo_mark(cache_path, "a", status="pick")
            save_photo_mark(cache_path, "b", status="pick")

            preflight = export_preflight_action(source_df, cache_path, str(destination))
            copied = export_selected_files_action(source_df, cache_path, str(destination))

            self.assertEqual([target.name for target in preflight.ready_paths], ["photo-2.jpg", "photo-3.jpg"])
            self.assertEqual([target.name for target in copied.copied_paths], ["photo-2.jpg", "photo-3.jpg"])
            self.assertEqual(preflight.total, copied.copied)


if __name__ == "__main__":
    unittest.main()
