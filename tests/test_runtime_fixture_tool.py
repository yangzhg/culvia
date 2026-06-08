from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from culvia import scoring


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "prepare_runtime_fixture.py"


def load_tool_module():
    spec = importlib.util.spec_from_file_location("prepare_runtime_fixture", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load runtime fixture tool")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RuntimeFixtureToolTests(unittest.TestCase):
    def test_write_fixture_creates_images_cache_and_env(self) -> None:
        tool = load_tool_module()
        with tempfile.TemporaryDirectory() as tmp:
            payload = tool.write_fixture(Path(tmp) / "fixture", count=4, force=True)

            photo_dir = Path(payload["photoDir"])
            cache_path = Path(payload["cachePath"])
            rows = scoring.load_cache_records(cache_path)
            insights = scoring.load_analysis_insights(cache_path)
            self.assertEqual(payload["count"], 4)
            self.assertTrue(cache_path.exists())
            self.assertEqual(len(list(photo_dir.glob("*.jpg"))), 4)
            self.assertEqual(len(rows), 4)
            self.assertEqual(len(insights), 4)
            self.assertTrue(any(len(str(name)) > 90 for name in rows["filename"]))
            self.assertEqual(insights[0].analyzer_key, scoring.MODEL_LLM_REVIEW)
            self.assertEqual(
                {insight.file_id for insight in insights},
                set(rows["file_id"]),
            )
            self.assertGreater(len(insights[0].summary), 200)
            self.assertTrue(any(len(suggestion) > 180 for suggestion in insights[0].suggestions))
            self.assertIn("Retouch:", insights[0].suggestions[0])
            self.assertIn("CULVIA_CACHE_PATH", payload["env"])
            self.assertIn("CULVIA_PHOTO_DIRS", payload["env"])
            self.assertEqual(payload["env"]["CULVIA_CACHE_PATH"], str(cache_path))
            self.assertGreater(float(rows["recommendation_0_10"].dropna().iloc[0]), 0)

    def test_json_output_is_machine_readable(self) -> None:
        tool = load_tool_module()
        with tempfile.TemporaryDirectory() as tmp:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = tool.main(["--root", str(Path(tmp) / "fixture"), "--count", "2", "--force", "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(result, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 2)

    def test_shell_output_quotes_exports(self) -> None:
        tool = load_tool_module()
        with tempfile.TemporaryDirectory() as tmp:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = tool.main(["--root", str(Path(tmp) / "fixture"), "--count", "1", "--force", "--shell"])

        self.assertEqual(result, 0)
        self.assertIn("export CULVIA_CACHE_PATH='", stdout.getvalue())
        self.assertIn("export CULVIA_PHOTO_DIRS='", stdout.getvalue())

    def test_force_refuses_existing_unmarked_directory(self) -> None:
        tool = load_tool_module()
        with tempfile.TemporaryDirectory() as tmp:
            unsafe_root = Path(tmp)
            (unsafe_root / "keep.txt").write_text("do not delete", encoding="utf-8")

            with self.assertRaises(ValueError):
                tool.write_fixture(unsafe_root, count=1, force=True)

            self.assertTrue((unsafe_root / "keep.txt").exists())

    def test_force_allows_previous_marked_fixture_directory(self) -> None:
        tool = load_tool_module()
        with tempfile.TemporaryDirectory() as tmp:
            fixture_root = Path(tmp) / "fixture"
            first = tool.write_fixture(fixture_root, count=1, force=True)
            second = tool.write_fixture(fixture_root, count=2, force=True)

            self.assertEqual(first["count"], 1)
            self.assertEqual(second["count"], 2)
            self.assertTrue((fixture_root / tool.MARKER_NAME).exists())


if __name__ == "__main__":
    unittest.main()
