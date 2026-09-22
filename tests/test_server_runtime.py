from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from culvia import server, settings


class ServerRuntimeTests(unittest.TestCase):
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
