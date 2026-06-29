from __future__ import annotations

import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendExportResultDataTests(unittest.TestCase):
    def test_export_result_data_module_normalizes_structured_payloads(self) -> None:
        script = textwrap.dedent(
            """
            const fs = require("fs");
            const vm = require("vm");
            const context = { console };
            context.window = context;
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/export_result_data.js", "utf8"), context);

            const data = context.window.CulviaExportResultData;
            if (!data) throw new Error("data module was not registered");
            if (data.normalize(null) !== null) throw new Error("empty payload should normalize to null");

            const normalized = data.normalize({
              destination: "/exports/final",
              copied: "2",
              skipped: "1",
              copiedFiles: ["/exports/final/new.jpg"],
              skippedDetails: [{ path: "/photos/missing.jpg", label: "源文件缺失", reason: "missing" }],
              skippedReasonSummary: [{ label: "源文件缺失", reason: "missing", count: "1" }],
            });
            if (normalized.destination !== "/exports/final") throw new Error("destination should be kept");
            if (normalized.copied !== 2 || normalized.skipped !== 1) throw new Error("counts should be numeric");
            if (normalized.copiedFiles.length !== 1 || normalized.copiedFiles[0] !== "/exports/final/new.jpg") {
              throw new Error("copied files should be preserved");
            }
            if (normalized.skippedDetails.length !== 1 || normalized.skippedDetails[0].path !== "/photos/missing.jpg") {
              throw new Error("skipped details should be preserved");
            }
            if (normalized.skippedReasonSummary.length !== 1 || normalized.skippedReasonSummary[0].count !== 1) {
              throw new Error("structured skipped payload should keep numeric reason summary");
            }
            if ("skippedFiles" in normalized) throw new Error("removed skippedFiles should not be emitted");

            const explicit = data.normalize({
              skippedDetails: [
                { path: "/photos/a.jpg", label: "源文件缺失", reason: "missing" },
                { path: "/photos/b.jpg", label: "源文件缺失", reason: "missing" },
              ],
            });
            if (explicit.skippedReasonSummary.length !== 1 || explicit.skippedReasonSummary[0].count !== 2) {
              throw new Error("missing explicit summary should derive from structured details");
            }
            """
        )
        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
