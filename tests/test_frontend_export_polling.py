from __future__ import annotations

import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

POLLING_HARNESS = r"""
const assert = require("node:assert/strict");
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync("web/app.js", "utf8");
const factory = source.slice(source.indexOf("const exportPanel ="), source.indexOf("const updatePanel ="));
const polling = source.slice(source.indexOf("async function loadState("), source.indexOf("function selectedScoringModels("));
const h = { exporting: false, token: "receipt-at-request", timers: new Map(), requests: [], errors: [], synced: [], renders: 0 };
const context = {
  console,
  appState: { job: { running: false } },
  pollTimer: null,
  stateLoadPromise: null,
  sourcePanel: { dirty: () => false, resumePendingPreviewIfReady() {} },
  filterPanel: { restoreSavedFiltersIfNeeded: async () => {}, persistCurrentFilters() {} },
  viewerPanel: { ensureSelectedIndex() {} },
  render: () => { h.renders += 1; },
  getJson: () => new Promise((resolve, reject) => h.requests.push({ resolve, reject })),
  window: {
    setInterval: (callback, delay) => { h.timers.set(1, { callback, delay }); return 1; },
    clearInterval: (id) => h.timers.delete(id),
    CulviaExportPanel: { create: (dependencies) => {
      h.dependencies = dependencies;
      return {
        receiptToken: () => h.token,
        isExporting: () => h.exporting,
        syncReceiptFromState: (options) => h.synced.push(options),
        stateReadFailed: (error) => h.errors.push(error.message),
      };
    } },
  },
};
for (const match of factory.matchAll(/^  ([a-zA-Z_$]+),$/gm)) context[match[1]] = () => {};
vm.createContext(context);
vm.runInContext(factory + polling, context);
const settle = () => new Promise((resolve) => setImmediate(resolve));
"""


class FrontendExportPollingTests(unittest.TestCase):
    def run_poll_script(self, script: str) -> None:
        source = POLLING_HARNESS + "\n(async () => {\n" + textwrap.dedent(script)
        source += "\n})().catch((error) => { console.error(error); process.exitCode = 1; });"
        result = subprocess.run(["node", "-e", source], cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_export_activity_starts_polling_before_the_backend_job_is_visible(self) -> None:
        self.run_poll_script(
            """
            h.exporting = true;
            h.dependencies.onActivityChange();
            assert.equal(h.timers.size, 1);
            assert.equal(h.timers.get(1).delay, 800);
            h.timers.get(1).callback();
            assert.equal(h.requests.length, 1);
            h.requests[0].resolve({ job: { running: false } });
            await settle();
            assert.equal(h.timers.size, 1, "an early idle state cannot stop pending export polling");
            assert.equal(h.synced[0].expectedReceiptToken, "receipt-at-request");
            h.exporting = false;
            h.dependencies.onActivityChange();
            assert.equal(h.timers.size, 0);
            """
        )

    def test_state_loads_do_not_overlap_and_export_completion_requests_a_fresh_state(self) -> None:
        self.run_poll_script(
            """
            const first = context.loadState();
            const duplicate = context.loadState();
            const finalRefresh = h.dependencies.refreshState();
            assert.equal(h.requests.length, 1);
            h.requests[0].resolve({ job: { running: false } });
            await settle();
            assert.equal(h.requests.length, 2, "export completion must fetch after the existing request");
            h.requests[1].resolve({ job: { running: false } });
            await Promise.all([first, duplicate, finalRefresh]);
            assert.equal(h.renders, 2);
            assert.equal(context.stateLoadPromise, null);
            """
        )

    def test_poll_failure_keeps_receipt_monitoring_available_for_recovery(self) -> None:
        self.run_poll_script(
            """
            h.exporting = true;
            h.dependencies.onActivityChange();
            h.timers.get(1).callback();
            h.requests[0].reject(new Error("backend restarting"));
            await settle();
            assert.deepEqual(h.errors, ["backend restarting"]);
            assert.equal(h.timers.size, 1);
            h.timers.get(1).callback();
            assert.equal(h.requests.length, 2);
            h.exporting = false;
            h.requests[1].resolve({ job: { running: false } });
            await settle();
            assert.equal(h.timers.size, 0);
            assert.equal(h.renders, 1);
            """
        )


if __name__ == "__main__":
    unittest.main()
