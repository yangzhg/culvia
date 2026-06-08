from __future__ import annotations

import types
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import check_backend_smoke


class BackendSmokeTests(unittest.TestCase):
    def test_parse_ready_event_requires_machine_readable_payload(self) -> None:
        ready = check_backend_smoke.parse_ready_event(
            '{"event":"ready","baseUrl":"http://127.0.0.1:8501","healthUrl":"http://127.0.0.1:8501/health"}'
        )

        self.assertEqual(ready["baseUrl"], "http://127.0.0.1:8501")
        self.assertIsNone(check_backend_smoke.parse_ready_event("Culvia 已启动"))
        self.assertIsNone(check_backend_smoke.parse_ready_event('{"event":"log"}'))

    def test_parse_ready_event_rejects_nonlocal_or_mismatched_urls(self) -> None:
        self.assertIsNotNone(
            check_backend_smoke.parse_ready_event(
                '{"event":"ready","baseUrl":"http://localhost:8501","healthUrl":"http://localhost:8501/health"}'
            )
        )
        self.assertIsNone(
            check_backend_smoke.parse_ready_event(
                '{"event":"ready","baseUrl":"https://127.0.0.1:8501","healthUrl":"http://127.0.0.1:8501/health"}'
            )
        )
        self.assertIsNone(
            check_backend_smoke.parse_ready_event(
                '{"event":"ready","baseUrl":"http://example.com:8501","healthUrl":"http://127.0.0.1:8501/health"}'
            )
        )
        self.assertIsNone(
            check_backend_smoke.parse_ready_event(
                '{"event":"ready","baseUrl":"http://127.0.0.1:8501","healthUrl":"http://127.0.0.1:8502/health"}'
            )
        )
        self.assertIsNone(
            check_backend_smoke.parse_ready_event(
                '{"event":"ready","baseUrl":"http://127.0.0.1","healthUrl":"http://127.0.0.1/health"}'
            )
        )
        self.assertIsNone(
            check_backend_smoke.parse_ready_event(
                '{"event":"ready","baseUrl":"http://127.0.0.1:8501","healthUrl":"http://127.0.0.1:8501/"}'
            )
        )
        self.assertIsNone(
            check_backend_smoke.parse_ready_event(
                '{"event":"ready","baseUrl":"http://127.0.0.1:8501","healthUrl":"http://127.0.0.1:8501/ready"}'
            )
        )
        self.assertIsNone(
            check_backend_smoke.parse_ready_event(
                '{"event":"ready","baseUrl":"http://127.0.0.1:8501","healthUrl":"http://127.0.0.1:8501"}'
            )
        )

    def test_source_command_runs_python_backend_module(self) -> None:
        args = types.SimpleNamespace(source=True, python=Path("/python"), timeout=10.0, binary=None)

        mode, command = check_backend_smoke.command_for_args(args)

        self.assertEqual(mode, "source")
        self.assertEqual(command[:3], ["/python", "-m", "culvia.server"])
        self.assertIn("--print-json", command)
        self.assertIn("--port", command)
        self.assertIn("auto", command)

    def test_binary_command_defaults_to_current_backend_binary(self) -> None:
        args = types.SimpleNamespace(source=False, python=Path("/python"), timeout=10.0, binary=None)

        with patch("tools.check_backend_smoke.default_binary_path", return_value=Path("/backend")):
            mode, command = check_backend_smoke.command_for_args(args)

        self.assertEqual(mode, "binary")
        self.assertEqual(command[0], "/backend")
        self.assertIn("--print-json", command)

    def test_explicit_binary_command_uses_given_path(self) -> None:
        args = types.SimpleNamespace(source=False, python=Path("/python"), timeout=10.0, binary=Path("/custom"))

        mode, command = check_backend_smoke.command_for_args(args)

        self.assertEqual(mode, "binary")
        self.assertEqual(command[0], "/custom")

    def test_smoke_reports_process_start_failure_as_payload(self) -> None:
        result = check_backend_smoke.smoke(["/definitely/missing/culvia-server"], timeout=1.0)

        self.assertFalse(result["ok"])
        self.assertIsNone(result["ready"])
        self.assertIsNone(result["returncode"])
        self.assertIn("definitely/missing", result["error"])


if __name__ == "__main__":
    unittest.main()
