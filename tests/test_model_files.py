from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from culvia import model_files


class ModelFileHelperTests(unittest.TestCase):
    def test_format_helpers_are_compact_and_localized(self) -> None:
        self.assertEqual(model_files.format_bytes(None), "")
        self.assertEqual(model_files.format_bytes(1536), "1.5 KB")
        self.assertEqual(model_files.format_duration(None), "计算中")
        self.assertEqual(model_files.format_duration(65), "1分05秒")
        self.assertEqual(model_files.format_duration(3660), "1小时01分")

    def test_huggingface_cache_root_respects_hf_home(self) -> None:
        with patch.dict(os.environ, {"HF_HOME": "/tmp/culvia-hf"}, clear=False):
            self.assertEqual(model_files.get_huggingface_cache_root(), Path("/tmp/culvia-hf") / "hub")

    def test_request_headers_uses_huggingface_token_without_exposing_when_absent(self) -> None:
        with patch.dict(os.environ, {"HF_TOKEN": "token-123"}, clear=False):
            headers = model_files.request_headers({"Range": "bytes=10-"})

        self.assertEqual(headers["Authorization"], "Bearer token-123")
        self.assertEqual(headers["Range"], "bytes=10-")
        self.assertEqual(headers["User-Agent"], "culvia-local/1.0")

    def test_sanitize_proxy_env_for_httpx_removes_cidr_and_ipv6_no_proxy_entries(self) -> None:
        with patch.dict(os.environ, {"NO_PROXY": "localhost,10.0.0.0/8,::1,example.com"}, clear=False):
            model_files.sanitize_proxy_env_for_httpx()

            self.assertEqual(os.environ["NO_PROXY"], "localhost,example.com")

    def test_core_model_cache_status_accepts_app_model_file_for_model_pt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_cache = root / "app-model"
            app_cache.mkdir()
            (app_cache / "model.pt").write_bytes(b"model")
            snapshot = root / "hf" / "hub" / model_files.MODEL_CACHE_REPO_DIR / "snapshots" / "rev1"
            snapshot.mkdir(parents=True)
            for filename in model_files.MODEL_REQUIRED_CACHE_FILES:
                if filename != "model.pt":
                    (snapshot / filename).write_text("ok", encoding="utf-8")

            with (
                patch.object(model_files, "APP_MODEL_CACHE_DIR", app_cache),
                patch.dict(
                    os.environ,
                    {"HF_HOME": str(root / "hf")},
                    clear=False,
                ),
            ):
                status = model_files.get_model_cache_status()

        self.assertTrue(status["downloaded"])
        self.assertFalse(status["partial"])
        self.assertEqual(status["missing_files"], [])
        self.assertEqual(status["model_file"], str(app_cache / "model.pt"))

    def test_snapshot_status_reports_missing_files_and_active_incomplete_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo_dir = "models--unit--clip"
            repo = root / "hf" / "hub" / repo_dir
            snapshot = repo / "snapshots" / "rev1"
            blobs = repo / "blobs"
            snapshot.mkdir(parents=True)
            blobs.mkdir(parents=True)
            (snapshot / "config.json").write_text("{}", encoding="utf-8")
            (blobs / "download.incomplete").write_bytes(b"partial")

            with patch.dict(os.environ, {"HF_HOME": str(root / "hf")}, clear=False):
                status = model_files.get_hf_snapshot_status(
                    "unit/clip",
                    repo_dir,
                    ["config.json", "pytorch_model.bin"],
                )

        self.assertFalse(status["downloaded"])
        self.assertTrue(status["partial"])
        self.assertEqual(status["active_download_size"], 7)
        self.assertEqual(status["missing_files"], ["pytorch_model.bin"])

    def test_ensure_model_files_skips_download_when_all_files_cached(self) -> None:
        calls: list[tuple[str, int, int, str]] = []

        def progress(filename: str, stage: int, total: int, state: str, _info: dict[str, object]) -> None:
            calls.append((filename, stage, total, state))

        with (
            patch(
                "culvia.model_files.get_model_cache_status",
                return_value={"missing_files": []},
            ),
            patch("culvia.model_files.download_hf_file") as download_file,
        ):
            model_files.ensure_model_files(progress)

        self.assertEqual(len(calls), len(model_files.MODEL_REQUIRED_CACHE_FILES))
        self.assertTrue(all(call[3] == "cached" for call in calls))
        download_file.assert_not_called()


if __name__ == "__main__":
    unittest.main()
