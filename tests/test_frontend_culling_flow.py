from __future__ import annotations

import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendCullingFlowTests(unittest.TestCase):
    def test_selection_index_helpers_do_not_loop_or_skip_filtered_photos(self) -> None:
        script = textwrap.dedent(
            """
            const fs = require("fs");
            const vm = require("vm");
            const context = { console };
            context.window = context;
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/culling_flow.js", "utf8"), context);

            const flow = context.window.CulviaCullingFlow;
            const photos = [{ fileId: "a" }, { fileId: "b" }, { fileId: "c" }];
            if (flow.nextIndexByDelta(photos, 0, -1) !== 0) throw new Error("left edge should not loop");
            if (flow.nextIndexByDelta(photos, 2, 1) !== 2) throw new Error("right edge should not loop");
            if (flow.nextIndexByDelta(photos, 1, 1) !== 2) throw new Error("normal next failed");
            if (flow.nextIndexAfterMark(photos, 1, "b", false) !== 1) throw new Error("mark should preserve by default");
            if (flow.nextIndexAfterMark(photos, 1, "b", true) !== 2) throw new Error("advance should move to next retained photo");
            if (flow.nextIndexAfterMark(photos, 2, "c", true) !== 2) throw new Error("advance should stop at end");

            const filteredAfterMark = [{ fileId: "a" }, { fileId: "c" }];
            if (flow.nextIndexAfterMark(filteredAfterMark, 1, "b", true) !== 1) {
              throw new Error("removed photo should leave selection on the replacement row");
            }
            if (flow.nextIndexAfterMark(filteredAfterMark, 99, "missing", true) !== 1) {
              throw new Error("fallback index should clamp to last row");
            }
            if (flow.nextIndexAfterMark([], 1, "b", true) !== 0) throw new Error("empty list should select zero");

            const range = flow.rangeFileIds(photos, "a", "c");
            if (range.join(",") !== "a,b,c") throw new Error(`forward range failed: ${range.join(",")}`);
            const reverseRange = flow.rangeFileIds(photos, "c", "a");
            if (reverseRange.join(",") !== "a,b,c") throw new Error(`reverse range failed: ${reverseRange.join(",")}`);
            if (flow.rangeFileIds(photos, "missing", "a").length !== 0) throw new Error("missing anchor should return empty range");
            """
        )
        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
