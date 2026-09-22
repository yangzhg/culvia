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
    "locales/zh-CN", "locales/en", "i18n_messages", "batch_actions",
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
    escapeHtml: (value) => String(value ?? ""),
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
    errorMessage: (error) => error.message,
    showCommandNotice: (notice) => harness.notices.push(notice),
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


if __name__ == "__main__":
    unittest.main()
