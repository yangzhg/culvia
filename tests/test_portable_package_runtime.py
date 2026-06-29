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

    def test_wait_for_backend_shutdown_returns_when_health_stops(self) -> None:
        with (
            patch.object(check_portable_package_runtime, "backend_responds", side_effect=[True, False]),
            patch.object(check_portable_package_runtime.time, "sleep") as sleep,
        ):
            detail = check_portable_package_runtime.wait_for_backend_shutdown(
                "http://127.0.0.1:12345",
                timeout=5.0,
                delay=0.1,
            )

        self.assertEqual(detail, "")
        self.assertEqual(sleep.call_count, 1)

    def test_wait_for_backend_shutdown_reports_persistent_health_response(self) -> None:
        with (
            patch.object(check_portable_package_runtime, "backend_responds", return_value=True),
            patch.object(check_portable_package_runtime.time, "sleep") as sleep,
            patch.object(
                check_portable_package_runtime.time,
                "monotonic",
                side_effect=[0.0, 0.0, 0.5, 1.1],
            ),
        ):
            detail = check_portable_package_runtime.wait_for_backend_shutdown(
                "http://127.0.0.1:12345",
                timeout=1.0,
                delay=0.1,
            )

        self.assertIn("backend still answered http://127.0.0.1:12345/health after 1.0s", detail)
        self.assertEqual(sleep.call_count, 2)

    def test_windows_sqlite_cleanup_lock_is_nonblocking_after_successful_shutdown(self) -> None:
        cleanup_error = (
            "could not remove temporary directory C:\\Temp\\fixture: [WinError 32] "
            "The process cannot access the file because it is being used by another process: "
            "'C:\\Temp\\fixture\\basic-technical-smoke\\state\\culvia_scores.sqlite'"
        )

        self.assertTrue(
            check_portable_package_runtime.cleanup_error_is_nonblocking(
                spec=check_portable_package_runtime.WINDOWS_SPEC,
                cleanup_error=cleanup_error,
                backend_shutdown_error="",
                returncode=0,
            )
        )

    def test_cleanup_lock_still_blocks_when_backend_shutdown_failed(self) -> None:
        cleanup_error = "[WinError 32] culvia_scores.sqlite"

        self.assertFalse(
            check_portable_package_runtime.cleanup_error_is_nonblocking(
                spec=check_portable_package_runtime.WINDOWS_SPEC,
                cleanup_error=cleanup_error,
                backend_shutdown_error="backend still answered /health",
                returncode=0,
            )
        )

    def test_cleanup_lock_still_blocks_for_linux_runtime(self) -> None:
        cleanup_error = "[WinError 32] culvia_scores.sqlite"

        self.assertFalse(
            check_portable_package_runtime.cleanup_error_is_nonblocking(
                spec=check_portable_package_runtime.LINUX_SPEC,
                cleanup_error=cleanup_error,
                backend_shutdown_error="",
                returncode=0,
            )
        )


if __name__ == "__main__":
    unittest.main()
