from __future__ import annotations

import unittest
from pathlib import Path

from tools import release_smoke


ROOT = Path(__file__).resolve().parents[1]


class ReleaseSmokeTests(unittest.TestCase):
    def test_probe_cwd_is_outside_source_tree(self) -> None:
        probe_cwd = release_smoke.outside_source_tree_cwd(ROOT).resolve()

        self.assertNotEqual(probe_cwd, ROOT.resolve())
        self.assertNotIn(ROOT.resolve(), probe_cwd.parents)

    def test_project_output_path_resolves_relative_path_from_source_root(self) -> None:
        self.assertEqual(
            release_smoke.project_output_path(Path("dist/python"), ROOT),
            ROOT / "dist" / "python",
        )

    def test_project_output_path_keeps_absolute_path(self) -> None:
        absolute = release_smoke.outside_source_tree_cwd(ROOT) / "culvia-dist"

        self.assertEqual(release_smoke.project_output_path(absolute, ROOT), absolute)


if __name__ == "__main__":
    unittest.main()
