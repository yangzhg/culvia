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
            if (!waiting.mainScore.disabled || waiting.mainScore.label !== "准备模型并评分") {
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
            if (ready.mainScore.icon !== "play" || ready.mainScore.label !== "开始评分") {
              throw new Error("ready button state is wrong");
            }
            if (ready.llmReview.disabled || ready.llmReview.label !== "大模型评审") {
              throw new Error("ready LLM review button state is wrong");
            }

            const summary = view.commandViewState({
              hasResults: true,
              sourceReady: true,
              summary: { scored: 12, showing: 5 },
            });
            if (!summary.compact || summary.dotTone !== "ready" || summary.state !== "结果已就绪") {
              throw new Error("summary state is wrong");
            }
            if (!summary.detail.includes("已评分 12 张，当前展示 5 张")) {
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
                title: "正在进行大模型评审",
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
                activeEvaluation: "大模型评审",
                completedEvaluations: ["基础质检", "审美"],
                currentFile: "portrait.jpg",
                currentThumb: "/api/image/thumb",
                paused: true,
                progress: 0.42,
                running: true,
                title: "处理照片",
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

            const preparing = view.commandViewState({
              sourceReady: true,
              job: {
                modelProgress: { detail: "下载权重", label: "准备模型", progress: 1.4 },
                running: true,
              },
            });
            if (preparing.progress.width !== "100%" || preparing.currentPhoto.visible) {
              throw new Error("model progress should clamp and hide current photo");
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


if __name__ == "__main__":
    unittest.main()
