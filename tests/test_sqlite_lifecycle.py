from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from culvia import curation, curation_history
from culvia.cache_records import ScoreCacheStore
from culvia.insight_store import AnalysisInsight, AnalysisInsightStore, AppConfigStore
from tools.prepare_runtime_fixture import write_fixture


@contextmanager
def recorded_connections(factory=sqlite3.Connection):
    connect = sqlite3.connect
    connections: list[sqlite3.Connection] = []

    def record(*args, **kwargs):
        connection = connect(*args, **{**kwargs, "factory": factory})
        connections.append(connection)
        return connection

    with patch("sqlite3.connect", new=record):
        try:
            yield connections
        finally:
            for connection in connections:
                connection.close()


class SqliteLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path = self.root / "scores.sqlite"
        self.scores = ScoreCacheStore(
            csv_columns=("file_id", "path", "error", "recommendation_0_10"),
            text_columns=frozenset({"file_id", "path", "error"}),
            field_groups=(),
            recommendation_column="recommendation_0_10",
        )
        self.insights = AnalysisInsightStore(schema_ensurer=self.scores.ensure_schema)
        self.config = AppConfigStore(
            schema_ensurer=self.scores.ensure_schema,
            clean_config=lambda config: {str(key): str(value).strip() for key, value in (config or {}).items()},
        )

    def assert_connections_closed(self, connections: list[sqlite3.Connection]) -> None:
        self.assertTrue(connections, "the operation must exercise a real SQLite connection")
        for connection in connections:
            with self.assertRaisesRegex(sqlite3.ProgrammingError, "closed"):
                _ = connection.in_transaction

    def insight(self, *, summary: str = "saved") -> AnalysisInsight:
        return AnalysisInsight(
            file_id="photo-1",
            analyzer_key="review",
            provider="unit",
            model="test-model",
            model_version="v1",
            prompt_version="v1",
            summary=summary,
            created_at=1.0,
        )

    def rows(self, *values: tuple[str, float]) -> pd.DataFrame:
        return pd.DataFrame([{"file_id": file_id, "recommendation_0_10": score} for file_id, score in values])

    def install_trigger(self, table: str, predicate: str) -> None:
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                f"CREATE TRIGGER fail_write BEFORE INSERT ON {table} WHEN {predicate} "
                "BEGIN SELECT RAISE(ABORT, 'write failed'); END"
            )

    def test_operations_close_connections_and_keep_committed_results(self) -> None:
        operations = (
            ("save scores", lambda: self.scores.save(self.rows(("photo-1", 6.0)), self.path)),
            ("upsert scores", lambda: self.scores.upsert(self.rows(("photo-1", 8.0)), self.path)),
            ("load scores", lambda: self.scores.load(self.path)),
            ("save insights", lambda: self.insights.save([self.insight()], self.path)),
            ("load insights", lambda: self.insights.load(self.path)),
            ("load selected insights", lambda: self.insights.load(self.path, ["photo-1"])),
            ("load empty insight selection", lambda: self.insights.load(self.path, [])),
            (
                "match insights",
                lambda: self.insights.latest_matching_results(
                    self.path,
                    file_ids=["photo-1"],
                    analyzer_key="review",
                    provider="unit",
                    model="test-model",
                    model_version="v1",
                    prompt_version="v1",
                ),
            ),
            ("save configuration", lambda: self.config.save({"model": "test-model"}, self.path)),
            ("load configuration", lambda: self.config.load(self.path)),
            ("ensure marks", lambda: curation.ensure_curation_schema(self.path)),
            ("save mark", lambda: curation.save_photo_mark(self.path, "photo-1", rating=4, status="pick")),
            ("load all marks", lambda: curation.load_photo_marks(self.path)),
            ("load selected marks", lambda: curation.load_photo_marks(self.path, ["photo-1"])),
            ("load empty mark selection", lambda: curation.load_photo_marks(self.path, [])),
            (
                "save mark batch",
                lambda: curation.save_photo_marks(self.path, [{"file_id": "photo-1", "color_label": "green"}]),
            ),
        )
        for name, operation in operations:
            with self.subTest(operation=name), recorded_connections() as connections:
                operation()
                self.assert_connections_closed(connections)

        with recorded_connections() as connections:
            self.assertEqual(float(self.scores.load(self.path).iloc[0]["recommendation_0_10"]), 8.0)
            self.assertEqual(self.insights.load(self.path)[0].summary, "saved")
            self.assertEqual(self.config.load(self.path), {"model": "test-model"})
            mark = curation.load_photo_marks(self.path)["photo-1"]
            self.assertEqual((mark.rating, mark.status, mark.color_label), (4, "pick", "green"))
            self.assert_connections_closed(connections)

    def test_runtime_fixture_returns_with_every_connection_closed(self) -> None:
        with recorded_connections() as connections:
            fixture = write_fixture(self.root / "fixture", count=4)
            self.assertEqual(fixture["count"], 4)
            self.assert_connections_closed(connections)

    def test_score_batch_failure_rolls_back_and_closes(self) -> None:
        with recorded_connections() as connections:
            self.scores.save(self.rows(("photo-1", 6.0)), self.path)
            self.install_trigger("culvia_scores", "NEW.file_id = 'fail'")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "write failed"):
                self.scores.upsert(self.rows(("photo-1", 9.0), ("fail", 7.0)), self.path)
            saved = self.scores.load(self.path).set_index("file_id")
            self.assertEqual(list(saved.index), ["photo-1"])
            self.assertEqual(float(saved.loc["photo-1", "recommendation_0_10"]), 6.0)
            self.assert_connections_closed(connections)

    def test_insight_generator_failure_rolls_back_and_closes(self) -> None:
        error = RuntimeError("insight source failed")

        def failing_insights():
            yield self.insight(summary="uncommitted")
            raise error

        with recorded_connections() as connections:
            self.insights.save([self.insight()], self.path)
            with self.assertRaises(RuntimeError) as caught:
                self.insights.save(failing_insights(), self.path)
            self.assertIs(caught.exception, error)
            self.assertEqual(self.insights.load(self.path)[0].summary, "saved")
            self.assert_connections_closed(connections)

    def test_configuration_failure_rolls_back_prior_fields_and_closes(self) -> None:
        before = {"base_url": "https://example.test/v1", "model": "saved-model"}
        with recorded_connections() as connections:
            self.config.save(before, self.path)
            self.install_trigger("photo_app_config", "NEW.key = 'llm_model'")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "write failed"):
                self.config.save({"base_url": "https://example.test/v2", "model": "uncommitted"}, self.path)
            self.assertEqual(self.config.load(self.path), before)
            self.assert_connections_closed(connections)

    def test_mark_batch_failure_rolls_back_deleted_and_updated_marks(self) -> None:
        with recorded_connections() as connections:
            curation.save_photo_marks(
                self.path,
                [{"file_id": "photo-1", "status": "pick"}, {"file_id": "photo-2", "status": "hold"}],
            )
            before = curation.load_photo_marks(self.path)
            self.install_trigger("photo_curation_marks", "NEW.file_id = 'photo-2'")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "write failed"):
                curation.save_photo_marks(
                    self.path,
                    [{"file_id": "photo-1", "status": ""}, {"file_id": "photo-2", "status": "reject"}],
                )
            self.assertEqual(curation.load_photo_marks(self.path), before)
            with self.assertRaisesRegex(sqlite3.IntegrityError, "write failed"):
                curation.save_photo_mark(self.path, "photo-2", status="reject")
            self.assertEqual(curation.load_photo_marks(self.path), before)
            self.assert_connections_closed(connections)

    def test_read_failure_keeps_existing_error_contracts_and_closes(self) -> None:
        error = sqlite3.OperationalError("schema unavailable")

        def fail_schema(_connection):
            raise error

        with recorded_connections() as connections:
            self.scores.save(self.rows(("photo-1", 6.0)), self.path)
            with patch.object(ScoreCacheStore, "ensure_schema", side_effect=error):
                self.assertTrue(self.scores.load(self.path).empty)
            for store in (
                replace(self.insights, schema_ensurer=fail_schema),
                replace(self.config, schema_ensurer=fail_schema),
            ):
                with self.subTest(store=type(store).__name__), self.assertRaises(sqlite3.OperationalError) as caught:
                    store.load(self.path)
                self.assertIs(caught.exception, error)
            curation.save_photo_mark(self.path, "photo-1", status="pick")
            with patch("culvia.curation._photo_mark_from_row", side_effect=error):
                with self.assertRaises(sqlite3.OperationalError) as caught:
                    curation.load_photo_marks(self.path)
                self.assertIs(caught.exception, error)
            self.assert_connections_closed(connections)

    def test_history_operations_close_connections_and_preserve_records(self) -> None:
        with recorded_connections() as connections:
            curation_history.ensure_curation_history_schema(self.path)
            first = curation_history.append_curation_action(
                self.path,
                "status",
                scope="selected",
                summary="Pick one photo",
                payload={"beforeMarks": [{"fileId": "photo-1", "status": "hold"}]},
            )
            second = curation_history.append_curation_action(self.path, "restore", payload={"restored": 1})
            self.assertEqual(curation_history.load_curation_action(self.path, first.id), first)
            self.assertEqual(curation_history.load_curation_actions(self.path), [second, first])
            self.assertEqual(curation_history.load_curation_actions(self.path, limit=1), [second])
            self.assertIsNone(curation_history.load_curation_action(self.path, "missing"))
            self.assertEqual(first.payload["schemaVersion"], 1)
            self.assert_connections_closed(connections)

    def test_history_schema_errors_close_connections_and_preserve_the_file(self) -> None:
        contents = b"not a SQLite database"
        self.path.write_bytes(contents)
        operations = (
            lambda: curation_history.ensure_curation_history_schema(self.path),
            lambda: curation_history.append_curation_action(self.path, "status"),
            lambda: curation_history.load_curation_action(self.path, "action-1"),
            lambda: curation_history.load_curation_actions(self.path),
        )
        for index, operation in enumerate(operations):
            with self.subTest(operation=index), recorded_connections() as connections:
                with self.assertRaises(sqlite3.DatabaseError):
                    operation()
                self.assertEqual(self.path.read_bytes(), contents)
                self.assert_connections_closed(connections)

    def test_history_insert_failure_rolls_back_trigger_writes_and_closes(self) -> None:
        with recorded_connections() as connections:
            before = curation_history.append_curation_action(self.path, "status", payload={"marked": 1})
            with closing(sqlite3.connect(self.path)) as connection, connection:
                connection.execute("CREATE TABLE pending_history (value TEXT)")
                connection.execute(
                    "CREATE TRIGGER fail_history BEFORE INSERT ON photo_curation_actions WHEN NEW.kind = 'fail' "
                    "BEGIN INSERT INTO pending_history VALUES ('uncommitted'); "
                    "SELECT RAISE(FAIL, 'history write failed'); END"
                )
            with self.assertRaisesRegex(sqlite3.IntegrityError, "history write failed"):
                curation_history.append_curation_action(self.path, "fail", payload={"marked": 2})
            self.assertEqual(curation_history.load_curation_actions(self.path), [before])
            with closing(sqlite3.connect(self.path)) as connection:
                self.assertEqual(connection.execute("SELECT * FROM pending_history").fetchall(), [])
            self.assert_connections_closed(connections)

    def test_history_serialization_failure_closes_without_adding_a_record(self) -> None:
        with recorded_connections() as connections:
            before = curation_history.append_curation_action(self.path, "status", payload={"marked": 1})
            with self.assertRaisesRegex(TypeError, "JSON serializable"):
                curation_history.append_curation_action(self.path, "invalid", payload={"invalid": object()})
            self.assertEqual(curation_history.load_curation_actions(self.path), [before])
            self.assert_connections_closed(connections)

    def test_history_query_failures_close_connections(self) -> None:
        class DeniedSelect(sqlite3.Connection):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.set_authorizer(
                    lambda action, *_: sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_SELECT else sqlite3.SQLITE_OK
                )

        with recorded_connections() as connections:
            before = curation_history.append_curation_action(self.path, "status", payload={"marked": 1})
            self.assert_connections_closed(connections)
        operations = (
            lambda: curation_history.load_curation_action(self.path, before.id),
            lambda: curation_history.load_curation_actions(self.path),
        )
        for index, operation in enumerate(operations):
            with self.subTest(operation=index), recorded_connections(factory=DeniedSelect) as connections:
                with self.assertRaisesRegex(sqlite3.DatabaseError, "not authorized"):
                    operation()
                self.assert_connections_closed(connections)

    def test_checkpoint_writer_closes_after_schema_initialization_failure(self) -> None:
        error = RuntimeError("schema failed")

        def fail_schema(_store, connection):
            connection.execute("CREATE TABLE pending (value TEXT)")
            connection.execute("INSERT INTO pending VALUES ('uncommitted')")
            raise error

        writer = self.scores.checkpoint_writer(self.path)
        with recorded_connections() as connections:
            with patch.object(ScoreCacheStore, "ensure_schema", new=fail_schema):
                with self.assertRaises(RuntimeError) as caught, writer:
                    self.fail("writer body must not run when initialization fails")
                self.assertIs(caught.exception, error)
            self.assertIsNone(writer.connection)
            self.assert_connections_closed(connections)
            with closing(sqlite3.connect(self.path)) as connection:
                self.assertEqual(connection.execute("SELECT * FROM pending").fetchall(), [])
            with writer:
                writer.upsert(self.rows(("photo-1", 8.0)))
            self.assertEqual(float(self.scores.load(self.path).iloc[0]["recommendation_0_10"]), 8.0)
            self.assert_connections_closed(connections)

    def test_checkpoint_writer_closes_after_initial_commit_failure(self) -> None:
        class FailingCommit(sqlite3.Connection):
            def commit(self):
                raise sqlite3.OperationalError("commit failed")

        writer = self.scores.checkpoint_writer(self.path)
        with recorded_connections(factory=FailingCommit) as connections:
            with self.assertRaisesRegex(sqlite3.OperationalError, "commit failed"), writer:
                self.fail("writer body must not run when its initial commit fails")
            self.assertIsNone(writer.connection)
            self.assert_connections_closed(connections)

    def test_checkpoint_writer_preserves_completed_records_and_rolls_back_failed_batch(self) -> None:
        writer = self.scores.checkpoint_writer(self.path)
        with recorded_connections() as connections:
            with self.assertRaisesRegex(sqlite3.IntegrityError, "write failed"), writer:
                writer.upsert(self.rows(("photo-1", 8.0)))
                self.install_trigger("culvia_scores", "NEW.file_id = 'fail'")
                writer.upsert(self.rows(("photo-1", 9.0), ("fail", 7.0)))
            self.assertIsNone(writer.connection)
            saved = self.scores.load(self.path).set_index("file_id")
            self.assertEqual(list(saved.index), ["photo-1"])
            self.assertEqual(float(saved.loc["photo-1", "recommendation_0_10"]), 8.0)
            self.assert_connections_closed(connections)


if __name__ == "__main__":
    unittest.main()
