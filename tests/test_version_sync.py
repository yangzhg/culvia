from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from tools import check_version_sync


ROOT = Path(__file__).resolve().parents[1]


class VersionSyncTests(unittest.TestCase):
    def test_repository_versions_are_synchronized(self) -> None:
        versions = check_version_sync.collect_versions(ROOT)
        canonical = versions["pyproject.toml"]

        self.assertTrue(canonical)
        self.assertEqual(set(versions.values()), {canonical})
        self.assertEqual(check_version_sync.version_sync_errors(versions, tag=f"v{canonical}"), [])

    def test_mismatch_and_wrong_release_tag_fail_the_check(self) -> None:
        versions = {"pyproject.toml": "1.2.3", "desktop": "1.2.2"}

        errors = check_version_sync.version_sync_errors(versions, tag="v1.2.4")

        self.assertEqual(len(errors), 2)
        self.assertIn("desktop has version '1.2.2'", errors[0])
        self.assertIn("release tag 'v1.2.4'", errors[1])

    def test_non_semantic_canonical_version_fails_the_check(self) -> None:
        errors = check_version_sync.version_sync_errors({"pyproject.toml": "1.2", "desktop": "1.2"})

        self.assertEqual(errors, ["canonical version '1.2' must use stable semantic X.Y.Z form"])

    def test_cli_rejects_a_tag_that_does_not_match_the_repository(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            result = check_version_sync.main(["--root", str(ROOT), "--tag", "v9.9.9"])

        self.assertEqual(result, 1)
        self.assertIn("does not match canonical version", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
