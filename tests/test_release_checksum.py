from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

from tools import write_release_checksum


@contextmanager
def windows_text_defaults() -> Iterator[None]:
    original_open = Path.open

    def open_with_windows_newlines(path: Path, mode: str = "r", **kwargs: Any):
        # Use real text I/O translation for the Windows default, while honoring explicit newlines.
        if mode == "w" and kwargs.get("newline") is None:
            kwargs["newline"] = "\r\n"
        return original_open(path, mode, **kwargs)

    with patch.object(Path, "open", open_with_windows_newlines):
        yield


class ReleaseChecksumTests(unittest.TestCase):
    def test_default_checksum_path_preserves_multi_suffix_artifact_name(self) -> None:
        path = Path("dist/linux/culvia-0.1.0-linux-x86_64-unknown-linux-gnu.tar.gz")

        self.assertEqual(
            write_release_checksum.default_checksum_path(path),
            Path("dist/linux/culvia-0.1.0-linux-x86_64-unknown-linux-gnu.tar.gz.sha256"),
        )

    def test_write_checksum_creates_standard_sha256_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "culvia.zip"
            artifact.write_bytes(b"release-payload")

            payload = write_release_checksum.write_checksum(artifact=artifact)

            expected = hashlib.sha256(b"release-payload").hexdigest()
            checksum_path = Path(payload["checksumPath"])

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["sha256"], expected)
            self.assertEqual(checksum_path.name, "culvia.zip.sha256")
            self.assertEqual(checksum_path.read_bytes(), f"{expected}  culvia.zip\n".encode("utf-8"))

    def test_write_checksum_uses_utf8_lf_with_windows_text_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, windows_text_defaults():
            root = Path(tmp)
            control = root / "text-default.txt"
            control.write_text("text\n", encoding="utf-8")
            self.assertEqual(control.read_bytes(), b"text\r\n")

            for filename in ("culvia.zip", "Culvia 照片.zip"):
                for output in (None, root / "checksums" / "release.sha256"):
                    with self.subTest(filename=filename, output=output):
                        artifact = root / filename
                        artifact.write_bytes(b"release-payload")

                        payload = write_release_checksum.write_checksum(artifact=artifact, output=output)

                        expected = hashlib.sha256(b"release-payload").hexdigest()
                        self.assertTrue(payload["ok"])
                        self.assertEqual(
                            Path(payload["checksumPath"]).read_bytes(),
                            f"{expected}  {filename}\n".encode("utf-8"),
                        )

    def assert_verifier_checks_checksum(self, command: list[str]) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "Culvia 照片.zip"
            artifact.write_bytes(b"release-payload")
            with windows_text_defaults():
                payload = write_release_checksum.write_checksum(artifact=artifact)
            command = [*command, "-c", Path(payload["checksumPath"]).name]

            result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=15, check=False)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("OK", result.stdout)

            artifact.write_bytes(b"changed-payload")
            result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=15, check=False)

            self.assertNotEqual(result.returncode, 0, "checksum verification must detect changed artifacts")

    @unittest.skipUnless(shutil.which("shasum"), "shasum is unavailable")
    def test_checksum_is_verified_by_shasum(self) -> None:
        self.assert_verifier_checks_checksum(["shasum", "-a", "256"])

    @unittest.skipUnless(shutil.which("sha256sum"), "sha256sum is unavailable")
    def test_checksum_is_verified_by_sha256sum(self) -> None:
        self.assert_verifier_checks_checksum(["sha256sum"])

    def test_write_checksum_refuses_missing_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "missing.zip"

            payload = write_release_checksum.write_checksum(artifact=artifact)

        self.assertFalse(payload["ok"])
        self.assertIn("missing artifact", payload["issues"][0])

    def test_main_outputs_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "culvia.tar.gz"
            artifact.write_bytes(b"payload")
            stdout = StringIO()

            with redirect_stdout(stdout):
                result = write_release_checksum.main([str(artifact), "--json"])

        self.assertEqual(result, 0)
        self.assertTrue(json.loads(stdout.getvalue())["ok"])


if __name__ == "__main__":
    unittest.main()
