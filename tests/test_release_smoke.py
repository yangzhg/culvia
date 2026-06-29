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


if __name__ == "__main__":
    unittest.main()
