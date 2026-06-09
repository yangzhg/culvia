from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from culvia.supervisor import (
    DEFAULT_PORT,
    STATE_DIR_ENV,
    ServerTarget,
    build_runtime_env,
    build_server_command,
    find_available_port,
    parse_args,
    print_ready_event,
    ready_event_payload,
    runtime_log_path,
    runtime_state_dir,
)


class SupervisorConfigTests(unittest.TestCase):
    def test_server_target_builds_public_and_health_urls(self) -> None:
        target = ServerTarget("127.0.0.1", 8510)

        self.assertEqual(target.base_url, "http://127.0.0.1:8510")
        self.assertEqual(target.health_url, "http://127.0.0.1:8510/health")

    def test_server_command_uses_uvicorn_module_and_target_port(self) -> None:
        command = build_server_command(ServerTarget("0.0.0.0", 9000), reload=True)

        self.assertIn("-m", command)
        self.assertIn("uvicorn", command)
        self.assertIn("culvia_app:app", command)
        self.assertEqual(command[-1], "--reload")
        self.assertIn("9000", command)

    def test_ready_event_can_be_machine_readable_for_desktop_shells(self) -> None:
        target = ServerTarget("127.0.0.1", 8510)
        payload = ready_event_payload(target)

        self.assertEqual(payload["event"], "ready")
        self.assertEqual(payload["baseUrl"], "http://127.0.0.1:8510")
        self.assertEqual(payload["healthUrl"], "http://127.0.0.1:8510/health")

        output = io.StringIO()
        with patch("sys.stdout", output):
            print_ready_event(target, as_json=True)
        emitted = json.loads(output.getvalue())
        self.assertEqual(emitted, payload)

    def test_auto_port_returns_a_usable_port(self) -> None:
        class FakeSocket:
            def __enter__(self) -> "FakeSocket":
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def bind(self, address: tuple[str, int]) -> None:
                self.address = address

            def getsockname(self) -> tuple[str, int]:
                return ("127.0.0.1", 49152)

        with patch("culvia.supervisor.socket.socket", return_value=FakeSocket()):
            port = find_available_port("127.0.0.1", 0)

        self.assertGreater(port, 0)
        self.assertNotEqual(port, DEFAULT_PORT)

    def test_runtime_env_keeps_runtime_data_outside_project_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp) / "cache"
            data_dir = Path(tmp) / "data"
            env = build_runtime_env(
                {
                    "CULVIA_CACHE_DIR": str(cache_dir),
                    STATE_DIR_ENV: str(data_dir),
                }
            )

            self.assertEqual(env["CULVIA_DATA_DIR"], str(cache_dir))
            self.assertEqual(env["CULVIA_THUMBNAIL_CACHE_DIR"], str(cache_dir / "thumbnails"))
            self.assertEqual(env["CULVIA_UPLOAD_DIR"], str(cache_dir / "uploads"))
            self.assertEqual(env["CULVIA_CACHE_PATH"], str(data_dir / "culvia_scores.sqlite"))
            self.assertEqual(runtime_log_path(env), data_dir / "logs" / "supervisor.log")
            self.assertEqual(env["PYTHONUNBUFFERED"], "1")

    def test_runtime_env_does_not_override_explicit_app_paths(self) -> None:
        env = build_runtime_env(
            {
                "CULVIA_DATA_DIR": "/custom/runtime",
                "CULVIA_CACHE_PATH": "/custom/scores.sqlite",
                "CULVIA_THUMBNAIL_CACHE_DIR": "/custom/thumbs",
                "CULVIA_UPLOAD_DIR": "/custom/uploads",
            }
        )

        self.assertEqual(env["CULVIA_DATA_DIR"], "/custom/runtime")
        self.assertEqual(env["CULVIA_CACHE_PATH"], "/custom/scores.sqlite")
        self.assertEqual(env["CULVIA_THUMBNAIL_CACHE_DIR"], "/custom/thumbs")
        self.assertEqual(env["CULVIA_UPLOAD_DIR"], "/custom/uploads")

    def test_runtime_env_keeps_explicit_cache_path_over_state_dir_default(self) -> None:
        env = build_runtime_env(
            {
                STATE_DIR_ENV: "/state/root",
                "CULVIA_CACHE_PATH": "/custom/scores.sqlite",
            }
        )

        self.assertEqual(env["CULVIA_CACHE_PATH"], "/custom/scores.sqlite")
        self.assertEqual(runtime_log_path(env), Path("/state/root") / "logs" / "supervisor.log")

    def test_runtime_state_dir_falls_back_to_data_dir_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "app-data"

            self.assertEqual(runtime_state_dir({"CULVIA_DATA_DIR": str(data_dir)}), data_dir)
            self.assertEqual(runtime_log_path({"CULVIA_DATA_DIR": str(data_dir)}), data_dir / "logs" / "supervisor.log")

    def test_parse_args_supports_auto_port_without_touching_global_env(self) -> None:
        original = os.environ.get("CULVIA_PORT")
        try:
            os.environ.pop("CULVIA_PORT", None)
            with patch("culvia.supervisor.find_available_port", return_value=49153) as find_port:
                config = parse_args(["--host", "127.0.0.1", "--port", "auto", "--no-open", "--print-json"])
        finally:
            if original is None:
                os.environ.pop("CULVIA_PORT", None)
            else:
                os.environ["CULVIA_PORT"] = original

        find_port.assert_called_once_with("127.0.0.1", DEFAULT_PORT)
        self.assertEqual(config.target.host, "127.0.0.1")
        self.assertGreater(config.target.port, 0)
        self.assertFalse(config.open_browser)
        self.assertTrue(config.print_json)

    def test_parse_args_supports_random_port_for_desktop_shells(self) -> None:
        with patch("culvia.supervisor.find_available_port", return_value=49154) as find_port:
            config = parse_args(["--host", "127.0.0.1", "--port", "random", "--no-open", "--print-json"])

        find_port.assert_called_once_with("127.0.0.1", 0)
        self.assertEqual(config.target.host, "127.0.0.1")
        self.assertEqual(config.target.port, 49154)
        self.assertFalse(config.open_browser)
        self.assertTrue(config.print_json)


if __name__ == "__main__":
    unittest.main()
