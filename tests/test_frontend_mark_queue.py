from __future__ import annotations

import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

MARK_HARNESS = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

function createHarness() {
  const requests = [];
  const notices = [];
  const context = {
    console,
    localStorage: { getItem() { return null; } },
    appState: {
      job: { running: false },
      photos: ["a", "b", "c"].map((fileId) => ({ fileId, manual: { status: "" } })),
    },
    refreshCurationHistoryIfOpen() {},
    render() {},
    showCommandNotice(notice) { notices.push(notice); },
    t(value) { return value; },
    errorMessage(error) { return error.message; },
    restoreNoticeAction() { return null; },
    visibleGallerySelection() {},
    localizedHistoryStatus: (status) => status,
    photoCountText: (count) => String(count),
    flushFilterUpdate: async () => {},
    filteredBatchTarget: () => ({ scope: "filtered", count: 3, fileIds: [] }),
    postJson(url, payload) {
      let resolve;
      let reject;
      const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
      requests.push({ url, payload, resolve, reject });
      return promise;
    },
  };
  context.window = context;
  vm.createContext(context);
  for (const name of ["culling_flow", "manual_status", "batch_actions", "viewer_panel", "gallery_panel"]) {
    vm.runInContext(fs.readFileSync(`web/${name}.js`, "utf8"), context);
  }
  context.manualStatus = context.CulviaManualStatus;
  context.viewerPanel = context.CulviaViewerPanel.create({
    clamp: (value, min, max) => Math.max(min, Math.min(max, value)),
    cullingFlow: context.CulviaCullingFlow,
    getAppState: () => context.appState,
  });
  context.selectedPhoto = () => context.viewerPanel.selectedPhoto();
  context.preserveSelectedPhoto = (...args) => context.viewerPanel.preserveSelectedPhoto(...args);
  const appSource = fs.readFileSync("web/app.js", "utf8");
  vm.runInContext(appSource.slice(
    appSource.indexOf("let markUpdateQueue ="),
    appSource.indexOf("const cullingFlow ="),
  ), context);
  vm.runInContext(appSource.slice(
    appSource.indexOf("async function performPhotoMarkUpdate("),
    appSource.indexOf("async function applyBatchColor("),
  ), context);
  vm.runInContext(appSource.slice(
    appSource.indexOf("async function applyBatchStatus("),
    appSource.indexOf("async function revealPhoto("),
  ), context);
  const gallery = context.CulviaGalleryPanel.create({
    getAppState: () => context.appState,
    updatePhotoMark: (...args) => context.updatePhotoMark(...args),
    statusToggleChanges: (...args) => context.statusToggleChanges(...args),
  });
  const harness = {
    requests,
    notices,
    settle: () => new Promise((resolve) => setImmediate(resolve)),
    current: () => context.selectedPhoto()?.fileId,
    select: (index) => context.viewerPanel.setSelectedIndex(index),
    mark: (changes, options = {}) => context.updateManualMark(changes, options),
    batchStatus: (status, target) => context.applyBatchStatus(status, target),
    accept: (basis) => context.acceptPhotoResult(basis),
    galleryStatus(fileId, status) {
      const button = { dataset: { fileId, galleryStatus: status } };
      gallery.handleGalleryGridClick({
        target: { closest: (selector) => selector === "[data-gallery-status]" ? button : null },
        stopPropagation() {},
      });
    },
    respond(index, options = {}) {
      const request = requests[index];
      assert.ok(request, `request ${index} was not sent`);
      const payload = request.payload;
      const fileId = payload.fileId || payload.fileIds?.[0];
      const next = JSON.parse(JSON.stringify(context.appState));
      const mark = { fileId, ...(options.mark || payload) };
      const photo = next.photos.find((item) => item.fileId === fileId);
      if (photo) Object.assign(photo.manual, mark);
      if (options.photos) next.photos = options.photos;
      next.action = { afterMarks: [mark], accepted: 1, marked: 1, skipped: 0 };
      request.resolve(next);
    },
    state: () => context.appState,
  };
  return harness;
}
"""


class FrontendMarkQueueTests(unittest.TestCase):
    def assert_js_passes(self, body: str) -> None:
        script = MARK_HARNESS + "\n(async () => {\n" + textwrap.dedent(body) + "\n})().catch((error) => {\n"
        script += "  console.error(error); process.exitCode = 1;\n});\n"
        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_queued_action_keeps_the_photo_visible_when_triggered(self) -> None:
        self.assert_js_passes(
            """
            const h = createHarness();
            const first = h.mark({ rating: 4 });
            await h.settle();
            h.select(1);
            const second = h.mark({ status: "reject" });
            h.respond(0);
            await h.settle();
            assert.equal(h.current(), "b", "first response must not pull the viewer back to a");
            assert.equal(h.requests[1].payload.fileId, "b", "the queued rejection belongs to b");
            h.respond(1);
            await Promise.all([first, second]);
            assert.equal(h.state().photos[0].manual.status, "");
            assert.equal(h.state().photos[1].manual.status, "reject");
            """
        )

    def test_response_preserves_later_navigation_across_reordering(self) -> None:
        self.assert_js_passes(
            """
            const h = createHarness();
            const saving = h.mark({ status: "pick" });
            await h.settle();
            h.select(1);
            h.respond(0, { photos: ["c", "a", "b"].map((fileId) => ({ fileId, manual: {} })) });
            await saving;
            assert.equal(h.current(), "b", "preserve the later photo by identity, not its old index");
            """
        )

    def test_repeated_viewer_status_uses_the_latest_saved_mark(self) -> None:
        self.assert_js_passes(
            """
            const h = createHarness();
            const first = h.mark({ status: "pick" });
            const second = h.mark({ status: "pick" });
            await h.settle();
            assert.equal(h.requests[0].payload.status, "pick");
            h.respond(0);
            await h.settle();
            assert.equal(h.requests[1].payload.status, "");
            h.respond(1);
            await Promise.all([first, second]);
            assert.equal(h.state().photos[0].manual.status, "");
            """
        )

    def test_repeated_gallery_status_uses_the_latest_saved_mark(self) -> None:
        self.assert_js_passes(
            """
            const h = createHarness();
            h.select(1);
            h.galleryStatus("a", "pick");
            h.galleryStatus("a", "pick");
            await h.settle();
            assert.equal(h.requests[0].payload.status, "pick");
            h.respond(0);
            await h.settle();
            assert.equal(h.requests[1].payload.status, "", "the second click toggles the persisted pick off");
            h.respond(1);
            await h.settle();
            assert.equal(h.state().photos[0].manual.status, "");
            assert.equal(h.current(), "b", "a gallery mark must not change the viewer selection");
            """
        )

    def test_auto_advance_does_not_retarget_already_queued_marks(self) -> None:
        self.assert_js_passes(
            """
            const h = createHarness();
            const first = h.mark({ rating: 4 }, { advance: true });
            const second = h.mark({ status: "pick" }, { advance: true });
            await h.settle();
            h.respond(0);
            await h.settle();
            assert.equal(h.current(), "b", "a completed mark should still auto-advance");
            assert.equal(h.requests[1].payload.fileId, "a", "both actions were triggered on a");
            h.respond(1);
            await Promise.all([first, second]);
            assert.equal(h.current(), "b", "the second response must not advance a different current photo");
            """
        )

    def test_explicit_batch_status_remains_a_set_not_a_toggle(self) -> None:
        self.assert_js_passes(
            """
            const h = createHarness();
            const target = { scope: "selected", fileIds: ["a"], count: 1, label: "Selected photos" };
            for (let index = 0; index < 2; index += 1) {
              const setting = h.batchStatus("pick", target);
              await h.settle();
              assert.equal(h.requests[index].url, "/api/mark/status");
              assert.equal(h.requests[index].payload.status, "pick");
              h.respond(index);
              await setting;
            }
            assert.equal(h.state().photos[0].manual.status, "pick");
            """
        )

    def test_navigation_away_and_back_cancels_pending_auto_advance(self) -> None:
        self.assert_js_passes(
            """
            const h = createHarness();
            const saving = h.mark({ status: "pick" }, { advance: true });
            await h.settle();
            h.select(1);
            h.select(0);
            h.respond(0);
            await saving;
            assert.equal(h.current(), "a", "the user's later selection wins over pending auto-advance");
            """
        )

    def test_filtered_out_photo_keeps_its_queued_toggle_and_saved_status(self) -> None:
        self.assert_js_passes(
            """
            const h = createHarness();
            const first = h.mark({ status: "pick" }, { advance: true });
            const second = h.mark({ status: "pick" }, { advance: true });
            await h.settle();
            h.respond(0, { photos: ["b", "c"].map((fileId) => ({ fileId, manual: {} })) });
            await h.settle();
            assert.equal(h.current(), "b", "filtered removal should keep the replacement row selected");
            assert.equal(h.requests[1].payload.fileId, "a", "the removed row must not redirect its queued action");
            assert.equal(h.requests[1].payload.status, "", "toggle from the saved mark even outside the filter");
            h.respond(1, { photos: ["a", "b", "c"].map((fileId) => ({ fileId, manual: {} })) });
            await Promise.all([first, second]);
            assert.equal(h.current(), "b", "returning a to the filter must not steal focus from b");
            """
        )

    def test_failed_request_does_not_poison_the_next_bound_action(self) -> None:
        self.assert_js_passes(
            """
            const h = createHarness();
            const first = h.mark({ rating: 4 });
            await h.settle();
            h.select(1);
            const second = h.mark({ status: "pick" });
            h.requests[0].reject(new Error("save failed"));
            await h.settle();
            assert.equal(h.requests[1].payload.fileId, "b");
            h.respond(1);
            await Promise.all([first, second]);
            assert.equal(h.notices[0].detail, "save failed");
            assert.equal(h.state().photos[1].manual.status, "pick");
            """
        )

    def test_interleaved_queue_retains_the_saved_status_of_a_filtered_out_target(self) -> None:
        self.assert_js_passes(
            """
            const h = createHarness();
            const first = h.mark({ status: "pick" });
            h.select(1);
            const middle = h.mark({ status: "reject" });
            h.select(0);
            const last = h.mark({ status: "pick" });
            await h.settle();
            h.respond(0, { photos: ["b", "c"].map((fileId) => ({ fileId, manual: {} })) });
            await h.settle();
            assert.equal(h.requests[1].payload.fileId, "b");
            h.respond(1);
            await h.settle();
            assert.equal(h.requests[2].payload.fileId, "a");
            assert.equal(h.requests[2].payload.status, "", "an intervening save must not erase a's saved status");
            h.respond(2);
            await Promise.all([first, middle, last]);
            """
        )

    def test_accepting_model_or_llm_does_not_undo_later_navigation(self) -> None:
        self.assert_js_passes(
            """
            for (const basis of ["model", "llm"]) {
              const h = createHarness();
              const accepting = h.accept(basis);
              await h.settle();
              h.select(1);
              assert.equal(h.requests[0].payload.fileId, "a");
              assert.equal(h.requests[0].payload.basis, basis);
              h.respond(0, { mark: { fileId: "a", rating: 4, status: "pick", source: basis } });
              await accepting;
              assert.equal(h.current(), "b", `${basis} response must preserve later navigation`);
            }
            """
        )


if __name__ == "__main__":
    unittest.main()
