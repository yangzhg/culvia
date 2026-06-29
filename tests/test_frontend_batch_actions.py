from __future__ import annotations

import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendBatchActionsTests(unittest.TestCase):
    def test_batch_action_notices_use_i18n_when_available(self) -> None:
        script = textwrap.dedent(
            """
            const fs = require("fs");
            const vm = require("vm");
            const context = { console };
            context.window = context;
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/locales/zh-CN.js", "utf8"), context);
            vm.runInContext(fs.readFileSync("web/locales/en.js", "utf8"), context);
            vm.runInContext(fs.readFileSync("web/i18n_messages.js", "utf8"), context);
            context.window.CulviaI18n = {
              t(key, params = {}) {
                const template = context.window.CulviaI18nMessages.en[key] ?? key;
                return String(template).replace(/\\{([A-Za-z0-9_]+)\\}/g, (_match, name) => params[name] ?? "");
              },
            };
            vm.runInContext(fs.readFileSync("web/batch_actions.js", "utf8"), context);

            const actions = context.window.CulviaBatchActions;
            const target = { scope: "filtered", fileIds: [], count: 4, label: "Current filter" };
            const notice = actions.acceptNotice({
              action: { accepted: 2, skipped: 1 },
              basis: "llm",
              scope: "filtered",
            });
            if (notice.notice.state !== "Accepted" || !notice.notice.title.includes("LLM results applied")) {
              throw new Error("accept notice should be localized");
            }
            if (!notice.notice.detail.includes("2 updated; 1 missing scores")) {
              throw new Error("accept notice detail should be localized");
            }
            const colorNotice = actions.colorNotice({ colorLabel: "", count: 4, target });
            if (colorNotice.state !== "Marked" || colorNotice.title !== "Color label cleared") {
              throw new Error("color notice should be localized");
            }
            """
        )
        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_batch_action_helpers_build_targets_and_confirm_view(self) -> None:
        script = textwrap.dedent(
            """
            const fs = require("fs");
            const vm = require("vm");
            const context = { console };
            context.window = context;
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/batch_actions.js", "utf8"), context);

            const actions = context.window.CulviaBatchActions;
            if (!actions) throw new Error("module was not registered");

            const photos = [{ fileId: "a" }, { fileId: "b" }, { fileId: "c" }];
            const visibleSelected = actions.visibleSelectedIds(photos, ["b", "missing", "", "a"]);
            if (visibleSelected.join(",") !== "b,a") {
              throw new Error(`visible selection was ${visibleSelected.join(",")}`);
            }

            const selectedTarget = actions.targetFromSelection(photos, visibleSelected);
            if (selectedTarget.scope !== "selected" || selectedTarget.count !== 2) {
              throw new Error("selected target is wrong");
            }
            if (selectedTarget.fileIds.join(",") !== "b,a" || selectedTarget.label !== "已选照片") {
              throw new Error("selected target detail is wrong");
            }
            if (actions.scopeSummary(selectedTarget) !== "已选照片 2 张") {
              throw new Error("selected scope summary is wrong");
            }
            if (!actions.scopeTitle(selectedTarget).includes("已选照片")) {
              throw new Error("selected scope title is wrong");
            }

            const filteredTarget = actions.targetFromSelection(photos, []);
            if (filteredTarget.scope !== "filtered" || filteredTarget.count !== 3 || filteredTarget.fileIds.length) {
              throw new Error("filtered target is wrong");
            }
            if (actions.scopeSummary(filteredTarget) !== "当前筛选 3 张") {
              throw new Error("filtered scope summary is wrong");
            }
            if (!actions.scopeTitle(filteredTarget).includes("当前筛选")) {
              throw new Error("filtered scope title is wrong");
            }

            const rejectMeta = actions.statusMeta("reject");
            if (rejectMeta.label !== "淘汰" || rejectMeta.icon !== "x" || rejectMeta.tone !== "reject") {
              throw new Error("reject meta is wrong");
            }
            const pendingMeta = actions.statusMeta("unknown");
            if (pendingMeta.label !== "待复核" || pendingMeta.icon !== "clock") {
              throw new Error("pending fallback is wrong");
            }

            const confirm = actions.confirmView("reject", selectedTarget);
            if (confirm.title !== "批量设为淘汰？" || confirm.buttonLabel !== "确认淘汰") {
              throw new Error("confirm labels are wrong");
            }
            if (confirm.countText !== "2 张 · 已选照片" || confirm.icon !== "x" || confirm.tone !== "reject") {
              throw new Error("confirm detail is wrong");
            }
            if (confirm.scopeText !== "已选照片") {
              throw new Error("confirm scope is wrong");
            }

            const accept = actions.acceptControls(selectedTarget, [
              { fileId: "a", llmReviewScores: { llm_review_overall: 7.2 } },
              { fileId: "b", llmReviewScores: {} },
              { fileId: "c", llmReviewScores: { llm_review_overall: 8.1 } },
            ]);
            if (accept.count !== 2 || accept.photos.map((photo) => photo.fileId).join(",") !== "a,b") {
              throw new Error("accept target photos are wrong");
            }
            if (accept.model.label !== "采纳已选" || accept.model.disabled) {
              throw new Error("selected model action is wrong");
            }
            if (accept.llm.label !== "采纳已选大模型" || accept.llm.disabled) {
              throw new Error("selected llm action is wrong");
            }

            const emptyAccept = actions.acceptControls(actions.emptyTarget(), [], {
              hasLlmReview: () => true,
            });
            if (!emptyAccept.model.disabled || !emptyAccept.llm.disabled || emptyAccept.hasPhotos) {
              throw new Error("empty accept actions should be disabled");
            }

            const filteredAccept = actions.acceptControls(filteredTarget, photos, {
              hasLlmReview: (photo) => photo.fileId === "c",
            });
            if (filteredAccept.model.label !== "采纳当前筛选" || filteredAccept.llm.label !== "采纳大模型") {
              throw new Error("filtered accept labels are wrong");
            }
            if (filteredAccept.llm.disabled) throw new Error("custom llm resolver was ignored");

            const acceptedNotice = actions.acceptNotice({
              action: { accepted: 2, skipped: 1 },
              basis: "llm",
              scope: "filtered",
            });
            if (acceptedNotice.duration !== 6200 || acceptedNotice.notice.tone !== "ready") {
              throw new Error("accepted notice state is wrong");
            }
            if (!acceptedNotice.notice.detail.includes("当前筛选 · 2 张已更新，1 张缺少分数")) {
              throw new Error("accepted notice detail is wrong");
            }
            const skippedNotice = actions.acceptNotice({ action: {}, basis: "model", scope: "current" });
            if (skippedNotice.duration !== 2400 || skippedNotice.notice.state !== "无可采纳") {
              throw new Error("empty accept notice is wrong");
            }

            const colorNotice = actions.colorNotice({
              colorLabel: "green",
              colorName: "绿色",
              count: 3,
              target: selectedTarget,
            });
            if (colorNotice.title !== "已设为绿色" || colorNotice.detail !== "已选照片 3 张") {
              throw new Error("color notice is wrong");
            }
            """
        )
        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
