from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import check_portable_package_runtime


class PortablePackageRuntimeTests(unittest.TestCase):
    def test_remove_tree_retries_transient_windows_file_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "fixture"
            target.mkdir()
            (target / "culvia_scores.sqlite").write_text("locked", encoding="utf-8")
            original_rmtree = check_portable_package_runtime.shutil.rmtree
            calls = 0

            def flaky_rmtree(path: Path) -> None:
                nonlocal calls
                calls += 1
                if calls < 3:
                    raise PermissionError("locked")
                original_rmtree(path)

            with (
                patch.object(check_portable_package_runtime.shutil, "rmtree", side_effect=flaky_rmtree),
                patch.object(check_portable_package_runtime.time, "sleep") as sleep,
            ):
                detail = check_portable_package_runtime.remove_tree_with_retries(
                    target,
                    attempts=3,
                    delay=0.01,
                )

            self.assertEqual(detail, "")
            self.assertEqual(calls, 3)
            self.assertEqual(sleep.call_count, 2)
            self.assertFalse(target.exists())

    def test_remove_tree_reports_persistent_cleanup_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "fixture"
            target.mkdir()

            with (
                patch.object(check_portable_package_runtime.shutil, "rmtree", side_effect=PermissionError("locked")),
                patch.object(check_portable_package_runtime.time, "sleep") as sleep,
            ):
                detail = check_portable_package_runtime.remove_tree_with_retries(
                    target,
                    attempts=2,
                    delay=0.01,
                )

            self.assertIn("could not remove temporary directory", detail)
            self.assertIn("locked", detail)
            self.assertEqual(sleep.call_count, 1)


if __name__ == "__main__":
    unittest.main()
