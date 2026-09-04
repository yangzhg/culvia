from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from culvia import model_files
from culvia.job_text import TranslatableRuntimeError


class ModelFileHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        with model_files._FILE_SHA256_CACHE_LOCK:
            model_files._FILE_SHA256_CACHE.clear()

    def test_audited_model_pins_are_exact(self) -> None:
        self.assertEqual(model_files.MODEL_REVISION, "2e93f809b484701a79ecc046ae2057c9084e1d38")
        self.assertEqual(
            model_files.MODEL_PT_SHA256,
            "59853d88e95c287d101bd692c876232f5cd4a860299060d370258ad68b36042d",
        )
        self.assertEqual(
            model_files.CLIP_REFERENCE_MODEL_REVISION,
            "eaee4c876b93e66f7fac584b529025a96d71ad66",
        )
        self.assertEqual(
            model_files.CLIP_REFERENCE_WEIGHT_SHA256,
            "99d28a652e6ec46629ab7047a0ac82c69b1fe11e0ce672c43af65d3a9a3fc05d",
        )

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
            snapshot = root / "hf" / "hub" / model_files.MODEL_CACHE_REPO_DIR / "snapshots" / model_files.MODEL_REVISION
            snapshot.mkdir(parents=True)
            for filename in model_files.MODEL_REQUIRED_CACHE_FILES:
                if filename != "model.pt":
                    (snapshot / filename).write_text("ok", encoding="utf-8")
            digest = model_files.file_sha256(app_cache / "model.pt")

            with (
                patch.object(model_files, "APP_MODEL_CACHE_DIR", app_cache),
                patch.object(model_files, "MODEL_PT_SHA256", digest),
                patch.dict(
                    os.environ,
                    {"HF_HOME": str(root / "hf")},
                    clear=False,
                ),
            ):
                model_files.verify_file_sha256(
                    app_cache / "model.pt",
                    digest,
                    filename="model.pt",
                    revision=model_files.MODEL_REVISION,
                )
                with model_files._FILE_SHA256_CACHE_LOCK:
                    model_files._FILE_SHA256_CACHE.clear()
                status = model_files.get_model_cache_status()

        self.assertTrue(status["downloaded"])
        self.assertFalse(status["partial"])
        self.assertEqual(status["missing_files"], [])
        self.assertEqual(status["model_file"], str(app_cache / "model.pt"))
        self.assertEqual(status["integrity_state"], model_files.INTEGRITY_STATE_VERIFIED)

    def test_core_model_cache_status_marks_corrupt_weight_not_ready_offline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_cache = root / "app-model"
            app_cache.mkdir()
            (app_cache / "model.pt").write_bytes(b"corrupt")
            snapshot = root / "hf" / "hub" / model_files.MODEL_CACHE_REPO_DIR / "snapshots" / model_files.MODEL_REVISION
            snapshot.mkdir(parents=True)
            for filename in model_files.MODEL_REQUIRED_CACHE_FILES:
                if filename != "model.pt":
                    (snapshot / filename).write_text("ok", encoding="utf-8")

            with (
                patch.object(model_files, "APP_MODEL_CACHE_DIR", app_cache),
                patch.dict(os.environ, {"HF_HOME": str(root / "hf")}, clear=False),
                patch("culvia.model_files.download_hf_file", side_effect=ConnectionError("offline")),
            ):
                before = model_files.get_model_cache_status()
                with self.assertRaises(ConnectionError):
                    model_files.ensure_model_files()
                after = model_files.get_model_cache_status()

        self.assertEqual(before["integrity_state"], model_files.INTEGRITY_STATE_NOT_CHECKED)
        self.assertEqual(after["integrity_state"], model_files.INTEGRITY_STATE_MISMATCH)
        for status in (before, after):
            self.assertFalse(status["downloaded"])
            self.assertTrue(status["partial"])
            self.assertIn("model.pt", status["missing_files"])

    def test_valid_pinned_core_snapshot_recovers_offline_from_corrupt_app_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_cache = root / "app-model"
            app_cache.mkdir()
            (app_cache / "model.pt").write_bytes(b"corrupt")
            snapshot = root / "hf" / "hub" / model_files.MODEL_CACHE_REPO_DIR / "snapshots" / model_files.MODEL_REVISION
            snapshot.mkdir(parents=True)
            for filename in model_files.MODEL_REQUIRED_CACHE_FILES:
                (snapshot / filename).write_bytes(b"trusted" if filename == "model.pt" else b"ok")
            digest = model_files.file_sha256(snapshot / "model.pt")

            with (
                patch.object(model_files, "APP_MODEL_CACHE_DIR", app_cache),
                patch.object(model_files, "MODEL_PT_SHA256", digest),
                patch.dict(os.environ, {"HF_HOME": str(root / "hf")}, clear=False),
                patch("culvia.model_files.download_hf_file") as download,
            ):
                cold = model_files.get_model_cache_status()
                model_files.ensure_model_files()
                ready = model_files.get_model_cache_status()

        self.assertEqual(cold["model_file"], str(app_cache / "model.pt"))
        self.assertEqual(cold["integrity_state"], model_files.INTEGRITY_STATE_NOT_CHECKED)
        self.assertFalse(cold["downloaded"])
        self.assertEqual(ready["model_file"], str(snapshot / "model.pt"))
        self.assertEqual(ready["integrity_state"], model_files.INTEGRITY_STATE_VERIFIED)
        self.assertTrue(ready["downloaded"])
        download.assert_not_called()

    def test_core_model_cache_status_ignores_unpinned_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "hf" / "hub" / model_files.MODEL_CACHE_REPO_DIR / "snapshots" / "moving-main"
            snapshot.mkdir(parents=True)
            for filename in model_files.MODEL_REQUIRED_CACHE_FILES:
                (snapshot / filename).write_text("untrusted", encoding="utf-8")

            with (
                patch.object(model_files, "APP_MODEL_CACHE_DIR", root / "app-model"),
                patch.dict(os.environ, {"HF_HOME": str(root / "hf")}, clear=False),
            ):
                status = model_files.get_model_cache_status()

        self.assertFalse(status["downloaded"])
        self.assertEqual(status["revision"], model_files.MODEL_REVISION)
        self.assertEqual(status["missing_files"], model_files.MODEL_REQUIRED_CACHE_FILES)

    def test_status_digest_is_cached_by_file_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "model.pt"
            model_path.write_bytes(b"stable")
            expected = model_files.file_sha256(model_path)
            with (
                patch.object(model_files, "APP_MODEL_CACHE_DIR", Path(tmp) / "app-cache"),
                patch("culvia.model_files.file_sha256", wraps=model_files.file_sha256) as digest,
            ):
                cold = model_files.cached_file_integrity_state(model_path, expected)
                model_files.verify_file_sha256(model_path, expected)
                warm = model_files.cached_file_integrity_state(model_path, expected)
                second_warm = model_files.cached_file_integrity_state(model_path, expected)
                model_path.write_bytes(b"changed-size")
                changed = model_files.cached_file_integrity_state(model_path, expected)

        self.assertEqual(cold, model_files.INTEGRITY_STATE_NOT_CHECKED)
        self.assertEqual(warm, model_files.INTEGRITY_STATE_VERIFIED)
        self.assertEqual(second_warm, model_files.INTEGRITY_STATE_VERIFIED)
        self.assertEqual(changed, model_files.INTEGRITY_STATE_NOT_CHECKED)
        digest.assert_called_once_with(model_path)

    def test_integrity_marker_binds_artifact_identity_and_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "model.pt"
            model_path.write_bytes(b"stable")
            expected = model_files.file_sha256(model_path)
            marker_root = Path(tmp) / "app-cache"
            with patch.object(model_files, "APP_MODEL_CACHE_DIR", marker_root):
                model_files.verify_file_sha256(
                    model_path,
                    expected,
                    revision="fixed-revision",
                    filename="model.pt",
                )
                with model_files._FILE_SHA256_CACHE_LOCK:
                    model_files._FILE_SHA256_CACHE.clear()
                verified = model_files.cached_file_integrity_state(
                    model_path,
                    expected,
                    revision="fixed-revision",
                    filename="model.pt",
                )
                wrong_revision = model_files.cached_file_integrity_state(
                    model_path,
                    expected,
                    revision="other-revision",
                    filename="model.pt",
                )
                wrong_filename = model_files.cached_file_integrity_state(
                    model_path,
                    expected,
                    revision="fixed-revision",
                    filename="other.pt",
                )
                wrong_digest = model_files.cached_file_integrity_state(
                    model_path,
                    "0" * 64,
                    revision="fixed-revision",
                    filename="model.pt",
                )
                markers = list((marker_root / ".integrity").glob("*.json"))
                marker_payload = json.loads(markers[0].read_text(encoding="utf-8"))

        self.assertEqual(verified, model_files.INTEGRITY_STATE_VERIFIED)
        self.assertEqual(wrong_revision, model_files.INTEGRITY_STATE_NOT_CHECKED)
        self.assertEqual(wrong_filename, model_files.INTEGRITY_STATE_NOT_CHECKED)
        self.assertEqual(wrong_digest, model_files.INTEGRITY_STATE_MISMATCH)
        self.assertEqual(len(markers), 1)
        self.assertEqual(marker_payload["schemaVersion"], 1)
        self.assertEqual(marker_payload["revision"], "fixed-revision")
        self.assertEqual(marker_payload["filename"], "model.pt")
        self.assertNotIn("path", marker_payload)
        self.assertNotIn(str(model_path), markers[0].name)

    def test_integrity_marker_write_failure_only_forgets_next_process_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "model.pt"
            model_path.write_bytes(b"stable")
            expected = model_files.file_sha256(model_path)
            with (
                patch.object(model_files, "APP_MODEL_CACHE_DIR", Path(tmp) / "app-cache"),
                patch("culvia.model_files.os.replace", side_effect=OSError("read only")),
            ):
                verified_path = model_files.verify_file_sha256(
                    model_path,
                    expected,
                    revision="fixed-revision",
                    filename="model.pt",
                )
                current_process = model_files.cached_file_integrity_state(
                    model_path,
                    expected,
                    revision="fixed-revision",
                    filename="model.pt",
                )
                with model_files._FILE_SHA256_CACHE_LOCK:
                    model_files._FILE_SHA256_CACHE.clear()
                next_process = model_files.cached_file_integrity_state(
                    model_path,
                    expected,
                    revision="fixed-revision",
                    filename="model.pt",
                )

        self.assertEqual(verified_path, model_path)
        self.assertEqual(current_process, model_files.INTEGRITY_STATE_VERIFIED)
        self.assertEqual(next_process, model_files.INTEGRITY_STATE_NOT_CHECKED)

    def test_cold_model_status_never_hashes_weight_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_cache = root / "app-model"
            app_cache.mkdir()
            (app_cache / "model.pt").write_bytes(b"core")
            core_snapshot = (
                root / "hf" / "hub" / model_files.MODEL_CACHE_REPO_DIR / "snapshots" / model_files.MODEL_REVISION
            )
            core_snapshot.mkdir(parents=True)
            for filename in model_files.MODEL_REQUIRED_CACHE_FILES:
                if filename != "model.pt":
                    (core_snapshot / filename).write_bytes(b"ok")
            clip_snapshot = (
                root
                / "hf"
                / "hub"
                / model_files.CLIP_REFERENCE_MODEL_REPO_DIR
                / "snapshots"
                / model_files.CLIP_REFERENCE_MODEL_REVISION
            )
            clip_snapshot.mkdir(parents=True)
            for filename in model_files.CLIP_REFERENCE_REQUIRED_CACHE_FILES:
                (clip_snapshot / filename).write_bytes(b"clip")

            with (
                patch.object(model_files, "APP_MODEL_CACHE_DIR", app_cache),
                patch.dict(os.environ, {"HF_HOME": str(root / "hf")}, clear=False),
                patch("culvia.model_files.file_sha256") as digest,
            ):
                core_status = model_files.get_model_cache_status()
                clip_status = model_files.get_clip_reference_cache_status()

        digest.assert_not_called()
        self.assertEqual(core_status["integrity_state"], model_files.INTEGRITY_STATE_NOT_CHECKED)
        self.assertEqual(clip_status["integrity_state"], model_files.INTEGRITY_STATE_NOT_CHECKED)
        self.assertFalse(core_status["downloaded"])
        self.assertFalse(clip_status["downloaded"])

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

        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "model.pt"
            model_path.write_bytes(b"cached")
            digest = model_files.file_sha256(model_path)
            with (
                patch(
                    "culvia.model_files.get_model_cache_status",
                    return_value={
                        "missing_files": [],
                        "model_file": str(model_path),
                        "integrity_state": model_files.INTEGRITY_STATE_VERIFIED,
                    },
                ),
                patch.object(model_files, "MODEL_PT_SHA256", digest),
                patch("culvia.model_files.download_hf_file") as download_file,
            ):
                model_files.ensure_model_files(progress)

        self.assertEqual(len(calls), len(model_files.MODEL_REQUIRED_CACHE_FILES))
        self.assertTrue(all(call[3] == "cached" for call in calls))
        download_file.assert_not_called()

    def test_download_hf_file_pins_core_model_revision(self) -> None:
        with patch("culvia.model_files.hf_hub_download", return_value="/tmp/config.json") as download:
            result = model_files.download_hf_file("preprocessor_config.json", 1, 5)

        self.assertEqual(result, "/tmp/config.json")
        download.assert_called_once_with(
            repo_id=model_files.MODEL_ID,
            filename="preprocessor_config.json",
            revision=model_files.MODEL_REVISION,
        )

    def test_cached_core_model_is_verified_before_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_cache = Path(tmp)
            model_path = app_cache / "model.pt"
            model_path.write_bytes(b"trusted-model")
            digest = model_files.file_sha256(model_path)

            with (
                patch.object(model_files, "APP_MODEL_CACHE_DIR", app_cache),
                patch.object(model_files, "MODEL_PT_SHA256", digest),
                patch("culvia.model_files.requests.get") as request,
            ):
                result = model_files.download_model_pt_with_progress(5, 5)

        self.assertEqual(result, str(model_path))
        request.assert_not_called()

    def test_completed_core_download_persists_final_path_integrity_marker(self) -> None:
        payload = b"trusted-model"

        class FakeResponse:
            status_code = 200
            headers = {"content-length": str(len(payload))}

            def raise_for_status(self) -> None:
                return None

            def iter_content(self, chunk_size: int):
                self.chunk_size = chunk_size
                yield payload

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app_cache = root / "app-model"
            snapshot = root / "hf" / "hub" / model_files.MODEL_CACHE_REPO_DIR / "snapshots" / model_files.MODEL_REVISION
            snapshot.mkdir(parents=True)
            for filename in model_files.MODEL_REQUIRED_CACHE_FILES:
                if filename != "model.pt":
                    (snapshot / filename).write_bytes(b"ok")
            digest = hashlib.sha256(payload).hexdigest()

            with (
                patch.object(model_files, "APP_MODEL_CACHE_DIR", app_cache),
                patch.object(model_files, "MODEL_PT_SHA256", digest),
                patch.dict(os.environ, {"HF_HOME": str(root / "hf")}, clear=False),
                patch("culvia.model_files.hf_hub_url", return_value="https://example.test/model.pt"),
                patch("culvia.model_files.requests.get", return_value=FakeResponse()),
            ):
                model_files.download_model_pt_with_progress(5, 5)
                with model_files._FILE_SHA256_CACHE_LOCK:
                    model_files._FILE_SHA256_CACHE.clear()
                status = model_files.get_model_cache_status()
                final_marker = model_files._integrity_marker_path(app_cache / "model.pt")
                part_marker = model_files._integrity_marker_path(app_cache / "model.pt.part")
                final_marker_exists = final_marker.exists()
                part_marker_exists = part_marker.exists()

        self.assertTrue(status["downloaded"])
        self.assertEqual(status["integrity_state"], model_files.INTEGRITY_STATE_VERIFIED)
        self.assertTrue(final_marker_exists)
        self.assertFalse(part_marker_exists)

    def test_stale_partial_core_download_retries_once_from_zero(self) -> None:
        fresh_payload = b"fresh-complete-model"

        class FakeResponse:
            def __init__(self, status_code: int, payload: bytes) -> None:
                self.status_code = status_code
                self.payload = payload
                self.headers = {"content-length": str(len(payload))}

            def raise_for_status(self) -> None:
                return None

            def iter_content(self, chunk_size: int):
                self.chunk_size = chunk_size
                yield self.payload

        with tempfile.TemporaryDirectory() as tmp:
            app_cache = Path(tmp)
            (app_cache / "model.pt.part").write_bytes(b"old-")
            responses = [
                FakeResponse(206, b"new-revision-tail"),
                FakeResponse(200, fresh_payload),
            ]
            with (
                patch.object(model_files, "APP_MODEL_CACHE_DIR", app_cache),
                patch.object(model_files, "MODEL_PT_SHA256", hashlib.sha256(fresh_payload).hexdigest()),
                patch("culvia.model_files.hf_hub_url", return_value="https://example.test/model.pt"),
                patch("culvia.model_files.requests.get", side_effect=responses) as request,
            ):
                result = model_files.download_model_pt_with_progress(5, 5)
                result_bytes = Path(result).read_bytes()

        self.assertEqual(result_bytes, fresh_payload)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[0].kwargs["headers"]["Range"], "bytes=4-")
        self.assertNotIn("Range", request.call_args_list[1].kwargs["headers"])

    def test_core_preparation_replaces_mismatched_cached_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "model.pt"
            model_path.write_bytes(b"tampered")
            trusted_path = Path(tmp) / "trusted.pt"
            trusted_path.write_bytes(b"trusted")
            digest = model_files.file_sha256(trusted_path)
            with (
                patch(
                    "culvia.model_files.get_model_cache_status",
                    return_value={
                        "missing_files": ["model.pt"],
                        "model_file": str(model_path),
                        "integrity_state": model_files.INTEGRITY_STATE_MISMATCH,
                    },
                ),
                patch.object(model_files, "MODEL_PT_SHA256", digest),
                patch("culvia.model_files.download_hf_file") as download,
            ):
                model_files.ensure_model_files()

        download.assert_called_once_with("model.pt", 5, 5, None)

    def test_failed_core_model_download_integrity_is_fail_closed(self) -> None:
        class FakeResponse:
            status_code = 200
            headers = {"content-length": "8"}

            def raise_for_status(self) -> None:
                return None

            def iter_content(self, chunk_size: int):
                self.chunk_size = chunk_size
                yield b"tampered"

        with tempfile.TemporaryDirectory() as tmp:
            app_cache = Path(tmp)
            (app_cache / "model.pt").write_bytes(b"cached-tampered")
            with (
                patch.object(model_files, "APP_MODEL_CACHE_DIR", app_cache),
                patch.object(model_files, "MODEL_PT_SHA256", "0" * 64),
                patch("culvia.model_files.hf_hub_url", return_value="https://example.test/model.pt") as hub_url,
                patch("culvia.model_files.requests.get", return_value=FakeResponse()),
            ):
                with self.assertRaises(TranslatableRuntimeError):
                    model_files.download_model_pt_with_progress(5, 5)

            self.assertFalse((app_cache / "model.pt").exists())
            self.assertFalse((app_cache / "model.pt.part").exists())
            hub_url.assert_called_once_with(
                repo_id=model_files.MODEL_ID,
                filename="model.pt",
                revision=model_files.MODEL_REVISION,
            )

    def test_clip_preparation_pins_revision_and_verifies_safetensors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            weight_path = Path(tmp) / model_files.CLIP_REFERENCE_WEIGHT_FILENAME
            weight_path.write_bytes(b"safe-clip")
            digest = model_files.file_sha256(weight_path)

            def downloaded_path(*args: object, **kwargs: object) -> str:
                filename = str(args[3])
                return str(
                    weight_path if filename == model_files.CLIP_REFERENCE_WEIGHT_FILENAME else Path(tmp) / filename
                )

            with (
                patch.object(model_files, "APP_MODEL_CACHE_DIR", Path(tmp) / "app-cache"),
                patch(
                    "culvia.model_files.get_clip_reference_cache_status",
                    return_value={"missing_files": model_files.CLIP_REFERENCE_REQUIRED_CACHE_FILES},
                ),
                patch("culvia.model_files.download_hf_repo_file", side_effect=downloaded_path) as download,
                patch.object(model_files, "CLIP_REFERENCE_WEIGHT_SHA256", digest),
            ):
                model_files.ensure_clip_reference_model_files()

        self.assertEqual(download.call_count, len(model_files.CLIP_REFERENCE_REQUIRED_CACHE_FILES))
        self.assertTrue(
            all(
                call.kwargs["revision"] == model_files.CLIP_REFERENCE_MODEL_REVISION for call in download.call_args_list
            )
        )

    def test_clip_cache_status_ignores_unpinned_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = root / "hf" / "hub" / model_files.CLIP_REFERENCE_MODEL_REPO_DIR / "snapshots" / "moving-main"
            snapshot.mkdir(parents=True)
            for filename in model_files.CLIP_REFERENCE_REQUIRED_CACHE_FILES:
                (snapshot / filename).write_bytes(b"untrusted")

            with patch.dict(os.environ, {"HF_HOME": str(root / "hf")}, clear=False):
                status = model_files.get_clip_reference_cache_status()

        self.assertFalse(status["downloaded"])
        self.assertEqual(status["snapshot_path"], "")
        self.assertEqual(status["integrity_state"], model_files.INTEGRITY_STATE_MISSING)
        self.assertEqual(status["missing_files"], model_files.CLIP_REFERENCE_REQUIRED_CACHE_FILES)

    def test_valid_pinned_clip_cache_is_ready_offline_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = (
                root
                / "hf"
                / "hub"
                / model_files.CLIP_REFERENCE_MODEL_REPO_DIR
                / "snapshots"
                / model_files.CLIP_REFERENCE_MODEL_REVISION
            )
            snapshot.mkdir(parents=True)
            for filename in model_files.CLIP_REFERENCE_REQUIRED_CACHE_FILES:
                (snapshot / filename).write_bytes(
                    b"safe" if filename == model_files.CLIP_REFERENCE_WEIGHT_FILENAME else b"ok"
                )
            digest = model_files.file_sha256(snapshot / model_files.CLIP_REFERENCE_WEIGHT_FILENAME)

            with (
                patch.object(model_files, "APP_MODEL_CACHE_DIR", root / "app-cache"),
                patch.dict(os.environ, {"HF_HOME": str(root / "hf")}, clear=False),
                patch.object(model_files, "CLIP_REFERENCE_WEIGHT_SHA256", digest),
                patch("culvia.model_files.download_hf_repo_file") as download,
            ):
                cold = model_files.get_clip_reference_cache_status()
                model_files.ensure_clip_reference_model_files()
                status = model_files.get_clip_reference_cache_status()

        self.assertFalse(cold["downloaded"])
        self.assertEqual(cold["integrity_state"], model_files.INTEGRITY_STATE_NOT_CHECKED)
        self.assertTrue(status["downloaded"])
        self.assertFalse(status["partial"])
        self.assertEqual(status["integrity_state"], model_files.INTEGRITY_STATE_VERIFIED)
        download.assert_not_called()

    def test_corrupt_clip_cache_stays_not_ready_when_offline_repair_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot = (
                root
                / "hf"
                / "hub"
                / model_files.CLIP_REFERENCE_MODEL_REPO_DIR
                / "snapshots"
                / model_files.CLIP_REFERENCE_MODEL_REVISION
            )
            snapshot.mkdir(parents=True)
            for filename in model_files.CLIP_REFERENCE_REQUIRED_CACHE_FILES:
                (snapshot / filename).write_bytes(
                    b"corrupt" if filename == model_files.CLIP_REFERENCE_WEIGHT_FILENAME else b"ok"
                )

            with (
                patch.object(model_files, "APP_MODEL_CACHE_DIR", root / "app-cache"),
                patch.dict(os.environ, {"HF_HOME": str(root / "hf")}, clear=False),
                patch("culvia.model_files.download_hf_repo_file", side_effect=ConnectionError("offline")) as download,
            ):
                before = model_files.get_clip_reference_cache_status()
                with self.assertRaises(ConnectionError):
                    model_files.ensure_clip_reference_model_files()
                after = model_files.get_clip_reference_cache_status()

        self.assertEqual(before["integrity_state"], model_files.INTEGRITY_STATE_NOT_CHECKED)
        self.assertEqual(after["integrity_state"], model_files.INTEGRITY_STATE_MISMATCH)
        for status in (before, after):
            self.assertFalse(status["downloaded"])
            self.assertTrue(status["partial"])
            self.assertIn(model_files.CLIP_REFERENCE_WEIGHT_FILENAME, status["missing_files"])
        self.assertTrue(download.call_args.kwargs["force_download"])

    def test_clip_preparation_force_downloads_mismatched_cached_weight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp)
            weight_path = snapshot / model_files.CLIP_REFERENCE_WEIGHT_FILENAME
            weight_path.write_bytes(b"trusted-clip")
            digest = model_files.file_sha256(weight_path)
            weight_path.write_bytes(b"tampered-clip")

            def repair_weight(*_args: object, **_kwargs: object) -> str:
                weight_path.write_bytes(b"trusted-clip")
                return str(weight_path)

            with (
                patch.object(model_files, "APP_MODEL_CACHE_DIR", Path(tmp) / "app-cache"),
                patch(
                    "culvia.model_files.get_clip_reference_cache_status",
                    return_value={
                        "missing_files": [model_files.CLIP_REFERENCE_WEIGHT_FILENAME],
                        "snapshot_path": str(snapshot),
                        "integrity_state": model_files.INTEGRITY_STATE_MISMATCH,
                    },
                ),
                patch("culvia.model_files.download_hf_repo_file", side_effect=repair_weight) as download,
                patch.object(model_files, "CLIP_REFERENCE_WEIGHT_SHA256", digest),
            ):
                model_files.ensure_clip_reference_model_files()

        download.assert_called_once()
        self.assertTrue(download.call_args.kwargs["force_download"])
        self.assertEqual(download.call_args.kwargs["revision"], model_files.CLIP_REFERENCE_MODEL_REVISION)

    def test_clip_preparation_rejects_second_integrity_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            weight_path = Path(tmp) / model_files.CLIP_REFERENCE_WEIGHT_FILENAME
            weight_path.write_bytes(b"still-corrupt")
            with (
                patch.object(model_files, "APP_MODEL_CACHE_DIR", Path(tmp) / "app-cache"),
                patch(
                    "culvia.model_files.get_clip_reference_cache_status",
                    return_value={
                        "missing_files": [model_files.CLIP_REFERENCE_WEIGHT_FILENAME],
                        "snapshot_path": tmp,
                        "integrity_state": model_files.INTEGRITY_STATE_MISMATCH,
                    },
                ),
                patch("culvia.model_files.download_hf_repo_file", return_value=str(weight_path)) as download,
            ):
                with self.assertRaises(TranslatableRuntimeError) as caught:
                    model_files.ensure_clip_reference_model_files()

        self.assertEqual(caught.exception.text["key"], "error.modelIntegrityFailed")
        self.assertTrue(download.call_args.kwargs["force_download"])


if __name__ == "__main__":
    unittest.main()
