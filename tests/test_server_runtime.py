from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

from culvia import __version__, server, settings


class ServerRuntimeTests(unittest.TestCase):
    def test_module_entrypoint_handles_command_line_arguments(self) -> None:
        for arguments, returncode, expected in (
            (["--help"], 0, "--health-timeout"),
            (["--unknown-option"], 2, "unrecognized arguments"),
        ):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [sys.executable, "-m", "culvia.server", *arguments],
                    cwd=Path(__file__).resolve().parents[1],
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
                self.assertEqual(result.returncode, returncode, result.stderr)
                self.assertIn(expected, result.stdout + result.stderr)

    def test_module_entrypoint_starts_live_service_from_isolated_directory(self) -> None:
        from tools import check_backend_smoke, check_backend_workflow_smoke, prepare_runtime_fixture

        with tempfile.TemporaryDirectory(prefix="culvia-server-entrypoint-") as tmp:
            fixture = prepare_runtime_fixture.write_fixture(Path(tmp), count=2)
            env = check_backend_workflow_smoke.workflow_environment(fixture)
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
            env["PYTHONNOUSERSITE"] = "1"
            stdout, stderr = deque(maxlen=20), deque(maxlen=20)
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "culvia.server",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "random",
                    "--no-open",
                    "--print-json",
                    "--health-timeout",
                    "15",
                ],
                cwd=tmp,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            try:
                ready = check_backend_smoke.wait_for_ready(process, 20, stdout_tail=stdout, stderr_tail=stderr)
                check_backend_smoke.wait_for_health(ready["healthUrl"], 5)
                state = check_backend_workflow_smoke.request_json(ready["baseUrl"], "/api/state")
                self.assertEqual(state["app"]["serviceVersion"], __version__)
                self.assertEqual(len(state["photos"]), 2)
            finally:
                check_backend_smoke.terminate_process(process)

    def test_runtime_setup_preserves_desktop_build_identity(self) -> None:
        desktop_identity = {
            "CULVIA_DESKTOP_APP": "1",
            "CULVIA_DESKTOP_SHELL_VERSION": "1.0.0",
            "CULVIA_DESKTOP_RUNTIME_PROFILE": "lite",
            "CULVIA_DESKTOP_BUILD_TARGET": "aarch64-apple-darwin",
        }
        with patch.dict(
            os.environ,
            {
                **desktop_identity,
                "CULVIA_DATA_DIR": "/runtime/data",
                "CULVIA_CACHE_DIR": "/runtime/cache",
            },
            clear=True,
        ):
            server.apply_runtime_env()

            self.assertEqual({key: os.environ[key] for key in desktop_identity}, desktop_identity)

    def test_parse_args_accepts_auto_port_for_packaged_backend(self) -> None:
        with patch("culvia.server.find_available_port", return_value=49160):
            config = server.parse_args(["--port", "auto"])

        self.assertEqual(config.target.host, "127.0.0.1")
        self.assertEqual(config.target.port, 49160)
        self.assertFalse(config.print_json)

    def test_parse_args_accepts_random_port_for_desktop_backend(self) -> None:
        with patch("culvia.server.find_available_port", return_value=49161) as find_port:
            config = server.parse_args(["--port", "random"])

        find_port.assert_called_once_with("127.0.0.1", 0)
        self.assertEqual(config.target.host, "127.0.0.1")
        self.assertEqual(config.target.port, 49161)

    def test_parse_args_accepts_production_startup_args(self) -> None:
        config = server.parse_args(
            [
                "--host",
                "127.0.0.1",
                "--port",
                "8509",
                "--no-open",
                "--print-json",
                "--health-timeout",
                "3",
            ]
        )

        self.assertEqual(config.target.base_url, "http://127.0.0.1:8509")
        self.assertEqual(config.health_timeout, 3)

    def test_resolve_web_dir_supports_pyinstaller_meipass_share_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundled = root / "share" / "culvia" / "web"
            bundled.mkdir(parents=True)
            (bundled / "index.html").write_text("", encoding="utf-8")

            with patch.object(settings.sys, "_MEIPASS", str(root), create=True), patch.dict(os.environ, {}, clear=True):
                self.assertEqual(settings.resolve_web_dir(), bundled)


if __name__ == "__main__":
    unittest.main()
