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


RESTORE_HARNESS = r"""
const assert = require("node:assert/strict");
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync("web/app.js", "utf8");
const filterFactory = source.slice(source.indexOf("const filterPanel ="), source.indexOf("function preserveSelectedPhoto("));
const exportFactory = source.slice(source.indexOf("const exportPanel ="), source.indexOf("const updatePanel ="));
const polling = source.slice(source.indexOf("async function loadState("), source.indexOf("function selectedScoringModels("));
const h = { storage: new Map(), nodes: new Map(), states: [], filters: [], calls: [], downloads: [], timers: new Map(), renders: 0 };
const context = { console };
context.window = context;
for (const match of (filterFactory + exportFactory).matchAll(/^  ([a-zA-Z_$][a-zA-Z0-9_$]*),$/gm)) context[match[1]] = () => {};
const node = (selector) => {
  if (!h.nodes.has(selector)) h.nodes.set(selector, {
    innerHTML: "", textContent: "", style: {}, classList: { toggle() {} },
    querySelectorAll: () => [], querySelector: () => null,
  });
  return h.nodes.get(selector);
};
const deferred = (requests) => new Promise((resolve, reject) => requests.push({ resolve, reject }));
Object.assign(context, {
  appState: null, pollTimer: null, stateLoadPromise: null, activeView: "export",
  localStorage: {
    getItem: (key) => h.storage.get(key) ?? null,
    setItem: (key, value) => h.storage.set(key, value),
    removeItem: (key) => h.storage.delete(key),
  },
  setInterval: (callback) => { h.timers.set(1, callback); return 1; },
  clearInterval: (id) => h.timers.delete(id),
  sourcePanel: { dirty: () => false, resumePendingPreviewIfReady() {} },
  viewerPanel: { ensureSelectedIndex() {}, resetSelectedIndex() {} },
  commandNotice: null,
  $: node,
  clamp: (value, min, max) => Math.max(min, Math.min(max, value)),
  escapeHtml: (value) => String(value ?? ""),
  iconMarkup: () => "",
  manualColorLabels: [],
  numericValue: () => null,
  colorLabelMeta: (value) => ({ value }),
  pathName: (value) => String(value).split("/").pop(),
  parentPath: (value) => String(value).split("/").slice(0, -1).join("/"),
  setText: (selector, value) => { node(selector).textContent = String(value); },
  setTextWithHint: (selector, value) => { node(selector).textContent = String(value); },
  galleryBatchTarget: () => ({ scope: "filtered", count: 0, fileIds: [] }),
  renderBatchScopePill() {},
  downloadFile: (url, filename) => h.downloads.push({ url, filename }),
  getJson: (url) => { h.calls.push({ method: "GET", url }); return deferred(h.states); },
  postJson: (url, payload) => {
    h.calls.push({ method: "POST", url, payload });
    if (url === "/api/filter") return deferred(h.filters);
    if (url === "/api/export/preflight") return Promise.resolve({ total: 24, ready: 23, missing: 1, renamed: 0, destinationWritable: true });
    throw new Error(`Unexpected mutation: ${url}`);
  },
  render: () => { h.renders += 1; vm.runInContext("exportPanel.renderExportList()", context); },
});
vm.createContext(context);
for (const name of [
  "locales/zh-CN", "locales/en", "i18n_messages", "api_client", "command_view", "filter_state", "filter_presets", "filter_panel",
  "batch_actions", "export_preflight_state", "export_preflight", "export_actions",
  "export_result_data", "export_result", "export_list", "export_panel",
]) vm.runInContext(fs.readFileSync(`web/${name}.js`, "utf8"), context);
context.t = (key, params = {}) => String(context.CulviaI18nMessages.en[key] ?? key)
  .replace(/\{([A-Za-z0-9_]+)\}/g, (_match, name) => params[name] ?? "");
context.CulviaI18n = { t: context.t };
context.errorMessage = context.CulviaApi.errorMessage;
vm.runInContext(filterFactory + exportFactory + polling, context);
h.panel = vm.runInContext("exportPanel", context);
h.savedFilters = { ...context.CulviaFilterState.defaultFilterPayload(), manualStatus: "pending" };
context.CulviaFilterState.persistFilterPayload(h.savedFilters);
h.state = (extra = {}) => ({
  filters: context.CulviaFilterState.defaultFilterPayload(), job: { running: false },
  summary: { scored: 24, matched: 24 }, curation: { all: { selected: 24 }, filtered: { selected: 24 }, exportSelectionKey: "picked-24" },
  photos: [], selectedPhotos: [], ...extra,
});
h.completed = { operationId: "batch-1", sequence: 1, revision: 75, status: "completed", destination: "/delivery/final", total: 24, processed: 24, copied: 23, skipped: 1, notAttempted: 0, previewEntries: [], totalEntryCount: 24 };
const settle = () => new Promise((resolve) => setImmediate(resolve));
"""


