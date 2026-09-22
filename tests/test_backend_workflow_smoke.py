from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from tools import check_backend_workflow_smoke as smoke


class BackendWorkflowSmokeTests(unittest.TestCase):
    def assert_reader_closes_connection(self, reader, *, empty: bool = False, missing_table: bool = False) -> None:
        connect = sqlite3.connect
        connections: list[sqlite3.Connection] = []

        def tracked_connect(*args, **kwargs):
            connection = connect(*args, **kwargs)
            connections.append(connection)
            return connection

        with tempfile.TemporaryDirectory(prefix="culvia-smoke-connection-") as tmp:
            database = Path(tmp) / "fixture.sqlite"
            with closing(connect(database)) as connection:
                if not missing_table:
                    connection.execute("CREATE TABLE photo_app_config (key TEXT, value TEXT)")
                    connection.execute("INSERT INTO photo_app_config VALUES ('llm_model', 'fixture-model')")
                    connection.execute("INSERT INTO photo_app_config VALUES ('unrelated', 'ignored')")
                    connection.execute(
                        "CREATE TABLE culvia_scores (file_id TEXT, path TEXT, folder TEXT, filename TEXT, "
                        "error TEXT, technical_overall_0_10 REAL, sharpness_0_10 REAL, exposure_0_10 REAL, "
                        "contrast_0_10 REAL, cleanliness_0_10 REAL)"
                    )
                    if not empty:
                        connection.execute(
                            "INSERT INTO culvia_scores VALUES "
                            "('fixture', '/photos/fixture.jpg', '/photos', 'fixture.jpg', '', 5, 6, 7, 8, 9)"
                        )
                    connection.commit()

            try:
                with patch.object(smoke.sqlite3, "connect", side_effect=tracked_connect):
                    if missing_table:
                        with self.assertRaisesRegex(sqlite3.OperationalError, "no such table"):
                            reader(database)
                    else:
                        result = reader(database)
                        if reader is smoke.read_persisted_llm_rows:
                            self.assertEqual(result, {"llm_model": "fixture-model"})
                        elif empty:
                            self.assertEqual(result, {"count": 0})
                        else:
                            self.assertEqual(result["count"], 1)
                            self.assertEqual(result["file_id"], "fixture")
                            self.assertEqual(result["technical_overall_0_10"], 5)
                self.assertEqual(len(connections), 1)
                with self.assertRaisesRegex(sqlite3.ProgrammingError, "closed database"):
                    connections[0].execute("SELECT 1")
                database.unlink()
            finally:
                for connection in connections:
                    connection.close()

    def test_llm_configuration_reader_closes_connection(self) -> None:
        self.assert_reader_closes_connection(smoke.read_persisted_llm_rows)

    def test_basic_technical_reader_closes_connection(self) -> None:
        self.assert_reader_closes_connection(smoke.sqlite_basic_technical_row)

    def test_basic_technical_reader_closes_connection_for_empty_result(self) -> None:
        self.assert_reader_closes_connection(smoke.sqlite_basic_technical_row, empty=True)

    def test_readers_close_connection_when_query_fails(self) -> None:
        for reader in (smoke.read_persisted_llm_rows, smoke.sqlite_basic_technical_row):
            with self.subTest(reader=reader.__name__):
                self.assert_reader_closes_connection(reader, missing_table=True)


if __name__ == "__main__":
    unittest.main()
