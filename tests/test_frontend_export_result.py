from __future__ import annotations

import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendExportResultTests(unittest.TestCase):
    def test_export_result_normalizes_skipped_details(self) -> None:
        script = textwrap.dedent(
            """
            const fs = require("fs");
            const vm = require("vm");
            const context = { console };
            context.window = context;
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/export_result_data.js", "utf8"), context);
            vm.runInContext(fs.readFileSync("web/export_result.js", "utf8"), context);

            const view = context.window.CulviaExportResult;
            if (!context.window.CulviaExportResultData) throw new Error("data module was not registered");
            if (!view) throw new Error("module was not registered");

            const details = view.normalizeSkippedDetails(
              {
                skippedDetails: [
                  { path: "/photos/missing.jpg", reason: "missing", label: "源文件缺失", message: "not found" },
                  { path: "/photos/defaults.jpg" },
                ],
              },
            );
            if (details.length !== 2) throw new Error("skipped details should keep all entries");
            if (details[0].path !== "/photos/missing.jpg" || details[0].reason !== "missing" || details[0].label !== "源文件缺失") {
              throw new Error("explicit skipped detail should be preserved");
            }
            if (details[1].path !== "/photos/defaults.jpg" || details[1].reason !== "unknown" || details[1].label !== "未复制") {
              throw new Error("missing skipped detail metadata should use defaults");
            }
            if (details[1].message !== "") throw new Error("missing detail message should normalize to empty string");

            if (view.normalizeSkippedDetails({}).length !== 0) throw new Error("missing details should stay empty");
            """
        )
        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_export_result_normalizes_skipped_reason_summary(self) -> None:
        script = textwrap.dedent(
            """
            const fs = require("fs");
            const vm = require("vm");
            const context = { console };
            context.window = context;
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/export_result_data.js", "utf8"), context);
            vm.runInContext(fs.readFileSync("web/export_result.js", "utf8"), context);

            const view = context.window.CulviaExportResult;
            if (!context.window.CulviaExportResultData) throw new Error("data module was not registered");
            if (!view) throw new Error("module was not registered");

            const explicit = view.normalizeSkippedReasonSummary(
              { skippedReasonSummary: [{ reason: "missing", label: "源文件缺失", count: "2" }] },
              [],
            );
            if (explicit.length !== 1 || explicit[0].count !== 2 || explicit[0].label !== "源文件缺失") {
              throw new Error("explicit reason summary should be normalized");
            }

            const fromDetails = view.normalizeSkippedReasonSummary({}, [
              { path: "/a.jpg", reason: "unknown" },
              { path: "/b.jpg", reason: "unknown" },
            ]);
            if (fromDetails.length !== 1 || fromDetails[0].count !== 2 || fromDetails[0].reason !== "unknown") {
              throw new Error("details should provide fallback reason count");
            }

            const empty = view.normalizeSkippedReasonSummary({}, []);
            if (empty.length !== 0) throw new Error("empty skipped state should stay empty");
            """
        )
        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
