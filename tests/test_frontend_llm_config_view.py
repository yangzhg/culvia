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
vm.runInContext(fs.readFileSync("web/llm_config_view.js", "utf8"), context);

const view = context.window.CulviaLlmConfigView;
if (!view) throw new Error("module was not registered");
"""


class FrontendLlmConfigViewTests(unittest.TestCase):
    def assert_js_passes(self, body: str) -> None:
        script = textwrap.dedent(f"{MODULE_BOOTSTRAP}\n{body}")
        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_labels_summaries_and_model_option_helpers(self) -> None:
        self.assert_js_passes(
            """
            if (view.sourceLabel("env") !== "环境变量") throw new Error("env source label is wrong");
            if (view.sourceLabel("session") !== "当前会话") throw new Error("session source label is wrong");
            if (view.sourceLabel("keychain") !== "系统钥匙串") throw new Error("keychain source label is wrong");
            if (view.sourceLabel("sqlite") !== "本地库") throw new Error("sqlite source label is wrong");
            if (view.sourceLabel("") !== "未配置") throw new Error("empty source label is wrong");
            if (view.sourceLabel("自定义") !== "自定义") throw new Error("custom source label should pass through");

            const llm = {
              promptPreset: "retouching",
              promptPresets: [
                { value: "balanced", label: "综合", prompt: "综合默认提示词" },
                { value: "retouching", label: "修图", prompt: "修图默认提示词" },
              ],
            };
            if (view.promptPresetLabel(llm) !== "修图") throw new Error("prompt preset label is wrong");
            if (view.promptPresetPrompt(llm) !== "修图默认提示词") throw new Error("prompt preset text is wrong");
            if (view.promptPresetPrompt(llm, "balanced") !== "综合默认提示词") {
              throw new Error("explicit prompt preset text is wrong");
            }
            if (view.promptPresetLabel({ promptPreset: "unknown", promptPresets: [] }) !== "unknown") {
              throw new Error("unknown prompt preset should pass through");
            }
            if (view.customPromptSummary("   ") !== "") throw new Error("blank custom prompt should stay empty");
            if (view.customPromptSummary("1234567890123456789012345678") !== "123456789012345678901234...") {
              throw new Error("custom prompt summary should truncate");
            }

            const options = view.normalizedModelOptions({
              currentModel: "qwen-plus",
              fallbackModel: "fallback-model",
              providerOptions: [
                { id: "qwen-plus" },
                { value: "qwen-vl", source: "provider" },
                { label: "deepseek-vl" },
                { value: "" },
              ],
            });
            if (options.length !== 3) throw new Error(`unexpected model option count ${options.length}`);
            if (options[0].value !== "qwen-plus" || options[0].source !== "current") {
              throw new Error("current model option should be first");
            }
            if (options[1].value !== "qwen-vl" || options[2].value !== "deepseek-vl") {
              throw new Error("provider model options were not normalized");
            }
            const fallback = view.normalizedModelOptions({ fallbackModel: "fallback-model" });
            if (fallback.length !== 1 || fallback[0].value !== "fallback-model") {
              throw new Error("fallback model option missing");
            }
            if (view.modelButtonMeta({ source: "current" }, true) !== "当前配置") {
              throw new Error("current model meta is wrong");
            }
            if (view.modelButtonMeta({ source: "provider" }, true) !== "已读取模型列表") {
              throw new Error("provider model meta is wrong");
            }
            if (view.modelButtonMeta({ source: "provider" }, false) !== "从列表选择模型") {
              throw new Error("empty model list meta is wrong");
            }
            if (view.modelListResultMessage([{ value: "qwen" }, { value: "deepseek" }]) !== "已读取 2 个模型") {
              throw new Error("model list result message count is wrong");
            }
            if (view.modelListResultMessage([]) !== "没有可用模型") {
              throw new Error("empty model list result message is wrong");
            }
            if (view.modelListResultMessage(3) !== "已读取 3 个模型") {
              throw new Error("numeric model list result message is wrong");
            }
            """
        )

    def test_model_picker_state(self) -> None:
        self.assert_js_passes(
            """
            const pickerState = view.modelPickerState({
              currentModel: "qwen-plus",
              providerOptions: [{ value: "qwen-plus" }, { value: "qwen-vl" }, { value: "deepseek-vl" }],
              selectedModel: "qwen-vl",
              searchQuery: "vl",
            });
            if (pickerState.buttonText !== "qwen-vl" || pickerState.buttonMeta !== "已读取模型列表") {
              throw new Error("model picker button state is wrong");
            }
            if (pickerState.visibleOptions.length !== 2) {
              throw new Error(`unexpected filtered option count ${pickerState.visibleOptions.length}`);
            }
            const selectedView = pickerState.visibleOptions.find((option) => option.value === "qwen-vl");
            if (!selectedView?.active || selectedView.ariaSelected !== "true") {
              throw new Error("selected model view state is wrong");
            }
            const currentView = view.modelPickerState({ currentModel: "current-model", providerOptions: [] });
            if (currentView.buttonMeta !== "当前配置") throw new Error("current model picker meta is wrong");
            """
        )

    def test_prompt_option_views(self) -> None:
        self.assert_js_passes(
            """
            const promptViews = view.promptOptionViews({
              promptPreset: "retouching",
              promptPresets: [
                { value: "balanced", label: "综合", description: "整体", prompt: "综合提示词" },
                { value: "retouching", label: "修图", description: "后期", prompt: "修图提示词" },
              ],
            });
            if (promptViews.length !== 2) throw new Error("prompt option views missing");
            if (promptViews[0].ariaChecked !== "false") {
              throw new Error("inactive prompt option view is wrong");
            }
            if (promptViews[1].ariaChecked !== "true") {
              throw new Error("active prompt option view is wrong");
            }
            if (promptViews[1].prompt !== "修图提示词") {
              throw new Error("prompt option should carry default prompt text");
            }
            """
        )

    def test_config_form_payload_normalizes_values(self) -> None:
        self.assert_js_passes(
            """
            const connection = view.connectionPayload({
              apiKey: "  demo-key  ",
              baseUrl: "  https://example.invalid/v1  ",
              model: "  qwen-vl-plus  ",
              promptPreset: "retouching",
              persist: true,
              cachePath: "  /tmp/scores.sqlite  ",
            });
            if (connection.apiKey !== "demo-key") throw new Error("connection api key should be trimmed");
            if (connection.baseUrl !== "https://example.invalid/v1") {
              throw new Error("connection base url should be trimmed");
            }
            if (connection.model !== "qwen-vl-plus") throw new Error("connection model should be trimmed");
            if (connection.cachePath !== "/tmp/scores.sqlite") throw new Error("connection cache path should be trimmed");
            if (Object.keys(connection).sort().join(",") !== "apiKey,baseUrl,cachePath,model") {
              throw new Error("connection payload should only include connection fields");
            }

            const payload = view.configFormPayload({
              apiKey: "  sk-test-key  ",
              baseUrl: "  https://dashscope.aliyuncs.com/compatible-mode/v1  ",
              model: "  qwen-vl-plus  ",
              promptPreset: "  retouching  ",
              customPrompt: "  强调人物肤色  ",
              persist: "yes",
              cachePath: "  /tmp/scores.sqlite  ",
            });
            if (payload.apiKey !== "sk-test-key") throw new Error("api key should be trimmed");
            if (payload.baseUrl !== "https://dashscope.aliyuncs.com/compatible-mode/v1") {
              throw new Error("base url should be trimmed");
            }
            if (payload.model !== "qwen-vl-plus") throw new Error("model should be trimmed");
            if (payload.promptPreset !== "retouching") throw new Error("prompt preset should be trimmed");
            if (payload.customPrompt !== "强调人物肤色") throw new Error("custom prompt should be trimmed");
            if (payload.persist !== true) throw new Error("persist should be boolean true");
            if (payload.cachePath !== "/tmp/scores.sqlite") throw new Error("cache path should be trimmed");
            if ("clearKey" in payload) throw new Error("clearKey should be omitted by default");

            const fallback = view.configFormPayload({ promptPreset: "   ", persist: 0, clearKey: true });
            if (fallback.promptPreset !== "balanced") throw new Error("blank prompt preset should fall back");
            if (fallback.persist !== false) throw new Error("persist should be boolean false");
            if (fallback.clearKey !== true) throw new Error("clear key payload flag missing");
            if (fallback.apiKey !== "" || fallback.baseUrl !== "" || fallback.model !== "") {
              throw new Error("missing string fields should normalize to empty strings");
            }
            """
        )

    def test_config_view_state(self) -> None:
        self.assert_js_passes(
            """
            const configuredState = view.configViewState(
              {
                configured: true,
                keyLabel: "sk-3****3931",
                source: "sqlite",
                baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
                endpoint: "https://fallback.example/v1",
                model: "qwen-vl-plus",
                promptPreset: "retouching",
                customPrompt: "强调人物肤色和背景层次",
                promptPresets: [
                  { value: "balanced", label: "综合" },
                  { value: "retouching", label: "修图" },
                ],
              },
              { editing: true, modelsLoading: false, modelListMessage: "已读取 12 个模型" },
            );
            if (configuredState.statusText !== "已配置" || !configuredState.statusReady) {
              throw new Error("configured status state is wrong");
            }
            if (!configuredState.readonlyHidden || configuredState.editorHidden || configuredState.cancelHidden) {
              throw new Error("editing visibility state is wrong");
            }
            if (configuredState.readonly.source !== "本地库") throw new Error("readonly source is wrong");
            if (!configuredState.readonly.prompt.includes("修图") || !configuredState.readonly.prompt.includes("强调人物肤色")) {
              throw new Error("readonly prompt summary is wrong");
            }
            if (configuredState.inputs.apiKeyPlaceholder !== "sk-3****3931，输入新密钥可替换") {
              throw new Error("api key placeholder is wrong");
            }
            if (configuredState.inputs.baseUrlValue !== "https://dashscope.aliyuncs.com/compatible-mode/v1") {
              throw new Error("base url value is wrong");
            }
            if (configuredState.modelListHint !== "已读取 12 个模型") {
              throw new Error("model list message should win");
            }
            if (!configuredState.hint.includes("来源：本地库")) throw new Error("configured hint source is wrong");

            const loadingState = view.configViewState(
              { configured: false, endpoint: "https://default.example/v1" },
              { editing: false, modelsLoading: true },
            );
            if (loadingState.statusText !== "未配置" || loadingState.statusReady) {
              throw new Error("unconfigured status state is wrong");
            }
            if (loadingState.readonlyHidden || !loadingState.editorHidden || loadingState.editHidden) {
              throw new Error("readonly visibility state is wrong");
            }
            if (loadingState.inputs.apiKeyPlaceholder !== "API Key") {
              throw new Error("empty key placeholder is wrong");
            }
            if (loadingState.inputs.baseUrlPlaceholder !== "https://default.example/v1") {
              throw new Error("endpoint should become base url placeholder");
            }
            if (loadingState.modelListHint !== "正在读取模型列表..." || loadingState.refreshIcon !== "loader") {
              throw new Error("loading model list state is wrong");
            }
            if (loadingState.saveButton.label !== "正在读取模型列表...") {
              throw new Error("save button should show loading state while models load");
            }

            const unconfiguredState = view.configViewState({ configured: false });
            if (unconfiguredState.saveButton.label !== "保存设置") {
              throw new Error("save button should be final save, not an intermediate fetch action");
            }
            """
        )


if __name__ == "__main__":
    unittest.main()
