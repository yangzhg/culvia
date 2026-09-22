from __future__ import annotations

import csv
import io
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from culvia.curation import save_photo_marks
from culvia.export_receipts import ExportReceiptBusyError, ExportReceiptStorageError, ExportReceiptStore
from culvia.export_service import ExportServiceError, export_selected_files_action


class ExportReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.cache = self.root / "scores.sqlite"
        self.destination = self.root / "delivery"
        self.store = ExportReceiptStore(self.root / "receipts.sqlite")
        self.source_snapshot = {"mode": "folders", "folders": [str(self.root / "photos")], "cachePath": str(self.cache)}

    def photos(self, count: int = 3) -> pd.DataFrame:
        directory = self.root / "photos"
        directory.mkdir(exist_ok=True)
        rows = []
        for index in range(count):
            source = directory / f"photo-{index:03}.jpg"
            source.write_bytes(f"complete photo {index}".encode())
            rows.append({"file_id": str(index), "path": str(source)})
        save_photo_marks(self.cache, [{"file_id": row["file_id"], "status": "pick"} for row in rows])
        return pd.DataFrame(rows)

    def run_export(self, frame: pd.DataFrame, **kwargs):
        return self.store.run_export(
            frame, self.cache, str(self.destination), source_snapshot=self.source_snapshot, **kwargs
        )

    def prime_schema(self) -> None:
        self.run_export(self.photos(1))
        self.store.clear()
        for path in self.destination.iterdir():
            path.unlink()

    def trigger(self, statement: str) -> None:
        with sqlite3.connect(self.store.path) as conn:
            conn.execute(statement)

    def test_constructor_and_absent_reads_do_not_create_storage(self) -> None:
        store = ExportReceiptStore(self.root / "absent" / "receipts.sqlite")
        self.assertIsNone(store.latest())
        self.assertIsNone(store.get("unknown"))
        self.assertIsNone(store.manifest_csv("unknown"))
        self.assertEqual(store.recover_interrupted(), 0)
        self.assertEqual(store.clear(), 0)
        self.assertFalse(store.path.parent.exists())

    def test_complete_manifest_survives_reopening_and_keeps_actual_collision_targets(self) -> None:
        frame = self.photos(27)
        Path(frame.iloc[-1]["path"]).unlink()
        self.destination.mkdir()
        occupied = self.destination / "photo-000.jpg"
        occupied.write_bytes(b"previous delivery")
        original_copy = shutil.copyfileobj

        def copy_with_one_failure(source, output, **kwargs):
            if Path(source.name).name == "photo-025.jpg":
                output.write(b"partial")
                raise OSError("destination unavailable")
            return original_copy(source, output, **kwargs)

        with patch("culvia.export_service.shutil.copyfileobj", side_effect=copy_with_one_failure):
            summary = self.run_export(frame)

        self.assertEqual((summary["status"], summary["ok"], summary["schemaVersion"]), ("completed", True, 1))
        self.assertEqual(
            (summary["total"], summary["processed"], summary["copied"], summary["skipped"]), (27, 27, 25, 2)
        )
        self.assertEqual((summary["previewCount"], summary["totalEntryCount"]), (20, 27))
        self.assertEqual(len(summary["copiedFiles"]), 20)
        self.assertEqual(summary["source"], self.source_snapshot)
        self.assertEqual(occupied.read_bytes(), b"previous delivery")
        self.assertFalse((self.destination / "photo-025.jpg").exists())

        reopened = ExportReceiptStore(self.store.path)
        self.assertEqual(reopened.latest(), summary)
        full = reopened.get(summary["operationId"])
        self.assertEqual(len(full["entries"]), 27)
        self.assertEqual([entry["index"] for entry in full["entries"]], list(range(27)))
        self.assertEqual(full["entries"][0]["source"], frame.iloc[0]["path"])
        self.assertEqual(full["entries"][0]["target"], str(self.destination / "photo-000-2.jpg"))
        self.assertEqual(full["entries"][-2]["status"], "copy_failed")
        self.assertEqual(full["entries"][-1]["status"], "missing")
        rows = list(csv.DictReader(io.StringIO(reopened.manifest_csv(summary["operationId"]).decode("utf-8-sig"))))
        self.assertEqual(len(rows), 27)
        self.assertEqual(rows[0]["operationId"], summary["operationId"])
        self.assertEqual(rows[0]["target"], full["entries"][0]["target"])
        self.assertEqual(rows[-1]["reason"], "missing")

    def test_live_receipt_commits_complete_roster_before_copy_and_each_result_afterwards(self) -> None:
        frame = self.photos()
        original_copy = shutil.copyfileobj
        snapshots = []

        def inspect_copy(source, output, **kwargs):
            reader = ExportReceiptStore(self.store.path)
            summary = reader.latest()
            receipt = reader.get(summary["operationId"])
            snapshots.append(receipt)
            current = receipt["entries"][int(Path(source.name).stem.split("-")[-1])]
            self.assertEqual(current["status"], "copying")
            self.assertEqual(current["target"], str(output.name))
            self.assertEqual(Path(output.name).read_bytes(), b"")
            return original_copy(source, output, **kwargs)

        with patch("culvia.export_service.shutil.copyfileobj", side_effect=inspect_copy):
            summary = self.run_export(frame)

        self.assertEqual(len(snapshots), 3)
        self.assertEqual([snapshot["copied"] for snapshot in snapshots], [0, 1, 2])
        self.assertEqual([entry["status"] for entry in snapshots[0]["entries"]], ["copying", "pending", "pending"])
        self.assertTrue(all(snapshot["totalEntryCount"] == 3 for snapshot in snapshots))
        self.assertEqual(len({snapshot["operationId"] for snapshot in snapshots}), 1)
        self.assertEqual(
            sorted(snapshot["revision"] for snapshot in snapshots), [snapshot["revision"] for snapshot in snapshots]
        )
        self.assertGreater(summary["revision"], snapshots[-1]["revision"])

    def test_result_commit_failure_stops_remaining_copies_and_marks_delivered_file_unconfirmed(self) -> None:
        self.prime_schema()
        frame = self.photos()
        self.trigger("""CREATE TRIGGER reject_second_result BEFORE UPDATE OF status ON export_receipt_files
            WHEN NEW.file_id = '1' AND NEW.status = 'copied'
            BEGIN SELECT RAISE(FAIL, 'receipt storage failure'); END""")

        with self.assertRaises(ExportReceiptStorageError) as failure:
            self.run_export(frame)

        summary = self.store.latest()
        self.assertEqual(summary["operationId"], failure.exception.operation_id)
        self.assertEqual(
            (summary["status"], summary["ok"], summary["copied"], summary["skipped"]), ("failed", False, 1, 0)
        )
        self.assertEqual((summary["unconfirmed"], summary["notAttempted"]), (1, 1))
        self.assertEqual(summary["errorCode"], "exportReceiptStorageFailed")
        self.assertEqual(summary["errorText"], {"key": "apiError.exportReceiptStorageFailed"})
        detail = self.store.get(summary["operationId"])
        self.assertEqual([item["status"] for item in detail["entries"]], ["copied", "unconfirmed", "not_attempted"])
        self.assertEqual((self.destination / "photo-001.jpg").read_bytes(), b"complete photo 1")
        self.assertFalse((self.destination / "photo-002.jpg").exists())
        self.assertEqual(self.store.recover_interrupted(), 0)

    def test_begin_and_target_commit_failures_do_not_copy_a_photo(self) -> None:
        for boundary in ("begin", "target"):
            with self.subTest(boundary=boundary):
                self.prime_schema()
                if boundary == "begin":
                    self.trigger("""CREATE TRIGGER reject_write BEFORE INSERT ON export_receipt_files
                        BEGIN SELECT RAISE(FAIL, 'receipt storage failure'); END""")
                else:
                    self.trigger("""CREATE TRIGGER reject_write BEFORE UPDATE OF target ON export_receipt_files
                        WHEN NEW.target IS NOT NULL
                        BEGIN SELECT RAISE(FAIL, 'receipt storage failure'); END""")
                with self.assertRaises(ExportReceiptStorageError):
                    self.run_export(self.photos())
                self.assertEqual(list(self.destination.iterdir()), [])
                if boundary == "begin":
                    self.assertIsNone(self.store.latest())
                else:
                    self.assertEqual(self.store.latest()["status"], "failed")
                    self.assertEqual(self.store.latest()["copied"], 0)
                self.trigger("DROP TRIGGER reject_write")

    def test_completion_commit_failure_cannot_report_success(self) -> None:
        self.prime_schema()
        self.trigger("""CREATE TRIGGER reject_completed BEFORE UPDATE OF status ON export_receipts
            WHEN NEW.status = 'completed' BEGIN SELECT RAISE(FAIL, 'receipt storage failure'); END""")
        with self.assertRaises(ExportReceiptStorageError):
            self.run_export(self.photos(2))
        summary = self.store.latest()
        self.assertEqual((summary["status"], summary["ok"], summary["copied"]), ("failed", False, 2))
        self.assertEqual(summary["unconfirmed"], 0)

    def test_failed_error_record_is_left_running_then_explicitly_recovered(self) -> None:
        self.prime_schema()
        self.trigger("""CREATE TRIGGER reject_updates BEFORE UPDATE OF status ON export_receipt_files
            WHEN OLD.target IS NOT NULL BEGIN SELECT RAISE(FAIL, 'receipt storage failure'); END""")
        with self.assertRaises(ExportReceiptStorageError):
            self.run_export(self.photos(2))
        summary = self.store.latest()
        self.assertEqual(summary["status"], "running")
        self.trigger("DROP TRIGGER reject_updates")
        self.assertEqual(self.store.recover_interrupted(), 1)
        recovered = self.store.latest()
        self.assertEqual(
            (recovered["status"], recovered["copied"], recovered["unconfirmed"], recovered["notAttempted"]),
            ("interrupted", 0, 1, 1),
        )
        self.assertEqual(recovered["errorText"], {"key": "apiError.exportInterrupted"})
        self.assertEqual(self.store.recover_interrupted(), 0)
        self.assertEqual((self.destination / "photo-000.jpg").read_bytes(), b"complete photo 0")
        self.assertFalse((self.destination / "photo-001.jpg").exists())

    def test_validation_stays_compatible_and_missing_observer_cannot_report_success(self) -> None:
        frame = self.photos()
        with self.assertRaises(ExportServiceError) as invalid:
            self.store.run_export(frame, self.cache, "", source_snapshot=self.source_snapshot)
        self.assertEqual(invalid.exception.error_code, "exportDestinationRequired")
        self.assertIsNone(self.store.latest())
        self.assertFalse(self.destination.exists())
        with self.assertRaises(ExportReceiptStorageError):
            self.run_export(frame, copy_action=lambda *_args, **_kwargs: None)
        self.assertIsNone(self.store.latest())

    def test_new_explicit_export_recovers_abandoned_work_before_starting(self) -> None:
        frame = self.photos(2)
        with patch("culvia.export_service.shutil.copyfileobj", side_effect=SystemExit("worker ended")):
            with self.assertRaises(SystemExit):
                self.run_export(frame)
        abandoned = self.store.latest()
        self.assertEqual(abandoned["status"], "running")
        new_receipt = self.run_export(frame)
        previous = self.store.get(abandoned["operationId"])
        self.assertEqual(previous["status"], "interrupted")
        self.assertEqual((previous["unconfirmed"], previous["notAttempted"]), (1, 1))
        self.assertEqual(new_receipt["status"], "completed")
        self.assertNotEqual(new_receipt["operationId"], abandoned["operationId"])
        self.assertGreater(new_receipt["sequence"], abandoned["sequence"])

    def test_receipt_path_cannot_alias_the_score_database(self) -> None:
        frame = self.photos(1)
        original = self.cache.read_bytes()
        store = ExportReceiptStore(self.cache)
        with self.assertRaises(ExportServiceError) as conflict:
            store.run_export(frame, self.cache, str(self.destination), source_snapshot=self.source_snapshot)
        self.assertEqual(conflict.exception.error_code, "exportReceiptPathConflict")
        self.assertEqual(self.cache.read_bytes(), original)
        self.assertFalse(self.destination.exists())
        alias = self.root / "score-alias.sqlite"
        try:
            alias.symlink_to(self.cache)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Symbolic links unavailable: {exc}")
        with self.assertRaises(ExportServiceError) as aliased:
            ExportReceiptStore(alias).run_export(
                frame, self.cache, str(self.destination), source_snapshot=self.source_snapshot
            )
        self.assertEqual(aliased.exception.error_code, "exportReceiptPathConflict")
        self.assertEqual(self.cache.read_bytes(), original)

    def test_clear_removes_only_receipts_and_keeps_operation_sequence_increasing(self) -> None:
        frame = self.photos(1)
        first = self.run_export(frame)
        second = self.run_export(frame)
        self.assertNotEqual(first["operationId"], second["operationId"])
        self.assertGreater(second["sequence"], first["sequence"])
        self.assertEqual(self.store.clear(), 2)
        self.assertIsNone(self.store.latest())
        self.assertIsNone(self.store.get(first["operationId"]))
        self.assertNotIn(str(self.destination).encode(), self.store.path.read_bytes())
        self.assertNotIn(str(self.root / "photos").encode(), self.store.path.read_bytes())
        self.assertTrue(self.store.lock_path.exists())
        self.assertEqual((self.destination / "photo-000.jpg").read_bytes(), b"complete photo 0")
        self.assertEqual((self.destination / "photo-000-2.jpg").read_bytes(), b"complete photo 0")
        third = self.run_export(frame)
        self.assertGreater(third["sequence"], second["sequence"])
        with sqlite3.connect(self.store.path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM export_receipt_files").fetchone()[0], 1)

    def test_stable_alias_paths_and_csv_escaping_preserve_full_json_facts(self) -> None:
        frame = self.photos(1)
        alias = self.root / "photo-alias"
        try:
            alias.symlink_to(self.root / "photos", target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Symbolic links unavailable: {exc}")
        frame["path"] = str(alias / "photo-000.jpg")
        frame["file_id"] = '=unsafe,"spreadsheet"\nvalue'
        save_photo_marks(self.cache, [{"file_id": frame.iloc[0]["file_id"], "status": "pick"}])
        receipt = self.run_export(frame)
        detail = self.store.get(receipt["operationId"])
        self.assertEqual(detail["entries"][0]["source"], frame.iloc[0]["path"])
        self.assertEqual(detail["entries"][0]["fileId"], frame.iloc[0]["file_id"])
        rows = list(csv.DictReader(io.StringIO(self.store.manifest_csv(receipt["operationId"]).decode("utf-8-sig"))))
        self.assertEqual(rows[0]["source"], frame.iloc[0]["path"])
        self.assertEqual(rows[0]["fileId"], "'" + frame.iloc[0]["file_id"])

    def test_unreadable_receipt_is_an_explicit_error_not_an_empty_result(self) -> None:
        self.store.path.write_bytes(b"not a SQLite database")
        for read in (self.store.latest, lambda: self.store.get("known"), lambda: self.store.manifest_csv("known")):
            with self.subTest(read=read), self.assertRaises(ExportReceiptStorageError):
                read()

    def test_incomplete_schema_is_an_explicit_storage_error(self) -> None:
        receipt = self.run_export(self.photos(1))
        self.trigger("ALTER TABLE export_receipts DROP COLUMN source_json")
        for read in (
            self.store.latest,
            lambda: self.store.get(receipt["operationId"]),
            lambda: self.store.manifest_csv(receipt["operationId"]),
        ):
            with self.subTest(read=read), self.assertRaises(ExportReceiptStorageError):
                read()

    def test_unavailable_parent_is_an_explicit_storage_error_for_reads_and_maintenance(self) -> None:
        with patch.object(Path, "stat", side_effect=PermissionError("parent unavailable")):
            for operation in (
                self.store.latest,
                lambda: self.store.get("known"),
                lambda: self.store.manifest_csv("known"),
                self.store.recover_interrupted,
                self.store.clear,
            ):
                with self.subTest(operation=operation), self.assertRaises(ExportReceiptStorageError):
                    operation()

    def test_live_other_process_prevents_recovery_clear_and_duplicate_execution(self) -> None:
        frame = self.photos(2)
        process, ready = self.start_blocked_process()
        try:
            self.wait_for_worker(process, ready)
            running = self.store.latest()
            self.assertEqual(running["status"], "running")
            self.assertEqual(self.store.recover_interrupted(), 0)
            with self.assertRaises(ExportReceiptBusyError):
                self.store.clear()
            with self.assertRaises(ExportReceiptBusyError):
                self.run_export(frame)
            process.communicate("continue\n", timeout=15)
            self.assertEqual(process.returncode, 0)
            completed = self.store.latest()
            self.assertEqual(
                (completed["operationId"], completed["status"], completed["copied"]),
                (running["operationId"], "completed", 2),
            )
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)

    def test_process_exit_releases_lock_and_recovers_uncertain_copy_without_recopying(self) -> None:
        self.photos(2)
        process, ready = self.start_blocked_process()
        try:
            self.wait_for_worker(process, ready)
            original = self.store.latest()
            process.kill()
            process.communicate(timeout=10)
            self.assertEqual(self.store.recover_interrupted(), 1)
            recovered = self.store.latest()
            self.assertEqual((recovered["operationId"], recovered["status"]), (original["operationId"], "interrupted"))
            self.assertEqual((recovered["copied"], recovered["unconfirmed"], recovered["notAttempted"]), (0, 1, 1))
            self.assertEqual((self.destination / "photo-000.jpg").read_bytes(), b"partial")
            self.assertFalse((self.destination / "photo-001.jpg").exists())
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)

    def test_database_file_alias_uses_the_live_workers_execution_lock(self) -> None:
        frame = self.photos(2)
        alias = self.root / "receipt-alias.sqlite"
        try:
            alias.symlink_to(self.store.path)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Symbolic links unavailable: {exc}")
        aliased = ExportReceiptStore(alias)
        process, ready = self.start_blocked_process()
        try:
            self.wait_for_worker(process, ready)
            before = self.store.latest()
            self.assertEqual(aliased.latest(), before)
            self.assertEqual(aliased.recover_interrupted(), 0)
            with self.assertRaises(ExportReceiptBusyError):
                aliased.clear()
            with self.assertRaises(ExportReceiptBusyError):
                aliased.run_export(frame, self.cache, str(self.destination), source_snapshot=self.source_snapshot)
            self.assertEqual(self.store.latest(), before)
            process.communicate("continue\n", timeout=15)
            self.assertEqual(process.returncode, 0)
            self.assertEqual(aliased.latest()["status"], "completed")
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)

    def start_blocked_process(self):
        ready = self.root / "worker-ready"
        script = textwrap.dedent("""
            import shutil
            import sys
            from pathlib import Path
            from unittest.mock import patch
            import pandas as pd
            from culvia.export_receipts import ExportReceiptStore
            root = Path(sys.argv[1])
            sources = pd.DataFrame([
                {"file_id": str(i), "path": str(root / "photos" / f"photo-{i:03}.jpg")}
                for i in range(2)
            ])
            original_copy = shutil.copyfileobj
            def blocked_copy(source, output, **kwargs):
                if source.name.endswith("photo-000.jpg"):
                    output.write(b"partial")
                    output.flush()
                    (root / "worker-ready").write_text("ready", encoding="utf-8")
                    sys.stdin.readline()
                    output.seek(0)
                    output.truncate()
                return original_copy(source, output, **kwargs)
            with patch("culvia.export_service.shutil.copyfileobj", side_effect=blocked_copy):
                ExportReceiptStore(root / "receipts.sqlite").run_export(
                    sources, root / "scores.sqlite", str(root / "delivery"),
                    source_snapshot={"mode": "folders", "folders": [str(root / "photos")]},
                )
        """)
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        process = subprocess.Popen(
            [sys.executable, "-c", script, str(self.root)],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return process, ready

    def wait_for_worker(self, process, ready: Path) -> None:
        deadline = time.monotonic() + 15
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        if not ready.exists():
            process.kill()
            stdout, stderr = process.communicate(timeout=10)
            self.fail(f"Worker did not reach copying: {stdout} {stderr}")


if __name__ == "__main__":
    unittest.main()
