from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from PIL import Image
from starlette.testclient import TestClient

import culvia_app
from culvia import scoring
from culvia.app_state import AppStateStore, create_initial_state
from culvia.runtime_config import (
    DEFAULT_THUMBNAIL_CACHE_MAX_BYTES,
    DEFAULT_THUMBNAIL_CACHE_MAX_FILES,
    DEFAULT_THUMBNAIL_MAX_SIZE,
    RuntimeConfig,
)
from culvia.web_app import create_runtime_state_store


def make_image(path: Path) -> Path:
    Image.new("RGB", (32, 24), (96, 128, 180)).save(path)
    return path


class RuntimeConfigTests(unittest.TestCase):
    def test_runtime_config_reads_current_settings_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            web_dir = root / "web"
            upload_dir = root / "uploads"
            thumb_dir = root / "thumbs"
            cache_path = root / "scores.sqlite"
            receipts_path = root / "delivery.sqlite"
            photo_dir_a = root / "photos-a"
            photo_dir_b = root / "photos-b"
            web_dir.mkdir()

            with patch.dict(
                os.environ,
                {
                    "CULVIA_WEB_DIR": str(web_dir),
                    "CULVIA_UPLOAD_DIR": str(upload_dir),
                    "CULVIA_THUMBNAIL_CACHE_DIR": str(thumb_dir),
                    "CULVIA_THUMBNAIL_CACHE_MAX_BYTES": "123456789",
                    "CULVIA_THUMBNAIL_CACHE_MAX_FILES": "4321",
                    "CULVIA_CACHE_PATH": str(cache_path),
                    "CULVIA_EXPORT_RECEIPTS_PATH": str(receipts_path),
                    "CULVIA_PHOTO_DIRS": os.pathsep.join([str(photo_dir_a), str(photo_dir_b)]),
                },
                clear=False,
            ):
                config = RuntimeConfig.from_settings()

        self.assertEqual(config.web_dir, web_dir)
        self.assertEqual(config.upload_cache_dir, upload_dir)
        self.assertEqual(config.thumbnail_cache_dir, thumb_dir)
        self.assertEqual(config.default_cache_path, str(cache_path))
        self.assertEqual(config.export_receipts_path, receipts_path)
        self.assertEqual(config.resolved_export_receipts_path, receipts_path)
        self.assertEqual(config.default_photo_dirs, (str(photo_dir_a), str(photo_dir_b)))
        self.assertEqual(config.thumbnail_max_size, DEFAULT_THUMBNAIL_MAX_SIZE)
        self.assertEqual(config.thumbnail_cache_max_bytes, 123456789)
        self.assertEqual(config.thumbnail_cache_max_files, 4321)

    def test_receipt_path_is_independent_of_source_cache_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, {"CULVIA_DATA_DIR": str(root)}, clear=True):
                config = RuntimeConfig.from_settings()
            changed = config.with_paths(default_cache_path=root / "another" / "scores.sqlite")
            self.assertEqual(changed.resolved_export_receipts_path, root / "culvia_export_receipts.sqlite")
            explicit = changed.with_paths(export_receipts_path=root / "custom.sqlite")
            self.assertEqual(explicit.resolved_export_receipts_path, root / "custom.sqlite")

    def test_thumbnail_cache_limits_support_defaults_zero_and_invalid_environment(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            defaults = RuntimeConfig.from_settings()
        with patch.dict(
            os.environ,
            {
                "CULVIA_THUMBNAIL_CACHE_MAX_BYTES": "0",
                "CULVIA_THUMBNAIL_CACHE_MAX_FILES": "0",
            },
            clear=True,
        ):
            disabled = RuntimeConfig.from_settings()
        with patch.dict(
            os.environ,
            {
                "CULVIA_THUMBNAIL_CACHE_MAX_BYTES": "not-a-number",
                "CULVIA_THUMBNAIL_CACHE_MAX_FILES": "-1",
            },
            clear=True,
        ):
            invalid = RuntimeConfig.from_settings()

        self.assertEqual(defaults.thumbnail_cache_max_bytes, DEFAULT_THUMBNAIL_CACHE_MAX_BYTES)
        self.assertEqual(defaults.thumbnail_cache_max_files, DEFAULT_THUMBNAIL_CACHE_MAX_FILES)
        self.assertEqual(disabled.thumbnail_cache_max_bytes, 0)
        self.assertEqual(disabled.thumbnail_cache_max_files, 0)
        self.assertEqual(invalid.thumbnail_cache_max_bytes, DEFAULT_THUMBNAIL_CACHE_MAX_BYTES)
        self.assertEqual(invalid.thumbnail_cache_max_files, DEFAULT_THUMBNAIL_CACHE_MAX_FILES)

    def test_with_paths_overrides_thumbnail_cache_limits_and_rejects_negative_values(self) -> None:
        config = RuntimeConfig(
            web_dir=Path("web"),
            upload_cache_dir=Path("uploads"),
            thumbnail_cache_dir=Path("thumbs"),
            default_cache_path="scores.sqlite",
            default_photo_dirs=(),
        )

        disabled = config.with_paths(thumbnail_cache_max_bytes=0, thumbnail_cache_max_files=0)

        self.assertEqual(disabled.thumbnail_cache_max_bytes, 0)
        self.assertEqual(disabled.thumbnail_cache_max_files, 0)
        with self.assertRaisesRegex(ValueError, "byte limit"):
            config.with_paths(thumbnail_cache_max_bytes=-1)
        with self.assertRaisesRegex(ValueError, "file limit"):
            config.with_paths(thumbnail_cache_max_files=-1)

    def test_package_web_app_import_does_not_import_scoring_runtime(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import culvia.web_app; print('culvia.scoring' in sys.modules)",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.stdout.strip(), "False")

    def test_create_runtime_state_store_uses_config_defaults(self) -> None:
        config = RuntimeConfig(
            web_dir=Path("web"),
            upload_cache_dir=Path("uploads"),
            thumbnail_cache_dir=Path("thumbs"),
            default_cache_path="/tmp/runtime.sqlite",
            default_photo_dirs=("/photos/a", "/photos/b"),
        )
        seen_cache_paths: list[str] = []

        def load_scores(cache_path: str) -> pd.DataFrame:
            seen_cache_paths.append(cache_path)
            return pd.DataFrame({"file_id": ["a"]})

        store = create_runtime_state_store(
            config,
            load_scores=load_scores,
            filter_defaults={"limit": 42},
            default_selected_models=["core"],
        )

        self.assertEqual(seen_cache_paths, ["/tmp/runtime.sqlite"])
        self.assertEqual(store.data["source"]["cachePath"], "/tmp/runtime.sqlite")
        self.assertEqual(store.data["source"]["folders"], ["/photos/a", "/photos/b"])
        self.assertEqual(store.data["filters"]["limit"], 42)
        self.assertEqual(store.data["models"]["selected"], ["core"])

    def test_create_runtime_state_store_restores_persisted_source_config(self) -> None:
        config = RuntimeConfig(
            web_dir=Path("web"),
            upload_cache_dir=Path("uploads"),
            thumbnail_cache_dir=Path("thumbs"),
            default_cache_path="/tmp/runtime.sqlite",
            default_photo_dirs=("/photos/default",),
        )

        store = create_runtime_state_store(
            config,
            load_scores=lambda _cache_path: pd.DataFrame({"file_id": ["a"]}),
            load_source_config=lambda _cache_path: {
                "mode": "folders",
                "folders": ["/photos/restored"],
                "cachePath": "/tmp/runtime.sqlite",
            },
            filter_defaults={},
            default_selected_models=["core"],
        )

        self.assertEqual(store.data["source"]["folders"], ["/photos/restored"])
        self.assertEqual(store.data["sourcePreview"]["folders"], ["/photos/restored"])

    def test_create_runtime_state_store_respects_persisted_empty_source(self) -> None:
        config = RuntimeConfig(
            web_dir=Path("web"),
            upload_cache_dir=Path("uploads"),
            thumbnail_cache_dir=Path("thumbs"),
            default_cache_path="/tmp/runtime.sqlite",
            default_photo_dirs=("/photos/default",),
        )

        store = create_runtime_state_store(
            config,
            load_scores=lambda _cache_path: pd.DataFrame(),
            load_source_config=lambda _cache_path: {"mode": "folders", "folders": []},
            filter_defaults={},
            default_selected_models=[],
        )

        self.assertEqual(store.data["source"]["folders"], [])

    def test_create_app_runtime_config_controls_static_upload_and_thumbnail_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            web_dir = root / "web"
            upload_dir = root / "uploads"
            thumb_dir = root / "thumbs"
            source_dir = root / "photos"
            web_dir.mkdir()
            source_dir.mkdir()
            (web_dir / "index.html").write_text("<!doctype html><title>custom</title>", encoding="utf-8")
            source_image = make_image(source_dir / "source.jpg")
            cache_path = str(root / "scores.sqlite")
            source_df = pd.DataFrame(
                [
                    {
                        "file_id": "image-1",
                        "path": str(source_image),
                        "folder": str(source_dir),
                        "filename": source_image.name,
                        "error": "",
                        "overall_0_10": 8.0,
                    }
                ]
            )
            store = AppStateStore(
                create_initial_state(
                    scores_df=source_df,
                    default_photo_dirs=[str(source_dir)],
                    default_cache_path=cache_path,
                    filter_defaults=culvia_app.FILTER_DEFAULTS,
                    default_selected_models=[scoring.MODEL_CORE_AESTHETIC],
                )
            )
            config = RuntimeConfig(
                web_dir=web_dir,
                upload_cache_dir=upload_dir,
                thumbnail_cache_dir=thumb_dir,
                default_cache_path=cache_path,
                default_photo_dirs=(str(source_dir),),
                thumbnail_max_size=96,
            )
            web_app = culvia_app.create_app(store, runtime_config=config)
            self.addCleanup(web_app.state.thumbnail_coordinator.close)
            client = TestClient(web_app)

            home = client.get("/")
            upload = client.post("/api/upload", files=[("files", ("keep.jpg", b"fake image bytes", "image/jpeg"))])
            thumbnail = client.get("/api/thumbnail", params={"file_id": "image-1"})

            self.assertEqual(home.status_code, 200)
            self.assertIn("custom", home.text)
            self.assertEqual(upload.status_code, 200)
            saved_path = Path(upload.json()["saved"][0])
            self.assertTrue(saved_path.is_relative_to(upload_dir))
            self.assertTrue(saved_path.exists())
            self.assertEqual(thumbnail.status_code, 200)
            self.assertTrue(thumbnail.content.startswith(b"\xff\xd8"))
            self.assertRegex(thumbnail.headers["etag"], r'^"[0-9a-f]{40}"$')
            self.assertTrue(thumb_dir.exists())
            cached_thumbnail = next(thumb_dir.glob("*.jpg"))
            with Image.open(cached_thumbnail) as image:
                self.assertLessEqual(max(image.size), config.thumbnail_max_size)

    def test_create_app_applies_configured_thumbnail_cache_limits_on_startup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            thumb_dir = root / "thumbs"
            thumb_dir.mkdir()
            old_timestamp = 1_000_000
            for index in range(3):
                cached = thumb_dir / f"{index:040x}.jpg"
                cached.write_bytes(b"jpeg")
                os.utime(cached, (old_timestamp + index, old_timestamp + index))
            config = RuntimeConfig(
                web_dir=Path("web"),
                upload_cache_dir=root / "uploads",
                thumbnail_cache_dir=thumb_dir,
                default_cache_path=str(root / "scores.sqlite"),
                default_photo_dirs=(),
                thumbnail_cache_max_bytes=0,
                thumbnail_cache_max_files=2,
            )
            store = AppStateStore(
                create_initial_state(
                    scores_df=pd.DataFrame(),
                    default_photo_dirs=[],
                    default_cache_path=config.default_cache_path,
                    filter_defaults=culvia_app.FILTER_DEFAULTS,
                    default_selected_models=[],
                )
            )

            with TestClient(culvia_app.create_app(store, runtime_config=config)) as client:
                self.assertEqual(client.get("/health").status_code, 200)

            self.assertEqual(len(list(thumb_dir.glob("*.jpg"))), 1)


if __name__ == "__main__":
    unittest.main()
