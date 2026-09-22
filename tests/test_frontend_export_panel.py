from __future__ import annotations

import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PANEL_HARNESS = r"""
const assert = require("node:assert/strict");
const fs = require("fs");
const vm = require("vm");

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function createHarness() {
  const context = { console };
  context.window = context;
  vm.createContext(context);
  for (const name of [
    "locales/zh-CN", "locales/en", "i18n_messages", "api_client", "batch_actions",
    "export_preflight_state", "export_preflight", "export_actions",
    "export_result_data", "export_result", "export_list", "export_panel",
  ]) {
    vm.runInContext(fs.readFileSync(`web/${name}.js`, "utf8"), context);
  }
  const harness = {
    locale: "en",
    app: {
      job: { running: false },
      summary: { scored: 1, matched: 1 },
      curation: { all: { selected: 1 }, filtered: { selected: 1 }, exportSelectionKey: "selection-1" },
      selectedPhotos: [{ fileId: "photo-1", path: "/photos/photo.jpg" }],
      photos: [],
    },
    nodes: new Map(),
    calls: [],
    notices: [],
    exports: [],
    downloads: [],
    activityChanges: [],
    stateRefreshes: 0,
    destination: "/exports/final",
    settle: () => new Promise((resolve) => setImmediate(resolve)),
  };
  const $ = (selector) => {
    if (!harness.nodes.has(selector)) {
      harness.nodes.set(selector, {
        disabled: false, style: {}, textContent: "", innerHTML: "",
        classList: { toggle() {} }, querySelectorAll: () => [],
      });
    }
    return harness.nodes.get(selector);
  };
  const t = (key, params = {}) => {
    const template = context.CulviaI18nMessages[harness.locale][key] ?? key;
    return String(template).replace(/\{([A-Za-z0-9_]+)\}/g, (_match, name) => params[name] ?? "");
  };
  context.CulviaI18n = { t };
  harness.node = $;
  harness.t = t;
  harness.count = (url) => harness.calls.filter((call) => call.url === url).length;
  harness.panel = context.CulviaExportPanel.create({
    $, t,
    clamp: (value, min, max) => Math.max(min, Math.min(max, value)),
    escapeHtml: (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[character]),
    iconMarkup: () => "",
    parentPath: (value) => String(value).split("/").slice(0, -1).join("/"),
    pathName: (value) => String(value).split("/").pop(),
    setText: (selector, value) => { $(selector).textContent = String(value); },
    setTextWithHint: (selector, value) => { $(selector).textContent = String(value); },
    setButtonLabel: (node, icon, label) => { node.icon = icon; node.label = label; },
    localizedMetricText: (value, fallback) => value || fallback,
    localizedScoreLevel: () => "",
    manualBadgeMarkup: () => "",
    colorLabelMeta: (value) => ({ value }),
    manualColorLabels: [],
    numericValue: () => null,
    galleryBatchTarget: () => ({ scope: "filtered", count: 0, fileIds: [] }),
    renderBatchScopePill() {},
    errorMessage: context.CulviaApi.errorMessage,
    showCommandNotice: (notice) => harness.notices.push(notice),
    downloadFile: (url, filename) => harness.downloads.push({ url, filename }),
    onActivityChange: () => harness.activityChanges.push(harness.panel.isExporting()),
    refreshState: async () => {
      harness.stateRefreshes += 1;
      if (harness.onStateRefresh) await harness.onStateRefresh();
    },
    getAppState: () => harness.app,
    getActiveView: () => "export",
    postJson: (url, payload) => {
      harness.calls.push({ url, payload });
      if (url === "/api/pick-export-folder") return Promise.resolve({ folder: harness.destination });
      if (url === "/api/export/preflight") {
        const total = harness.app.curation.all.selected;
        return Promise.resolve({ total, ready: total, missing: 0, renamed: 0, destinationWritable: true });
      }
      if (url === "/api/export/selected-files") {
        const request = deferred();
        harness.exports.push(request);
        return request.promise;
      }
      throw new Error(`Unexpected request: ${url}`);
    },
  });
  harness.success = { copied: 1, skipped: 0, destination: harness.destination, copiedFiles: ["/exports/final/photo.jpg"] };
  return harness;
}

function receipt(overrides = {}) {
  return {
    operationId: "operation-1", sequence: 1, revision: 1, status: "running",
    destination: "/exports/original", total: 40, processed: 4,
    copied: 3, skipped: 1, unconfirmed: 0, notAttempted: 36,
    previewEntries: [
      { index: 0, source: "/photos/source.jpg", target: "/exports/original/target.jpg", status: "copied" },
      { index: 1, source: "/photos/missing.jpg", target: "", status: "missing", reason: "missing" },
    ],
    previewCount: 2, totalEntryCount: 40,
    ...overrides,
  };
}
"""


