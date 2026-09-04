from __future__ import annotations

import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendBatchActionsTests(unittest.TestCase):
    def test_filtered_operations_flush_before_action_and_abort_on_failure(self) -> None:
        script = textwrap.dedent(
            """
            const fs = require("fs");
            const vm = require("vm");
            const context = { console };
            context.window = context;
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/batch_actions.js", "utf8"), context);

            (async () => {
              const actions = context.window.CulviaBatchActions;
              const filteredEvents = [];
              const filteredResult = await actions.withCommittedFilter(
                "filtered",
                async () => filteredEvents.push("flush"),
                async () => { filteredEvents.push("post"); return "written"; },
              );
              if (filteredEvents.join(",") !== "flush,post" || filteredResult !== "written") {
                throw new Error(`filtered order was ${filteredEvents.join(",")}`);
              }

              for (const scope of ["selected", "current"]) {
                const events = [];
                await actions.withCommittedFilter(
                  scope,
                  async () => events.push("flush"),
                  async () => events.push("post"),
                );
                if (events.join(",") !== "post") throw new Error(`${scope} flushed unnecessarily`);
              }

              const failedEvents = [];
              let failed = false;
              try {
                await actions.withCommittedFilter(
                  "filtered",
                  async () => { failedEvents.push("flush"); throw new Error("filter failed"); },
                  async () => failedEvents.push("post"),
                );
              } catch (error) {
                failed = error.message === "filter failed";
              }
              if (!failed || failedEvents.join(",") !== "flush") {
                throw new Error("failed filter did not abort the write");
              }

              const targetEvents = [];
              const committedTarget = await actions.withCommittedTarget(
                { scope: "filtered", count: 3, showing: 3 },
                async () => targetEvents.push("flush"),
                () => {
                  targetEvents.push("rebuild");
                  return { scope: "filtered", count: 620, showing: 80 };
                },
                async (target) => {
                  targetEvents.push(`post:${target.count}/${target.showing}`);
                  return target;
                },
              );
              if (targetEvents.join(",") !== "flush,rebuild,post:620/80" || committedTarget.count !== 620) {
                throw new Error("filtered target was not rebuilt from committed state");
              }

              const selectedTargetEvents = [];
              await actions.withCommittedTarget(
                { scope: "selected", count: 2 },
                async () => selectedTargetEvents.push("flush"),
                () => { selectedTargetEvents.push("rebuild"); return {}; },
                async (target) => selectedTargetEvents.push(`post:${target.count}`),
              );
              if (selectedTargetEvents.join(",") !== "post:2") {
                throw new Error("selected target was flushed or rebuilt unnecessarily");
              }
            })().catch((error) => {
              console.error(error);
              process.exitCode = 1;
            });
            """
        )
        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

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
            const confirm = actions.confirmView("pick", target);
            if (confirm.countText !== "4 photos" || confirm.scopeText !== "Current filter") {
              throw new Error("confirm facts should stay concise and non-redundant");
            }
            const largeTarget = { scope: "filtered", count: 620, showing: 80, label: "All filtered matches" };
            const colorConfirm = actions.confirmActionView(
              { kind: "color", colorLabel: "red", colorName: "Red" },
              largeTarget,
            );
            if (colorConfirm.title !== "Set the color label to Red?" || colorConfirm.buttonLabel !== "Set Red") {
              throw new Error("color confirmation should name the requested label");
            }
            if (!colorConfirm.detail.includes("all 620 matching photos") || !colorConfirm.detail.includes("80 are currently shown")) {
              throw new Error("color confirmation hid the offscreen impact");
            }
            const acceptConfirm = actions.confirmActionView({ kind: "accept", basis: "llm" }, largeTarget);
            if (acceptConfirm.title !== "Use LLM results for these photos?" || acceptConfirm.buttonLabel !== "Use LLM") {
              throw new Error("LLM confirmation copy is wrong");
            }
            if (!acceptConfirm.detail.includes("manual rating") || !acceptConfirm.detail.includes("all 620 matching photos")) {
              throw new Error("LLM confirmation should explain overwrite and scope");
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
            if (actions.scopeSummary(filteredTarget) !== "全部筛选结果 3 张") {
              throw new Error("filtered scope summary is wrong");
            }
            if (!actions.scopeTitle(filteredTarget).includes("当前筛选")) {
              throw new Error("filtered scope title is wrong");
            }

            const largeFilteredTarget = actions.targetFromSelection(photos, [], 620);
            if (largeFilteredTarget.count !== 620 || largeFilteredTarget.showing !== 3) {
              throw new Error("full filtered count was truncated to shown photos");
            }
            if (actions.scopeSummary(largeFilteredTarget) !== "全部筛选结果 620 张") {
              throw new Error("full filtered scope summary is wrong");
            }
            const largeConfirm = actions.confirmView("pick", largeFilteredTarget);
            if (!largeConfirm.detail.includes("全部 620 张匹配照片") || !largeConfirm.detail.includes("当前仅展示 3 张")) {
              throw new Error("confirmation hid the offscreen impact");
            }
            if (actions.filterCountSummary(620, 80) !== "620 / 80") {
              throw new Error("matched/shown count summary is wrong");
            }
            if (actions.filterCountSummary(undefined, 3) !== "3 / 3") {
              throw new Error("legacy count fallback is wrong");
            }

            const selectedFromLargeFilter = actions.targetFromSelection(photos, visibleSelected, 620);
            if (selectedFromLargeFilter.scope !== "selected" || selectedFromLargeFilter.count !== 2) {
              throw new Error("matched count changed selected scope semantics");
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
            if (confirm.countText !== "2 张" || confirm.icon !== "x" || confirm.tone !== "reject") {
              throw new Error("confirm detail is wrong");
            }
            if (confirm.scopeText !== "已选照片") {
              throw new Error("confirm scope is wrong");
            }

            const clearColorConfirm = actions.confirmActionView(
              { kind: "color", colorLabel: "", colorName: "无色标" },
              largeFilteredTarget,
            );
            if (clearColorConfirm.title !== "清除这些照片的色标？" || clearColorConfirm.buttonLabel !== "清除色标") {
              throw new Error("clear color confirmation is wrong");
            }
            if (clearColorConfirm.detail.includes("。 这会")) {
              throw new Error("Chinese confirmation contains an unnatural punctuation gap");
            }
            const modelConfirm = actions.confirmActionView(
              { kind: "accept", basis: "model" },
              largeFilteredTarget,
            );
            if (modelConfirm.title.replace(/\u200b/g, "") !== "采纳这些照片的综合模型结果？" || modelConfirm.actionLabel !== "综合模型") {
              throw new Error("model confirmation is wrong");
            }
            if (!modelConfirm.title.includes("\u200b综合模型")) {
              throw new Error("model confirmation is missing its semantic wrap opportunity");
            }
            if (!modelConfirm.detail.includes("全部 620 张匹配照片") || !modelConfirm.detail.includes("当前仅展示 3 张")) {
              throw new Error("model confirmation hid the offscreen impact");
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

            const offscreenLlmAccept = actions.acceptControls(largeFilteredTarget, photos, {
              filteredLlmReviewCount: 12,
              hasLlmReview: () => false,
            });
            if (offscreenLlmAccept.count !== 620 || offscreenLlmAccept.llm.disabled) {
              throw new Error("offscreen filtered LLM results were ignored");
            }

            const acceptedNotice = actions.acceptNotice({
              action: { accepted: 2, skipped: 1 },
              basis: "llm",
              scope: "filtered",
            });
            if (acceptedNotice.duration !== 6200 || acceptedNotice.notice.tone !== "ready") {
              throw new Error("accepted notice state is wrong");
            }
            if (!acceptedNotice.notice.detail.includes("全部筛选结果 · 2 张已更新，1 张缺少分数")) {
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
