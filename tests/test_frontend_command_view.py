from __future__ import annotations

import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

MODULE_BOOTSTRAP = """
const fs = require("fs");
const vm = require("vm");
const context = {
  console,
  navigator: { language: "zh-CN" },
  localStorage: { getItem: () => "zh-CN", setItem: () => {} },
  CustomEvent: function CustomEvent(name, init) { return { name, detail: init.detail }; },
  dispatchEvent: () => {},
  document: {
    title: "",
    readyState: "loading",
    documentElement: {},
    addEventListener: () => {},
    querySelector: () => null,
    querySelectorAll: () => [],
  },
};
context.window = context;
vm.createContext(context);
vm.runInContext(fs.readFileSync("web/locales/zh-CN.js", "utf8"), context);
vm.runInContext(fs.readFileSync("web/locales/en.js", "utf8"), context);
vm.runInContext(fs.readFileSync("web/i18n_messages.js", "utf8"), context);
vm.runInContext(fs.readFileSync("web/i18n.js", "utf8"), context);
vm.runInContext(fs.readFileSync("web/command_view.js", "utf8"), context);

const view = context.window.CulviaCommandView;
if (!view) throw new Error("module was not registered");
"""


class FrontendCommandViewTests(unittest.TestCase):
    def assert_js_passes(self, body: str) -> None:
        script = textwrap.dedent(f"{MODULE_BOOTSTRAP}\n{body}")
        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_idle_ready_and_summary_states(self) -> None:
        self.assert_js_passes(
            """
            const waiting = view.commandViewState({ sourceReady: false, model: { label: "等待", downloaded: false } });
            if (waiting.title !== "先选择照片来源") throw new Error("waiting title is wrong");
            if (!waiting.mainScore.disabled || waiting.mainScore.label !== "准备评分") {
              throw new Error("waiting main score state is wrong");
            }
            if (!waiting.llmReview.disabled) throw new Error("waiting LLM review should be disabled");

            const ready = view.commandViewState({
              sourceReady: true,
              llmConfigured: true,
              model: { downloaded: true, label: "就绪", tone: "ready" },
            });
            if (ready.title !== "可以开始评分" || ready.mainScore.disabled) {
              throw new Error("ready command state is wrong");
            }
            if (ready.mainScore.icon !== "play" || ready.mainScore.label !== "评分") {
              throw new Error("ready button state is wrong");
            }
            if (ready.llmReview.disabled || ready.llmReview.label !== "AI评审") {
              throw new Error("ready LLM review button state is wrong");
            }

            const summary = view.commandViewState({
              hasResults: true,
              sourceReady: true,
              summary: { scored: 12, matched: 9, showing: 5 },
            });
            if (!summary.compact || summary.dotTone !== "ready" || summary.state !== "结果已就绪") {
              throw new Error("summary state is wrong");
            }
            if (!summary.detail.includes("已评分 12 张，筛选匹配 9 张，当前展示 5 张")) {
              throw new Error("summary detail is wrong");
            }
            """
        )

    def test_running_progress_and_current_photo_states(self) -> None:
        self.assert_js_passes(
            """
            const loading = view.commandViewState({
              sourceReady: true,
              job: { running: true, phase: "loading_model", detail: "加载中" },
            });
            if (loading.state !== "正在载入模型" || loading.progress.width !== "96%") {
              throw new Error("loading model progress state is wrong");
            }
            if (!loading.mainScore.disabled || !loading.pause.visible || loading.pause.label !== "暂停") {
              throw new Error("loading controls are wrong");
            }

            const scanning = view.commandViewState({
              sourceReady: false,
              job: { kind: "source_preview", running: true, progress: 0.25 },
            });
            if (scanning.state !== "正在扫描" || scanning.title !== "正在扫描照片来源") {
              throw new Error("source preview progress state is wrong");
            }
            if (!scanning.mainScore.disabled || scanning.pause.visible) {
              throw new Error("source preview controls are wrong");
            }

            const llmReview = view.commandViewState({
              sourceReady: true,
              job: {
                kind: "llm_review",
                currentFile: "portrait.jpg",
                progress: 0.5,
                running: true,
                titleText: { key: "jobText.llmRunning" },
              },
            });
            if (llmReview.state !== "大模型评审中" || llmReview.title !== "正在进行大模型评审") {
              throw new Error("LLM review running state is wrong");
            }
            if (llmReview.pause.visible || !llmReview.cancel.visible || !llmReview.currentPhoto.visible) {
              throw new Error("LLM review controls are wrong");
            }

            const paused = view.commandViewState({
              sourceReady: true,
              job: {
                activeEvaluation: "stage.llmReview",
                completedEvaluations: ["stage.basicTechnical", "stage.clipAesthetic"],
                currentFile: "portrait.jpg",
                currentThumb: "/api/image/thumb",
                paused: true,
                progress: 0.42,
                running: true,
                titleText: { key: "jobText.scoring" },
              },
            });
            if (paused.state !== "已暂停" || paused.pause.label !== "继续" || paused.pause.icon !== "play") {
              throw new Error("paused state is wrong");
            }
            if (!paused.currentPhoto.visible || paused.currentPhoto.stage !== "暂停中") {
              throw new Error("paused current photo state is wrong");
            }
            if (paused.currentPhoto.completed.length !== 2 || paused.progress.width !== "42%") {
              throw new Error("paused progress state is wrong");
            }
            if (paused.currentPhoto.completed[0] !== "技术质检" || paused.currentPhoto.completed[1] !== "审美参考") {
              throw new Error("completed evaluations should resolve stage keys");
            }

            const preparing = view.commandViewState({
              sourceReady: true,
              job: {
                modelProgress: {
                  detailText: { key: "jobText.connectingSource" },
                  labelText: { key: "jobText.prepModel" },
                  progress: 1.4,
                },
                running: true,
              },
            });
            if (preparing.progress.width !== "100%" || preparing.currentPhoto.visible) {
              throw new Error("model progress should clamp and hide current photo");
            }
            if (preparing.progress.label !== "准备模型" || preparing.progress.detail !== "正在连接下载源") {
              throw new Error("model progress text refs should resolve");
            }
            """
        )

    def test_error_notice_and_helpers(self) -> None:
        self.assert_js_passes(
            """
            if (!view.isPaused({ phase: "pausing" }) || view.isPaused({ phase: "done" })) {
              throw new Error("pause helper is wrong");
            }
            const fallbackProgress = view.progressView({ label: "", detail: "", value: "bad" });
            if (fallbackProgress.width !== "0%" || fallbackProgress.label !== "正在处理") {
              throw new Error("progress fallback is wrong");
            }

            const error = view.commandViewState({ job: { phase: "error", error: "目录不可读" } });
            if (error.dotTone !== "danger" || error.title !== "评分没有完成" || error.detail !== "目录不可读") {
              throw new Error("error state is wrong");
            }

            const notice = view.commandViewState({
              commandNotice: {
                action: { icon: "undo", label: "撤销" },
                detail: "刚刚恢复了 3 张照片",
                progress: { label: "恢复中", value: 1.2 },
                state: "已恢复",
                title: "撤销完成",
                tone: "ready",
              },
              sourceReady: true,
            });
            if (notice.state !== "已恢复" || notice.title !== "撤销完成") {
              throw new Error("notice should override idle state");
            }
            if (!notice.noticeAction.visible || notice.noticeAction.label !== "撤销") {
              throw new Error("notice action is wrong");
            }
            if (notice.progress.width !== "100%") throw new Error("notice progress should clamp");
            """
        )

    def test_text_refs_resolve_with_params_and_nesting(self) -> None:
        self.assert_js_passes(
            """
            const simple = view.resolveTextRef({ key: "jobText.photosReadyDetail", params: { count: 12 } });
            if (simple !== "找到 12 张可评分照片") throw new Error("param resolution is wrong: " + simple);

            const nested = view.resolveTextRef({
              key: "jobText.scoringDoneDetail",
              params: { count: 3, device: { key: "device.appleSilicon" } },
            });
            if (nested !== "3 张照片 · Apple 芯片加速") throw new Error("nested ref is wrong: " + nested);

            const stats = view.resolveTextRef({
              key: "jobText.downloadStats",
              params: {
                downloaded: "41.0 MB",
                expected: "333.7 MB",
                speed: "2.1 MB/s",
                eta: { key: "duration.minutesSeconds", params: { minutes: 2, seconds: "10" } },
              },
            });
            if (stats !== "41.0 MB / 333.7 MB · 2.1 MB/s · 约 2分10秒") {
              throw new Error("download stats ref is wrong: " + stats);
            }

            const legacy = view.commandViewState({
              sourceReady: true,
              job: { kind: "llm_review", running: true, title: "旧版纯文本标题" },
            });
            if (legacy.title !== "旧版纯文本标题") throw new Error("legacy plain title should pass through");
            """
        )

    def test_mutation_and_maintenance_phases_have_localized_task_semantics(self) -> None:
        self.assert_js_passes(
            """
            const cases = [
              ["mutation", "exporting_photos", "正在导出", "正在导出入选照片", "Exporting", "Exporting picked photos"],
              ["mutation", "checking_export", "正在检查导出", "正在检查导出文件与目标目录", "Checking export", "Checking export files and destination"],
              ["mutation", "updating_curation", "正在保存人工判断", "正在更新照片判断", "Saving decisions", "Updating photo decisions"],
              ["mutation", "loading_source", "正在载入来源", "正在载入照片来源", "Loading source", "Loading photo source"],
              ["mutation", "uploading_photos", "正在导入", "正在导入上传照片", "Importing", "Importing uploaded photos"],
              ["mutation", "updating_models", "正在更新模型选择", "正在保存评分模型选择", "Updating model selection", "Saving scoring model selection"],
              ["mutation", "updating_network", "正在保存网络设置", "正在更新网络设置", "Saving network settings", "Updating network settings"],
              ["mutation", "updating_llm_config", "正在保存评审设置", "正在更新大模型评审设置", "Saving review settings", "Updating LLM review settings"],
              ["maintenance", "clearing_history", "正在清理评分记录", "正在清空本地评分记录", "Clearing score records", "Clearing local scoring records"],
              ["maintenance", "clearing_models", "正在清理模型", "正在清理已下载模型", "Clearing models", "Clearing downloaded models"],
              ["maintenance", "clearing_local_data", "正在重置本机数据", "正在清理本机记录与缓存", "Resetting local data", "Clearing local records and caches"],
            ];
            for (const language of ["zh-CN", "en"]) {
              context.CulviaI18n.setLanguage(language);
              for (const [kind, phase, zhState, zhTitle, enState, enTitle] of cases) {
                const result = view.commandViewState({ job: {
                  kind, phase, running: true, paused: true,
                  titleText: { key: "jobText.startingBackgroundTask" },
                  detailText: { key: "jobText.startingBackgroundTask" },
                  modelProgress: { progress: 0.9, label: "old model task" },
                  currentFile: "old-photo.jpg",
                } });
                const state = language === "en" ? enState : zhState;
                const title = language === "en" ? enTitle : zhTitle;
                if (result.state !== state || result.title !== title) {
                  throw new Error(`${language} ${phase} used the wrong task: ${result.state} / ${result.title}`);
                }
                if (!result.detail || result.detail.startsWith("command.") || result.detail === context.CulviaI18n.t("jobText.startingBackgroundTask")) {
                  throw new Error(`${phase} needs its own localized explanation`);
                }
                if (result.pause.visible || result.cancel.visible || !result.pause.disabled || !result.cancel.disabled) {
                  throw new Error(`${phase} exposes unsupported task controls`);
                }
                if (result.currentPhoto.visible || result.progress) throw new Error(`${phase} reused scoring progress`);
                const plan = view.commandDomPlan(result);
                if (!plan.buttons.pause.hidden || !plan.buttons.cancel.hidden) throw new Error("the rendered controls must be hidden");
              }
            }
            """
        )

    def test_export_progress_only_uses_a_running_receipt_for_the_export_phase(self) -> None:
        self.assert_js_passes(
            """
            const job = { kind: "mutation", phase: "exporting_photos", running: true, progress: 0.9 };
            const exportReceipt = { operationId: "current-export", status: "running", processed: 5, total: 20 };
            const active = view.commandViewState({ job, exportReceipt });
            if (active.state !== "正在导出" || active.progress?.width !== "25%" || active.progress?.detail !== "已处理 5 / 20 张") {
              throw new Error(`export receipt progress was not used: ${JSON.stringify(active.progress)}`);
            }
            for (const status of ["completed", "failed", "interrupted", "unknown"]) {
              if (view.commandViewState({ job, exportReceipt: { ...exportReceipt, status } }).progress) {
                throw new Error(`a ${status} receipt cannot supply current export progress`);
              }
            }
            for (const phase of ["checking_export", "updating_curation"]) {
              if (view.commandViewState({ job: { ...job, phase }, exportReceipt }).progress) {
                throw new Error("export progress leaked into another operation");
              }
            }
            for (const invalid of [{ total: 0 }, { total: "bad" }, { processed: -1 }, { processed: 30 }]) {
              if (view.commandViewState({ job, exportReceipt: { ...exportReceipt, ...invalid } }).progress) {
                throw new Error("invalid counters must not invent progress");
              }
            }
            context.CulviaI18n.setLanguage("en");
            const english = view.commandViewState({ job, exportReceipt });
            if (english.progress.detail !== "5 of 20 processed" || english.title !== "Exporting picked photos") {
              throw new Error("export progress must update when the language changes");
            }
            """
        )

    def test_unknown_jobs_are_conservative_and_controls_follow_supported_kinds(self) -> None:
        self.assert_js_passes(
            """
            for (const kind of ["future_task", "mutation", "maintenance"]) {
              const unknown = view.commandViewState({ job: {
                kind, running: true, phase: "cancelling", paused: true,
                titleText: { key: "jobText.scoring" }, currentFile: "old-photo.jpg",
                modelProgress: { progress: 0.5 },
              } });
              if (unknown.pause.visible || unknown.cancel.visible || unknown.currentPhoto.visible || unknown.progress) {
                throw new Error(`${kind} acquired scoring controls or progress`);
              }
              if (unknown.title.includes("评分") || unknown.state.includes("取消") || unknown.state.includes("暂停")) {
                throw new Error(`${kind} acquired unsupported task semantics`);
              }
              if (!unknown.mainScore.disabled || !unknown.llmReview.disabled) throw new Error("a running task must block new work");
            }
            for (const kind of [undefined, "", "scoring"]) {
              const scoring = view.commandViewState({ job: { kind, running: true, phase: "scoring" } });
              if (!scoring.pause.visible || !scoring.cancel.visible || scoring.state !== "正在评分") {
                throw new Error("explicit and legacy scoring must retain controls");
              }
            }
            const llm = view.commandViewState({ job: { kind: "llm_review", running: true, phase: "cancelling" } });
            if (llm.pause.visible || !llm.cancel.visible || !llm.cancel.disabled || llm.title !== "正在取消大模型评审") {
              throw new Error("LLM cancellation must not claim to cancel scoring or offer pause");
            }
            const preview = view.commandViewState({ job: { kind: "source_preview", running: true } });
            if (preview.pause.visible || preview.cancel.visible) throw new Error("source preview has no cancellation controls");
            """
        )

    def test_app_render_keeps_cancelling_controls_disabled_and_uses_current_receipt(self) -> None:
        self.assert_js_passes(
            """
            const elements = new Map();
            function element(selector) {
              if (!elements.has(selector)) {
                const classes = new Set();
                elements.set(selector, {
                  classList: {
                    add: (name) => classes.add(name),
                    toggle: (name, force) => force ? classes.add(name) : classes.delete(name),
                    contains: (name) => classes.has(name),
                  },
                  style: {}, removeAttribute: () => {}, textContent: "", innerHTML: "",
                });
              }
              return elements.get(selector);
            }
            Object.assign(context, {
              $: element,
              appState: { model: {}, summary: {}, llm: { configured: true } },
              commandNotice: null,
              commandView: view,
              displayNetworkLabel: () => "",
              escapeHtml: String,
              hasSelectedSource: () => true,
              llmConfigPanel: { llmModelsLoading: () => false },
              setButtonLabel: (button, icon, label) => { button.textContent = label; },
              setText: (selector, text) => { element(selector).textContent = text; },
              setTextWithHint: (selector, text) => { element(selector).textContent = text; },
            });
            const appSource = fs.readFileSync("web/app.js", "utf8");
            const jobHelpers = appSource.slice(appSource.indexOf("function isScoringJob("), appSource.indexOf("function matchingSourcePreview("));
            const commandRenderers = appSource.slice(appSource.indexOf("function applyCommandButtonPlan("), appSource.indexOf("function renderStats("));
            vm.runInContext(jobHelpers + commandRenderers, context);
            function renderJob(job) {
              context.appState.job = job;
              vm.runInContext("renderCommand(appState.model, appState.job, appState.summary); renderProgress(appState.job);", context);
            }
            const pause = element("#pauseJobBtn");
            const cancel = element("#cancelJobBtn");
            renderJob({ kind: "scoring", running: true, phase: "cancelling" });
            if (pause.classList.contains("is-hidden") || !pause.disabled || !cancel.disabled) {
              throw new Error("the complete render chain re-enabled a cancelling scoring control");
            }
            renderJob({ kind: "scoring", running: true, phase: "scoring" });
            if (pause.disabled || cancel.disabled) throw new Error("active scoring must keep supported controls");
            renderJob({ kind: "llm_review", running: true, phase: "cancelling" });
            if (!pause.classList.contains("is-hidden") || !pause.disabled || cancel.classList.contains("is-hidden") || !cancel.disabled) {
              throw new Error("rendered LLM controls do not match its cancellation capabilities");
            }
            context.appState.exportReceipt = { status: "running", processed: 2, total: 8 };
            renderJob({ kind: "mutation", running: true, phase: "exporting_photos" });
            if (!pause.classList.contains("is-hidden") || !cancel.classList.contains("is-hidden") || !pause.disabled || !cancel.disabled) {
              throw new Error("export exposes an unsupported rendered control");
            }
            if (element("#commandProgress").classList.contains("is-hidden") || element("#commandProgressBar").style.width !== "25%") {
              throw new Error("renderCommand did not pass the running receipt through to export progress");
            }
            context.appState.exportReceiptError = { errorCode: "exportReceiptStorageFailed" };
            renderJob({ kind: "mutation", running: true, phase: "exporting_photos" });
            if (!element("#commandProgress").classList.contains("is-hidden")) {
              throw new Error("a receipt read error must not display retained progress as current");
            }
            """
        )


if __name__ == "__main__":
    unittest.main()