class FrontendExportPanelTests(unittest.TestCase):
    def run_panel_script(self, script: str) -> None:
        source = (
            PANEL_HARNESS
            + "\n(async () => {\n"
            + textwrap.dedent(script)
            + "\n})().catch((error) => { console.error(error); process.exitCode = 1; });"
        )
        result = subprocess.run(
            ["node", "-e", source],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_copy_is_single_flight_and_controls_stay_disabled_across_renders(self) -> None:
        self.run_panel_script(
            """
            const h = createHarness();
            await h.panel.pickExportFolder();
            const first = h.panel.exportSelectedPhotos();
            const duplicate = h.panel.exportSelectedPhotos();
            assert.equal(h.count("/api/export/selected-files"), 1, "consecutive clicks must send one copy request");
            h.panel.renderExportList();
            assert.equal(h.node("#exportSelectedBtn").disabled, true);
            assert.equal(h.node("#pickExportFolderBtn").disabled, true);
            assert.equal(h.node("#exportSelectedBtn").label, "Exporting…");
            assert.equal(h.node("#exportSelectedHint").textContent, "Copying picked photos to the export folder.");
            h.locale = "zh-CN";
            h.panel.renderExportList();
            assert.equal(h.node("#exportSelectedBtn").label, "正在导出…");
            assert.equal(h.node("#exportSelectedHint").textContent, "正在将入选照片复制到导出目录。");
            await h.panel.pickExportFolder();
            await h.panel.refreshExportPreflight();
            assert.equal(h.count("/api/pick-export-folder"), 1, "the destination cannot change during a copy");
            assert.equal(h.count("/api/export/preflight"), 1, "preflight cannot run during a copy");
            h.exports[0].resolve(h.success);
            await Promise.all([first, duplicate]);
            await h.settle();
            assert.equal(h.node("#exportSelectedBtn").disabled, false);
            assert.equal(h.node("#pickExportFolderBtn").disabled, false);
            assert.equal(h.count("/api/export/preflight"), 2, "copy completion must refresh destination checks");
            assert.ok(h.node("#exportResult").innerHTML.includes(h.t("export.resultCopiedTitle", { copied: 1 })));
            """
        )

    def test_copy_failure_and_partial_result_allow_a_deliberate_retry(self) -> None:
        self.run_panel_script(
            """
            const h = createHarness();
            await h.panel.pickExportFolder();
            const failed = h.panel.exportSelectedPhotos();
            h.exports[0].reject(new Error("destination disconnected"));
            await failed;
            await h.settle();
            assert.equal(h.node("#exportSelectedBtn").disabled, false, "failure must release the in-flight guard");
            assert.equal(h.node("#exportSelectedHint").textContent, "destination disconnected");
            assert.equal(h.notices.at(-1).tone, "danger");
            const retry = h.panel.exportSelectedPhotos();
            assert.equal(h.count("/api/export/selected-files"), 2);
            assert.equal(h.node("#exportSelectedBtn").disabled, true);
            h.exports[1].resolve({
              copied: 1, skipped: 1, destination: h.destination,
              skippedDetails: [{ path: "/photos/missing.jpg", reason: "missing" }],
            });
            await retry;
            await h.settle();
            assert.equal(h.node("#exportSelectedBtn").disabled, false);
            assert.ok(h.node("#exportResult").innerHTML.includes(h.t("export.resultCopiedPartialTitle", { copied: 1, skipped: 1 })));
            assert.equal(h.notices.at(-1).tone, "partial");
            """
        )

    def test_copy_completion_waits_for_backend_busy_state_before_rechecking(self) -> None:
        self.run_panel_script(
            """
            const h = createHarness();
            await h.panel.pickExportFolder();
            const copy = h.panel.exportSelectedPhotos();
            h.app.job.running = true;
            h.exports[0].resolve(h.success);
            await copy;
            await h.settle();
            assert.equal(h.count("/api/export/preflight"), 1);
            assert.equal(h.node("#exportSelectedBtn").disabled, true);
            h.app.job.running = false;
            h.panel.renderExportList();
            await h.settle();
            assert.equal(h.count("/api/export/preflight"), 2, "a busy render cannot consume the pending destination check");
            assert.equal(h.node("#exportSelectedBtn").disabled, false);
            """
        )

    def test_full_selection_key_invalidates_preflight_beyond_the_preview_limit(self) -> None:
        self.run_panel_script(
            """
            const h = createHarness();
            h.app.selectedPhotos = Array.from({ length: 80 }, (_, index) => ({ fileId: `photo-${index}`, path: `/photos/${index}.jpg` }));
            h.app.curation.all.selected = 81;
            await h.panel.pickExportFolder();
            h.app.curation.exportSelectionKey = "different-photo-beyond-preview";
            h.panel.renderExportList();
            await h.settle();
            assert.equal(h.count("/api/export/preflight"), 2, "full selection changes must invalidate an unchanged 80-photo preview");
            h.app.selectedPhotos.reverse();
            h.app.curation.filtered.selected = 0;
            h.panel.renderExportList();
            await h.settle();
            assert.equal(h.count("/api/export/preflight"), 2, "display order and filters do not change the export set");
            h.app.job.running = true;
            h.app.curation.exportSelectionKey = "new-source";
            h.panel.renderExportList();
            assert.equal(h.count("/api/export/preflight"), 2);
            h.app.job.running = false;
            h.panel.renderExportList();
            await h.settle();
            assert.equal(h.count("/api/export/preflight"), 3, "source changes during a job must recheck when it finishes");
            """
        )

    def test_older_state_responses_recheck_using_the_selection_preview(self) -> None:
        self.run_panel_script(
            """
            const h = createHarness();
            delete h.app.curation.exportSelectionKey;
            await h.panel.pickExportFolder();
            h.app.selectedPhotos = [{ fileId: "photo-2", path: "/photos/other.jpg" }];
            h.panel.renderExportList();
            await h.settle();
            assert.equal(h.count("/api/export/preflight"), 2);
            h.destination = "/exports/other";
            await h.panel.pickExportFolder();
            assert.equal(h.count("/api/export/preflight"), 3);
            assert.equal(h.calls.at(-1).payload.destination, "/exports/other");
            """
        )

    def test_running_and_completed_receipts_restore_after_page_refresh(self) -> None:
        self.run_panel_script(
            """
            const running = createHarness();
            running.app.exportReceipt = receipt();
            running.app.job.running = true;
            running.panel.renderExportList();
            assert.ok(running.node("#exportDestinationText").textContent.includes("original"));
            assert.ok(running.node("#exportResult").innerHTML.includes("4 of 40 processed"));
            assert.ok(running.node("#exportResult").innerHTML.includes("operation-1"));
            assert.equal(running.node("#exportSelectedBtn").disabled, true);
            assert.equal(running.panel.isExporting(), true);
            assert.equal(running.count("/api/export/selected-files"), 0);

            const finished = createHarness();
            finished.app.exportReceipt = receipt({ status: "completed", revision: 42, processed: 40, copied: 39, skipped: 1, notAttempted: 0 });
            finished.panel.renderExportList();
            await finished.settle();
            assert.ok(finished.node("#exportResult").innerHTML.includes(finished.t("export.resultCopiedPartialTitle", { copied: 39, skipped: 1 })));
            assert.ok(finished.node("#exportResult").innerHTML.includes("operation-1"));
            assert.equal(finished.panel.isExporting(), false);
            assert.equal(finished.count("/api/export/selected-files"), 0);
            """
        )

    def test_late_receipts_cannot_regress_a_result_or_replace_a_user_destination(self) -> None:
        self.run_panel_script(
            """
            const h = createHarness();
            const completed = receipt({ status: "completed", revision: 42, processed: 40, copied: 40, skipped: 0, notAttempted: 0 });
            h.app.exportReceipt = completed;
            h.panel.renderExportList();
            await h.settle();
            h.destination = "/exports/user-choice";
            await h.panel.pickExportFolder();
            h.app.exportReceipt = receipt({ revision: 10 });
            h.panel.renderExportList();
            assert.ok(h.node("#exportResult").innerHTML.includes(h.t("export.resultCopiedTitle", { copied: 40 })));
            assert.equal(h.panel.isExporting(), false);
            assert.ok(h.node("#exportDestinationText").textContent.includes("user-choice"));
            h.app.exportReceipt = receipt({ operationId: "older-operation", sequence: 0, revision: 100 });
            h.panel.renderExportList();
            assert.ok(!h.node("#exportResult").innerHTML.includes("older-operation"));
            const copy = h.panel.exportSelectedPhotos();
            assert.equal(h.calls.at(-1).payload.destination, "/exports/user-choice");
            h.exports[0].resolve(receipt({ operationId: "operation-2", sequence: 2, status: "completed", destination: "/exports/user-choice", processed: 40, copied: 40, skipped: 0, notAttempted: 0 }));
            await copy;
            await h.settle();
            assert.ok(h.node("#exportResult").innerHTML.includes("operation-2"));
            assert.ok(h.node("#exportDestinationText").textContent.includes("user-choice"));
            """
        )

    def test_missing_error_and_late_empty_state_do_not_erase_known_receipts(self) -> None:
        self.run_panel_script(
            """
            const h = createHarness();
            h.app.exportReceipt = receipt({ status: "completed", revision: 4 });
            h.panel.renderExportList();
            const before = h.panel.receiptToken();
            delete h.app.exportReceipt;
            h.panel.renderExportList();
            assert.ok(h.node("#exportResult").innerHTML.includes("operation-1"));
            h.app.exportReceiptError = { errorCode: "exportReceiptStorageFailed" };
            h.panel.renderExportList();
            assert.ok(h.node("#exportResult").innerHTML.includes("operation-1"));
            assert.ok(h.node("#exportResult").innerHTML.includes(h.t("export.refreshStatus")));
            assert.ok(h.node("#exportResult").innerHTML.includes(h.t("apiError.exportReceiptStorageFailed")));
            delete h.app.exportReceiptError;
            h.app.exportReceipt = receipt({ operationId: "operation-2", sequence: 2, status: "completed" });
            h.panel.renderExportList();
            h.app.exportReceipt = null;
            h.panel.syncReceiptFromState({ expectedReceiptToken: before });
            h.panel.renderExportList();
            assert.ok(h.node("#exportResult").innerHTML.includes("operation-2"), "late null cannot erase a newer POST or state receipt");
            h.panel.syncReceiptFromState({ expectedReceiptToken: h.panel.receiptToken() });
            h.panel.renderExportList();
            assert.equal(h.node("#exportResult").innerHTML, "", "an authoritative empty state clears receipts after reset");
            """
        )

    def test_interrupted_and_unknown_receipts_never_claim_completion_or_retry(self) -> None:
        self.run_panel_script(
            """
            const h = createHarness();
            h.app.exportReceipt = receipt({ status: "interrupted", revision: 5, unconfirmed: 1, notAttempted: 35 });
            h.panel.renderExportList();
            await h.settle();
            const html = h.node("#exportResult").innerHTML;
            assert.ok(html.includes(h.t("export.resultInterrupted")));
            assert.ok(html.includes(h.t("export.resultUnconfirmed")));
            assert.ok(html.includes(h.t("export.resultNotAttempted")));
            assert.ok(!html.includes(h.t("export.resultReady")));
            assert.equal(h.count("/api/export/selected-files"), 0);
            assert.equal(h.panel.isExporting(), false);
            h.app.exportReceipt = receipt({ operationId: "future-operation", sequence: 2, status: "future_status" });
            h.panel.renderExportList();
            assert.ok(h.node("#exportResult").innerHTML.includes(h.t("export.resultUnknown")));
            assert.ok(!h.node("#exportResult").innerHTML.includes(h.t("export.resultReady")));
            assert.equal(h.count("/api/export/selected-files"), 0);
            """
        )

    def test_request_failure_preserves_backend_progress_and_refreshes_state(self) -> None:
        self.run_panel_script(
            """
            const h = createHarness();
            await h.panel.pickExportFolder();
            const copy = h.panel.exportSelectedPhotos();
            assert.deepEqual(h.activityChanges, [true]);
            h.app.exportReceipt = receipt({ destination: h.destination });
            h.panel.renderExportList();
            h.exports[0].reject(new Error("connection lost"));
            await copy;
            assert.equal(h.stateRefreshes, 1);
            assert.ok(h.node("#exportResult").innerHTML.includes("operation-1"));
            assert.ok(h.node("#exportResult").innerHTML.includes("4 of 40 processed"));
            assert.equal(h.panel.isExporting(), true);
            assert.ok(!h.notices.at(-1).title.includes("not exported"));
            h.onStateRefresh = async () => {
              h.app.exportReceipt = receipt({ status: "completed", destination: h.destination, revision: 50, processed: 40, copied: 40, skipped: 0 });
            };
            await h.panel.refreshExportReceipt();
            assert.equal(h.stateRefreshes, 2);
            assert.equal(h.panel.isExporting(), false);
            """
        )

    def test_manifest_download_uses_the_clicked_operation_and_twenty_entry_preview(self) -> None:
        self.run_panel_script(
            """
            const h = createHarness();
            h.app.exportReceipt = receipt({
              status: "completed", total: 60, processed: 60, copied: 60, skipped: 0,
              previewCount: 20, totalEntryCount: 60,
              previewEntries: Array.from({ length: 20 }, (_, index) => ({
                index, source: `/photos/source-${index}.jpg`, target: `/exports/target-${index}.jpg`, status: "copied",
              })),
            });
            h.panel.renderExportList();
            const html = h.node("#exportResult").innerHTML;
            assert.ok(html.includes("source-19.jpg"));
            assert.ok(html.includes("target-19.jpg"));
            assert.ok(html.includes("20 of 60"));
            assert.ok(html.includes(h.t("export.downloadManifest")));
            const button = { dataset: { exportDownloadReceipt: "operation-1" } };
            const click = { target: { closest: (selector) => selector === "[data-export-download-receipt]" ? button : null } };
            h.app.exportReceipt = receipt({ operationId: "operation-2", sequence: 2, status: "completed" });
            h.panel.renderExportList();
            h.panel.handleExportResultClick(click);
            assert.deepEqual(h.downloads, [{ url: "/api/export/receipts/operation-1/manifest.csv", filename: "culvia-export-manifest.csv" }]);
            """
        )

    def test_receipt_progress_keeps_details_open_and_restores_keyboard_focus(self) -> None:
        self.run_panel_script(
            """
            const h = createHarness();
            const node = h.node("#exportResult");
            let content = "";
            let writes = 0;
            let details = null;
            let focused = null;
            let download = null;
            Object.defineProperty(node, "innerHTML", {
              get: () => content,
              set(value) {
                content = value;
                writes += 1;
                details = { open: false };
                focused = null;
                download = {
                  matches: (selector) => selector === "[data-export-download-receipt]",
                  focus: () => { focused = download; },
                };
              },
            });
            node.querySelector = (selector) => {
              if (selector === "details") return details;
              if (selector === ":focus") return focused;
              if (selector === "[data-export-download-receipt]") return download;
              return null;
            };
            h.app.exportReceipt = receipt();
            h.app.job.running = true;
            h.panel.renderExportList();
            details.open = true;
            download.focus();
            const unchangedWrites = writes;
            h.panel.renderExportList();
            assert.equal(writes, unchangedWrites, "unchanged state must not replace the result DOM");
            h.app.exportReceipt = receipt({ revision: 2, processed: 5, copied: 4 });
            h.panel.renderExportList();
            assert.equal(details.open, true);
            assert.equal(focused, download);
            h.app.exportReceipt = receipt({ operationId: "operation-2", sequence: 2 });
            h.panel.renderExportList();
            assert.equal(details.open, false, "a new operation starts with its own summary");
            """
        )

    def test_transport_failure_preserves_a_receipt_until_manual_refresh_recovers(self) -> None:
        self.run_panel_script(
            """
            const h = createHarness();
            h.app.exportReceipt = receipt({ status: "completed", revision: 40 });
            h.panel.renderExportList();
            h.panel.stateReadFailed(new Error("backend offline"));
            assert.ok(h.node("#exportResult").innerHTML.includes("backend offline"));
            assert.ok(h.node("#exportResult").innerHTML.includes("operation-1"));
            h.onStateRefresh = async () => {
              h.app.exportReceipt = receipt({ status: "completed", revision: 41 });
            };
            await h.panel.refreshExportReceipt();
            assert.ok(!h.node("#exportResult").innerHTML.includes("backend offline"));
            assert.ok(h.node("#exportResult").innerHTML.includes("operation-1"));
            """
        )

    def test_old_delivery_counts_do_not_describe_a_new_selection(self) -> None:
        self.run_panel_script(
            """
            const h = createHarness();
            h.app.exportReceipt = receipt({ status: "completed", processed: 40, copied: 40, skipped: 0 });
            h.panel.renderExportList();
            await h.settle();
            h.app.curation.all.selected = 2;
            h.app.curation.exportSelectionKey = "other-source-picks";
            h.panel.renderExportList();
            await h.settle();
            assert.equal(h.node("#exportSelectedBtn").label, "Export 2");
            assert.ok(!h.node("#exportSelectedHint").textContent.includes("40"));
            assert.ok(h.node("#exportResult").innerHTML.includes("Latest export"));
            assert.ok(h.node("#exportResult").innerHTML.includes("40 copied"));
            """
        )

    def test_reset_clears_receipt_without_reviving_it_from_an_old_response(self) -> None:
        self.run_panel_script(
            """
            const h = createHarness();
            h.app.exportReceipt = receipt({ sequence: 8, status: "completed" });
            h.panel.renderExportList();
            h.panel.clearReceipt();
            h.panel.renderExportList();
            assert.equal(h.node("#exportResult").innerHTML, "");
            h.app.exportReceipt = receipt({ operationId: "after-reset", sequence: 1, status: "completed" });
            h.panel.renderExportList();
            assert.ok(h.node("#exportResult").innerHTML.includes("after-reset"));
            """
        )

    def test_receipt_details_localize_errors_and_escape_user_file_names(self) -> None:
        self.run_panel_script(
            """
            const h = createHarness();
            h.app.exportReceipt = receipt({
              status: "interrupted", errorText: { key: "apiError.exportInterrupted", params: {} },
              previewEntries: [{
                source: "/photos/<img src=x onerror=alert(1)>.jpg",
                target: '/exports/quote"name.jpg', status: "copy_failed",
                messageText: { key: "apiError.exportFailed", params: {} },
              }],
            });
            h.panel.renderExportList();
            let html = h.node("#exportResult").innerHTML;
            assert.ok(!html.includes("<img src=x"));
            assert.ok(html.includes("&lt;img src=x"));
            assert.ok(html.includes("quote&quot;name.jpg"));
            assert.ok(html.includes(h.t("apiError.exportInterrupted")));
            assert.ok(html.includes(h.t("apiError.exportFailed")));
            h.locale = "zh-CN";
            h.panel.renderExportList();
            html = h.node("#exportResult").innerHTML;
            assert.ok(html.includes(h.t("export.resultInterrupted")));
            assert.ok(html.includes(h.t("apiError.exportInterrupted")));
            assert.ok(html.includes(h.t("export.downloadManifest")));
            """
        )


if __name__ == "__main__":
    unittest.main()
