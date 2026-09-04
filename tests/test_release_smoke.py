from __future__ import annotations

import tempfile
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

    def test_module_graph_strips_cache_bust_queries_and_fragments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            web_dir = Path(tmp)
            (web_dir / "main.js").write_text(
                'import "./app.js?v=score-provenance";\nimport "https://example.test/external.js";\n',
                encoding="utf-8",
            )
            (web_dir / "app.js").write_text(
                'import "./locales/en.js?v=score-provenance#messages";\n',
                encoding="utf-8",
            )
            (web_dir / "locales").mkdir()
            (web_dir / "locales" / "en.js").write_text("export {};\n", encoding="utf-8")

            files = release_smoke.module_graph_files(web_dir, "main.js")

        self.assertEqual(files, {"main.js", "app.js", "locales/en.js"})


if __name__ == "__main__":
    unittest.main()