class FrontendExportPollingTests(unittest.TestCase):
    def run_poll_script(self, script: str) -> None:
        source = POLLING_HARNESS + "\n(async () => {\n" + textwrap.dedent(script)
        source += "\n})().catch((error) => { console.error(error); process.exitCode = 1; });"
        result = subprocess.run(["node", "-e", source], cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def run_restore_script(self, script: str) -> None:
        source = RESTORE_HARNESS + "\n(async () => {\n" + textwrap.dedent(script)
        source += "\n})().catch((error) => { console.error(error); process.exitCode = 1; });"
        result = subprocess.run(["node", "-e", source], cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_saved_filters_do_not_discard_the_first_persisted_receipt_or_manifest_download(self) -> None:
        self.run_restore_script(
            """
            const first = context.loadState();
            const duplicate = context.loadState();
            h.states[0].resolve(h.state({ exportReceipt: h.completed }));
            await settle();
            assert.equal(h.filters.length, 1, "the real filter panel must restore the saved filter via POST");
            assert.equal(h.calls.find((call) => call.url === "/api/filter").payload.manualStatus, "pending");
            const whileRestoring = context.loadState();
            assert.equal(h.states.length, 1, "filter restoration must remain inside the single state load");
            h.filters[0].resolve(h.state({ filters: h.savedFilters }));
            await Promise.all([first, duplicate, whileRestoring]);
            await settle();
            assert.equal(context.appState.filters.manualStatus, "pending");
            assert.equal(Object.hasOwn(context.appState, "exportReceipt"), false, "the actual filter response replaces app state");
            assert.equal(context.CulviaFilterState.savedFilterPayload().manualStatus, "pending");
            const html = node("#exportResult").innerHTML;
            assert.ok(html.includes("batch-1"), "the first state receipt must survive filter restoration");
            assert.ok(html.includes(context.t("export.resultCopiedPartialTitle", { copied: 23, skipped: 1 })));
            const operationId = html.match(/data-export-download-receipt="([^"]+)"/)[1];
            h.panel.handleExportResultClick({ target: { closest: (selector) => selector === "[data-export-download-receipt]" ? { dataset: { exportDownloadReceipt: operationId } } : null } });
            assert.deepEqual(h.downloads, [{ url: "/api/export/receipts/batch-1/manifest.csv", filename: "culvia-export-manifest.csv" }]);
            assert.equal(h.calls.filter((call) => call.method === "GET").length, 1);
            assert.equal(h.calls.filter((call) => call.url === "/api/export/selected-files").length, 0);
            """
        )

    def test_saved_filter_restore_preserves_the_authoritative_receipt_read_error(self) -> None:
        self.run_restore_script(
            """
            const first = context.loadState();
            h.states[0].resolve(h.state({ exportReceiptError: { errorCode: "exportReceiptStorageFailed" } }));
            await settle();
            assert.equal(h.filters.length, 1);
            h.filters[0].resolve(h.state({ filters: h.savedFilters }));
            await first;
            assert.equal(context.appState.filters.manualStatus, "pending");
            assert.ok(node("#exportResult").innerHTML.includes(context.t("apiError.exportReceiptStorageFailed")));
            assert.ok(node("#exportResult").innerHTML.includes(context.t("export.refreshStatus")));
            assert.equal(h.states.length, 1);
            """
        )

    def test_running_export_keeps_command_progress_with_saved_filters(self) -> None:
        self.run_restore_script(
            """
            const first = context.loadState();
            h.states[0].resolve(h.state({
              job: { kind: "mutation", phase: "exporting_photos", running: true },
              exportReceipt: { ...h.completed, revision: 2, status: "running", processed: 1 },
            }));
            await first;
            assert.equal(h.filters.length, 0, "saved filters must not replace a running task state");
            const command = context.CulviaCommandView.commandViewState({
              job: context.appState.job, exportReceipt: context.appState.exportReceipt,
            });
            assert.equal(command.title, context.t("command.task.export.title"));
            assert.equal(command.progress.detail, context.t("export.resultProgress", { processed: 1, total: 24 }));
            assert.equal(command.pause.visible, false);
            assert.equal(command.cancel.visible, false);
            assert.equal(h.panel.isExporting(), true);
            """
        )

    def test_filter_restoration_keeps_late_empty_and_terminal_receipt_guards(self) -> None:
        self.run_restore_script(
            """
            context.appState = h.state({ exportReceipt: { ...h.completed, revision: 1, status: "running" } });
            h.panel.syncReceiptFromState();
            const staleLoad = context.loadState();
            context.appState = h.state({ exportReceipt: h.completed });
            h.panel.syncReceiptFromState();
            h.states[0].resolve(h.state({ exportReceipt: null }));
            await settle();
            assert.equal(h.filters.length, 1);
            h.filters[0].resolve(h.state({ filters: h.savedFilters }));
            await staleLoad;
            assert.ok(node("#exportResult").innerHTML.includes("batch-1"), "late null cannot erase the newer completed result");
            assert.equal(h.panel.isExporting(), false);
            const staleRunning = context.loadState();
            h.states[1].resolve(h.state({ filters: h.savedFilters, exportReceipt: { ...h.completed, revision: 100, status: "running" } }));
            await staleRunning;
            assert.equal(h.panel.isExporting(), false, "a terminal result cannot regress to running");
            assert.ok(node("#exportResult").innerHTML.includes("batch-1"));
            const cleared = context.loadState();
            h.states[2].resolve(h.state({ filters: h.savedFilters, exportReceipt: null }));
            await cleared;
            assert.equal(node("#exportResult").innerHTML, "", "a fresh authoritative empty state still clears the receipt");
            assert.equal(h.filters.length, 1, "saved filters restore only once");
            assert.equal(h.states.length, 3);
            """
        )

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
