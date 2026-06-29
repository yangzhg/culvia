from __future__ import annotations

import sys
import unittest
from pathlib import Path

from culvia.path_semantics import is_same_or_child_path, path_identity_key, stable_path


class PathSemanticsTests(unittest.TestCase):
    def test_stable_path_does_not_resolve_symlink_aliases(self) -> None:
        path = stable_path("/tmp/../tmp")

        self.assertEqual(str(path), "/tmp")

    @unittest.skipUnless(sys.platform == "darwin", "macOS exposes /var as a /private/var alias")
    def test_stable_path_preserves_macos_var_alias(self) -> None:
        path = stable_path("/var/folders")

        self.assertTrue(str(path).startswith("/var/"))
        self.assertNotEqual(str(path), str(Path("/var/folders").resolve(strict=False)))

    @unittest.skipUnless(sys.platform == "darwin", "macOS exposes /var as a /private/var alias")
    def test_identity_key_collapses_macos_var_aliases_without_changing_stable_path(self) -> None:
        self.assertEqual(path_identity_key("/var/folders"), path_identity_key("/private/var/folders"))

    @unittest.skipUnless(sys.platform == "darwin", "macOS exposes /var as a /private/var alias")
    def test_same_or_child_path_accepts_macos_alias_parent(self) -> None:
        self.assertTrue(is_same_or_child_path("/private/var/folders/example", "/var/folders"))


if __name__ == "__main__":
    unittest.main()
