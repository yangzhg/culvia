from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from culvia import settings


class ConfigPathTests(unittest.TestCase):
    def test_cache_path_uses_current_env_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            current = Path(tmp) / "current.sqlite"
            with patch.dict(
                os.environ,
                {"CULVIA_CACHE_PATH": str(current)},
                clear=False,
            ):
                self.assertEqual(settings.default_cache_path(), str(current))

    def test_data_dir_drives_model_analysis_and_thumbnail_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            with patch.dict(os.environ, {"CULVIA_DATA_DIR": str(data_dir)}, clear=False):
                self.assertEqual(
                    settings.rsinema_model_cache_dir(),
                    data_dir / "model_cache" / "rsinema_aesthetic_scorer",
                )
                self.assertEqual(settings.analysis_image_cache_dir(), data_dir / "analysis_cache")
                self.assertEqual(settings.thumbnail_cache_dir(), data_dir / "thumbnail_cache")

    def test_upload_dir_uses_current_env_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            current = Path(tmp) / "uploads"
            with patch.dict(os.environ, {"CULVIA_UPLOAD_DIR": str(current)}, clear=False):
                self.assertEqual(settings.upload_cache_dir(), current)

    def test_user_dirs_are_cross_platform(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch("sys.platform", "linux"):
            self.assertEqual(settings.user_data_dir(), Path.home() / ".local" / "share" / settings.APP_SLUG)
            self.assertEqual(settings.user_cache_dir(), Path.home() / ".cache" / settings.APP_SLUG)

        with (
            patch.dict(os.environ, {"LOCALAPPDATA": "C:/Users/A/AppData/Local"}, clear=True),
            patch("sys.platform", "win32"),
        ):
            self.assertEqual(settings.user_data_dir(), Path("C:/Users/A/AppData/Local") / settings.APP_DISPLAY_NAME)
            self.assertEqual(
                settings.user_cache_dir(), Path("C:/Users/A/AppData/Local") / settings.APP_DISPLAY_NAME / "Cache"
            )

    def test_resolve_web_dir_supports_installed_share_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            installed = root / "share" / "culvia" / "web"
            installed.mkdir(parents=True)
            (installed / "index.html").write_text("<!doctype html>", encoding="utf-8")

            with (
                patch.dict(os.environ, {}, clear=True),
                patch.object(settings, "PROJECT_ROOT", root / "missing"),
                patch(
                    "sys.prefix",
                    str(root),
                ),
            ):
                self.assertEqual(settings.resolve_web_dir(), installed)


if __name__ == "__main__":
    unittest.main()
