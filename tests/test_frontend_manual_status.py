from __future__ import annotations

import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendManualStatusTests(unittest.TestCase):
    def assert_js_passes(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            const fs = require("fs");
            const vm = require("vm");
            const context = {{ console }};
            context.window = context;
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/manual_status.js", "utf8"), context);

            const manualStatus = context.window.CulviaManualStatus;
            if (!manualStatus) throw new Error("module was not registered");

            {body}
            """
        )
        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_status_normalization_and_toggle(self) -> None:
        self.assert_js_passes(
            """
            if (manualStatus.normalizeStatus("pending") !== "hold") throw new Error("pending should normalize to hold");
            if (manualStatus.normalizeStatus("HOLD") !== "hold") throw new Error("case should normalize");
            if (manualStatus.normalizeStatus("unknown") !== "") throw new Error("unknown status should clear");

            if (manualStatus.toggledStatus("", "hold") !== "hold") throw new Error("empty hold should set hold");
            if (manualStatus.toggledStatus("hold", "hold") !== "") throw new Error("hold should toggle off");
            if (manualStatus.toggledStatus("pending", "hold") !== "") throw new Error("pending alias should toggle off");
            if (manualStatus.toggledStatus("reject", "hold") !== "hold") throw new Error("different status should switch");
            if (manualStatus.toggledStatus("pick", "") !== "") throw new Error("empty request should clear");
            """
        )

    def test_status_presentation_helpers(self) -> None:
        self.assert_js_passes(
            """
            if (manualStatus.statusClass("pick") !== "is-picked") throw new Error("pick class mismatch");
            if (manualStatus.statusClass("reject") !== "is-rejected") throw new Error("reject class mismatch");
            if (manualStatus.statusClass("hold") !== "is-pending") throw new Error("hold class mismatch");
            if (manualStatus.statusClass("") !== "is-unreviewed") throw new Error("empty class mismatch");

            if (manualStatus.statusIcon("pick") !== "check") throw new Error("pick icon mismatch");
            if (manualStatus.statusIcon("reject") !== "x") throw new Error("reject icon mismatch");
            if (manualStatus.statusIcon("hold") !== "clock") throw new Error("hold icon mismatch");
            if (manualStatus.statusIcon("") !== "") throw new Error("empty icon mismatch");

            if (manualStatus.stars(3) !== "★★★☆☆") throw new Error("star rendering mismatch");
            if (manualStatus.stars(9) !== "★★★★★") throw new Error("star upper clamp mismatch");
            if (manualStatus.stars(-2) !== "☆☆☆☆☆") throw new Error("star lower clamp mismatch");
            """
        )


if __name__ == "__main__":
    unittest.main()
