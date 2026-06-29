from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from culvia.app_state import AppStateStore, create_initial_state
from culvia.source_service import (
    SourceCacheDependencies,
    apply_source_cache_state,
    filter_cache_to_folders,
    load_source_cache_action,
)


class SourceServiceTests(unittest.TestCase):
    def test_filter_cache_to_folders_keeps_rows_inside_selected_roots(self) -> None:
        source_df = pd.DataFrame(
            [
                {"file_id": "a", "path": "/photos/a.jpg"},
                {"file_id": "b", "path": "/outside/b.jpg"},
                {"file_id": "c", "path": ""},
            ]
        )

        filtered = filter_cache_to_folders(
            source_df,
            ["/photos"],
            path_matcher=lambda value, folders: bool(value) and any(value.startswith(folder) for folder in folders),
        )

        self.assertEqual(filtered["file_id"].tolist(), ["a"])
        self.assertIsNot(filtered, source_df)

    def test_filter_cache_to_folders_preserves_empty_or_unscoped_frames(self) -> None:
        source_df = pd.DataFrame([{"file_id": "a", "path": "/photos/a.jpg"}])
        empty_df = source_df.iloc[0:0]

        self.assertIs(filter_cache_to_folders(source_df, []), source_df)
        self.assertIs(filter_cache_to_folders(empty_df, ["/photos"]), empty_df)

    def test_load_source_cache_action_normalizes_payload_and_filters_folder_cache(self) -> None:
        cache_df = pd.DataFrame(
            [
                {"file_id": "inside", "path": "/photos/inside.jpg"},
                {"file_id": "outside", "path": "/outside/outside.jpg"},
            ]
        )
        calls: dict[str, object] = {}

        def load_cache_records(cache_path: str | Path) -> pd.DataFrame:
            calls["cache_path"] = str(cache_path)
            return cache_df.copy()

        result = load_source_cache_action(
            {
                "mode": "folders",
                "folders": [" /photos ", "/photos"],
                "cachePath": " /tmp/scores.sqlite ",
            },
            SourceCacheDependencies(
                default_cache_path="/tmp/default.sqlite",
                load_cache_records=load_cache_records,
                path_is_inside=lambda value, folders: value.startswith(tuple(folders)),
            ),
        )

        self.assertEqual(calls["cache_path"], "/tmp/scores.sqlite")
        self.assertEqual(result.request.mode, "folders")
        self.assertEqual(result.request.folders, ["/photos"])
        self.assertEqual(result.request.cache_path, "/tmp/scores.sqlite")
        self.assertEqual(result.scores_df["file_id"].tolist(), ["inside"])

    def test_load_source_cache_action_keeps_upload_cache_unfiltered(self) -> None:
        cache_df = pd.DataFrame(
            [
                {"file_id": "inside", "path": "/photos/inside.jpg"},
                {"file_id": "outside", "path": "/outside/outside.jpg"},
            ]
        )

        result = load_source_cache_action(
            {
                "mode": "uploads",
                "folders": ["/photos"],
                "uploadedPaths": ["/tmp/upload.jpg"],
                "cachePath": "/tmp/uploads.sqlite",
            },
            SourceCacheDependencies(
                default_cache_path="/tmp/default.sqlite",
                load_cache_records=lambda _cache_path: cache_df.copy(),
                path_is_inside=lambda _value, _folders: False,
            ),
        )

        self.assertEqual(result.request.mode, "uploads")
        self.assertEqual(result.request.uploaded_paths, ["/tmp/upload.jpg"])
        self.assertEqual(result.scores_df["file_id"].tolist(), ["inside", "outside"])

    def test_apply_source_cache_state_updates_injected_store_only(self) -> None:
        result = load_source_cache_action(
            {"mode": "folders", "folders": ["/photos"], "cachePath": "/tmp/current.sqlite"},
            SourceCacheDependencies(
                default_cache_path="/tmp/default.sqlite",
                load_cache_records=lambda _cache_path: pd.DataFrame([{"file_id": "a", "path": "/photos/a.jpg"}]),
                path_is_inside=lambda value, folders: value.startswith(tuple(folders)),
            ),
        )
        store = AppStateStore(
            create_initial_state(
                scores_df=pd.DataFrame(columns=["file_id", "path"]),
                default_photo_dirs=["/old"],
                default_cache_path="/tmp/old.sqlite",
                filter_defaults={},
                default_selected_models=["core"],
            )
        )
        with store.lock:
            store.data["sourcePreview"] = {"mode": "folders", "folders": ["/old"], "total": 12}

        apply_source_cache_state(store, result)

        with store.lock:
            self.assertEqual(store.data["scores_df"]["file_id"].tolist(), ["a"])
            self.assertEqual(store.data["source"]["mode"], "folders")
            self.assertEqual(store.data["source"]["folders"], ["/photos"])
            self.assertEqual(store.data["source"]["cachePath"], "/tmp/current.sqlite")
            self.assertNotIn("sourcePreview", store.data)

    def test_load_source_cache_action_rejects_non_sqlite_cache_path(self) -> None:
        with self.assertRaisesRegex(ValueError, "SQLite"):
            load_source_cache_action(
                {"cachePath": "/tmp/scores.csv"},
                SourceCacheDependencies(
                    default_cache_path="/tmp/default.sqlite",
                    load_cache_records=lambda _cache_path: pd.DataFrame(),
                ),
            )


if __name__ == "__main__":
    unittest.main()
