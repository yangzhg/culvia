from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from tools import write_release_checksum


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
            checksum_text = checksum_path.read_text(encoding="utf-8")

            self.assertTrue(payload["ok"])
            self.assertEqual(payload["sha256"], expected)
            self.assertEqual(checksum_path.name, "culvia.zip.sha256")
            self.assertEqual(checksum_text, f"{expected}  culvia.zip\n")

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
