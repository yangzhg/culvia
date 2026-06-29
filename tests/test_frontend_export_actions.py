from __future__ import annotations

import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendExportActionsTests(unittest.TestCase):
    def test_export_action_helpers_use_i18n_when_available(self) -> None:
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
            vm.runInContext(fs.readFileSync("web/export_actions.js", "utf8"), context);

            const actions = context.window.CulviaExportActions;
            const helpers = { pathName(value) { return String(value).split("/").pop() || ""; } };
            const status = actions.exportStatusText({ copied: 2, skipped: 1 });
            if (status !== "2 exported · 1 not copied") throw new Error(`unexpected English status: ${status}`);
            const emptyAction = actions.primaryActionView({ selectedCount: 0 });
            if (emptyAction.label !== "Export picks" || !emptyAction.hint.includes("no picked photos")) {
              throw new Error("empty export action should be localized");
            }
            const readyAction = actions.primaryActionView({
              selectedCount: 3,
              destination: "/exports/final",
              preflight: { destinationWritable: true, ready: 3, missing: 0, renamed: 1 },
            });
            if (readyAction.label !== "Export 3" || !readyAction.hint.includes("will be renamed automatically")) {
              throw new Error("ready export action should be localized");
            }
            const notice = actions.successNotice({ copied: 2, skipped: 1, destination: "/exports/final" }, helpers);
            if (notice.state !== "Exported" || notice.title !== "Picked photos partially exported") {
              throw new Error("success notice should be localized");
            }
            const copyFailure = actions.copyDestinationFailureNotice("");
            if (!copyFailure.detail.includes("clipboard writes")) throw new Error("copy failure should be localized");
            """
        )
        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_export_action_helpers_build_status_notices_and_payloads(self) -> None:
        script = textwrap.dedent(
            """
            const fs = require("fs");
            const vm = require("vm");
            const context = { console };
            context.window = context;
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/export_actions.js", "utf8"), context);

            const actions = context.window.CulviaExportActions;
            if (!actions) throw new Error("module was not registered");
            if (actions.resultActions.copyDestination !== "copyDestination") {
              throw new Error("copy destination action constant is wrong");
            }
            if (actions.resultActions.revealDestination !== "revealDestination") {
              throw new Error("reveal destination action constant is wrong");
            }
            if (actions.resultActions.none !== "") {
              throw new Error("empty action constant is wrong");
            }
            const helpers = {
              pathName(value) {
                return String(value).split("/").pop() || "";
              },
            };

            const success = { copied: 3, skipped: 0, destination: "/exports/final" };
            if (actions.exportStatusText(success) !== "已导出 3 张") {
              throw new Error("success status text is wrong");
            }
            const emptyAction = actions.primaryActionView({ selectedCount: 0 });
            if (!emptyAction.disabled || emptyAction.label !== "导出入选" || !emptyAction.hint.includes("没有入选")) {
              throw new Error("empty primary action view is wrong");
            }
            const waitingDestination = actions.primaryActionView({ selectedCount: 3 });
            if (!waitingDestination.disabled || waitingDestination.label !== "导出 3 张" || !waitingDestination.hint.includes("等待选择")) {
              throw new Error("destination waiting primary action view is wrong");
            }
            const checking = actions.primaryActionView({ selectedCount: 3, destination: "/exports/final", preflightLoading: true });
            if (!checking.disabled || checking.icon !== "loader" || checking.label !== "检查中") {
              throw new Error("checking primary action view is wrong");
            }
            const blocked = actions.primaryActionView({
              selectedCount: 3,
              destination: "/exports/final",
              preflight: { destinationWritable: false, destinationIssue: "目录不可写" },
            });
            if (!blocked.disabled || blocked.icon !== "circleHelp" || blocked.hint !== "目录不可写") {
              throw new Error("blocked primary action view is wrong");
            }
            const missing = actions.primaryActionView({
              selectedCount: 3,
              destination: "/exports/final",
              preflight: { destinationWritable: true, ready: 2, missing: 1 },
            });
            if (missing.disabled || missing.label !== "导出 2 张" || !missing.hint.includes("1 张缺失")) {
              throw new Error("missing primary action view is wrong");
            }
            const ready = actions.primaryActionView({
              selectedCount: 3,
              destination: "/exports/final",
              preflight: { destinationWritable: true, ready: 3, missing: 0, renamed: 1 },
            });
            if (ready.disabled || ready.label !== "导出 3 张" || !ready.hint.includes("1 张会自动改名")) {
              throw new Error("ready primary action view is wrong");
            }
            const exported = actions.primaryActionView({
              selectedCount: 3,
              destination: "/exports/final",
              preflight: { destinationWritable: true, ready: 3 },
              statusText: actions.exportStatusText(success),
            });
            if (exported.disabled || exported.label !== "再次导出 3 张" || exported.hint !== "已导出 3 张") {
              throw new Error("exported primary action view is wrong");
            }
            const successNotice = actions.successNotice(success, helpers);
            if (successNotice.tone !== "ready" || successNotice.title !== "入选照片已导出") {
              throw new Error("success notice is wrong");
            }
            if (!successNotice.detail.includes("final")) throw new Error("destination name missing");

            const partial = { copied: 2, skipped: 1, destination: "/exports/final" };
            if (actions.exportStatusText(partial) !== "已导出 2 张 · 1 张未复制") {
              throw new Error("partial status text is wrong");
            }
            const partialNotice = actions.successNotice(partial, helpers);
            if (partialNotice.tone !== "partial" || partialNotice.title !== "入选照片部分导出") {
              throw new Error("partial notice is wrong");
            }

            const failure = actions.failureState("目录不可写");
            if (failure.statusText !== "目录不可写") throw new Error("failure status missing");
            if (failure.notice.tone !== "danger" || failure.duration !== 4200) {
              throw new Error("failure notice is wrong");
            }

            if (actions.destinationFromResult({ destination: "/from-result" }, "/fallback") !== "/from-result") {
              throw new Error("result destination should win");
            }
            if (actions.destinationFromResult({}, "/fallback") !== "/fallback") {
              throw new Error("fallback destination missing");
            }
            const payload = actions.revealDestinationPayload("/exports/final");
            if (payload.path !== "/exports/final" || payload.purpose !== "export") {
              throw new Error("reveal payload is wrong");
            }
            const revealNotice = actions.revealFailureNotice("");
            if (revealNotice.tone !== "danger" || !revealNotice.detail) {
              throw new Error("reveal failure notice should include fallback detail");
            }
            if (!revealNotice.detail.includes("手动打开")) {
              throw new Error("reveal failure fallback should explain manual recovery");
            }
            const copySuccess = actions.copyDestinationSuccessNotice("/exports/final", helpers);
            if (copySuccess.tone !== "ready" || copySuccess.title !== "导出路径已复制" || copySuccess.detail !== "final") {
              throw new Error("copy destination success notice is wrong");
            }
            const copyFailure = actions.copyDestinationFailureNotice("");
            if (copyFailure.tone !== "danger" || !copyFailure.detail.includes("手动复制导出位置")) {
              throw new Error("copy destination failure notice is wrong");
            }
            """
        )
        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
