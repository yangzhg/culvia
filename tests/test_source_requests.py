from __future__ import annotations

import sys
import unittest
from pathlib import Path

from culvia.source_requests import (
    normalize_cache_path,
    normalize_source_folders,
    normalize_source_mode,
    normalize_uploaded_path_values,
    source_request_from_payload,
)


class SourceRequestTests(unittest.TestCase):
    def test_normalize_source_mode_falls_back_to_folders(self) -> None:
        self.assertEqual(normalize_source_mode("uploads"), "uploads")
        self.assertEqual(normalize_source_mode("unknown"), "folders")
        self.assertEqual(normalize_source_mode(None), "folders")

    def test_normalize_source_folders_trims_deduplicates_and_accepts_single_value(self) -> None:
        self.assertEqual(normalize_source_folders([" /a ", "", "/a", Path("/b")]), ["/a", "/b"])
        self.assertEqual(normalize_source_folders(" /single "), ["/single"])
        self.assertEqual(normalize_source_folders(" /a \n\n /b \n /a "), ["/a", "/b"])

    def test_normalize_source_folders_expands_and_removes_redundant_children(self) -> None:
        home = str(Path.home())
        result = normalize_source_folders(["~/photos/session", "~/photos", "~/photos/session/picks"])

        self.assertEqual(result, [str(Path(home, "photos").absolute())])

    @unittest.skipUnless(sys.platform == "darwin", "macOS exposes /var as a /private/var alias")
    def test_normalize_source_folders_deduplicates_macos_var_aliases_but_preserves_first_text(self) -> None:
        result = normalize_source_folders(["/var/folders", "/private/var/folders/example"])

        self.assertEqual(result, ["/var/folders"])

    def test_normalize_uploaded_path_values_preserves_raw_values_for_sanitizer(self) -> None:
        path = Path("/tmp/a.jpg")
        self.assertEqual(normalize_uploaded_path_values(path), [path])
        self.assertEqual(normalize_uploaded_path_values(["/a.jpg", "/b.jpg"]), ["/a.jpg", "/b.jpg"])
        self.assertEqual(normalize_uploaded_path_values(None), [])

    def test_normalize_cache_path_defaults_and_rejects_unknown_suffix(self) -> None:
        self.assertEqual(normalize_cache_path("", default_cache_path="/tmp/default.sqlite"), "/tmp/default.sqlite")

        with self.assertRaisesRegex(ValueError, "SQLite"):
            normalize_cache_path("/tmp/notes.txt", default_cache_path="/tmp/default.sqlite")

        with self.assertRaisesRegex(ValueError, "SQLite"):
            normalize_cache_path("/tmp/scores.csv", default_cache_path="/tmp/default.sqlite")

    def test_source_request_from_payload_normalizes_all_fields(self) -> None:
        source = source_request_from_payload(
            {
                "mode": "uploads",
                "folders": [" /photos ", "/photos"],
                "cachePath": " /tmp/scores.sqlite3 ",
                "uploadedPaths": ["/tmp/a.jpg"],
            },
            default_cache_path="/tmp/default.sqlite",
        )

        self.assertEqual(source.mode, "uploads")
        self.assertEqual(source.folders, [str(Path("/photos").absolute())])
        self.assertEqual(source.cache_path, "/tmp/scores.sqlite3")
        self.assertEqual(source.uploaded_paths, ["/tmp/a.jpg"])


if __name__ == "__main__":
    unittest.main()
