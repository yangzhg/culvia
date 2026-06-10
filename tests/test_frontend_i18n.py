from __future__ import annotations

import json
import re
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
LOCALES = ("zh-CN", "en")


def locale_script(locale: str) -> Path:
    return WEB / "locales" / f"{locale}.js"


def load_locale_scripts_js() -> str:
    return "\n".join(
        f'vm.runInContext(fs.readFileSync({json.dumps(str(locale_script(locale)))}, "utf8"), sandbox);'
        for locale in LOCALES
    )


def load_i18n_messages() -> dict[str, dict[str, str]]:
    script = textwrap.dedent(
        f"""
        const fs = require("fs");
        const vm = require("vm");
        const sandbox = {{ window: {{}} }};
        vm.createContext(sandbox);
        {load_locale_scripts_js()}
        vm.runInContext(fs.readFileSync({json.dumps(str(WEB / "i18n_messages.js"))}, "utf8"), sandbox);
        console.log(JSON.stringify(sandbox.window.CulviaI18nMessages));
        """,
    )
    result = subprocess.run(["node", "-e", script], text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return json.loads(result.stdout)


def locale_source_body(text: str, locale: str) -> str:
    match = re.search(rf"CulviaLocaleMessages\[{json.dumps(locale)}\]\s*=\s*\{{", text)
    if not match:
        raise AssertionError(f"missing locale block: {locale}")
    start = text.index("{", match.start())
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : index]
    raise AssertionError(f"unterminated locale block: {locale}")


class FrontendI18nTests(unittest.TestCase):
    def test_message_locales_have_matching_keys(self) -> None:
        messages = load_i18n_messages()

        self.assertIn("zh-CN", messages)
        self.assertIn("en", messages)
        self.assertEqual(set(messages["zh-CN"]), set(messages["en"]))

    def test_message_locale_blocks_do_not_repeat_keys(self) -> None:
        messages = load_i18n_messages()

        for locale in messages:
            text = locale_script(locale).read_text(encoding="utf-8")
            keys = re.findall(r'^\s*"([^"]+)"\s*:', locale_source_body(text, locale), flags=re.MULTILINE)
            duplicates = sorted({key for key in keys if keys.count(key) > 1})
            self.assertEqual(duplicates, [], f"{locale} duplicate i18n keys")

    def test_high_risk_dynamic_i18n_modules_do_not_embed_cjk_fallbacks(self) -> None:
        for filename in ("shortcuts.js", "command_view.js", "llm_config_view.js"):
            text = (WEB / filename).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"[\u4e00-\u9fff]", text), filename)

    def test_dynamic_js_i18n_keys_exist_in_all_locales(self) -> None:
        messages = load_i18n_messages()
        keys: set[str] = set()
        for path in WEB.glob("*.js"):
            if path.name == "i18n_messages.js":
                continue
            text = path.read_text(encoding="utf-8")
            keys.update(re.findall(r'\b(?:t|tr)\(\s*["\']([^"\']+)["\']', text))

        self.assertTrue(keys)
        self.assertIn("viewer.beforeCount", keys)
        self.assertIn("gallery.viewPhoto", keys)
        for locale, dictionary in messages.items():
            missing = sorted(keys - set(dictionary))
            self.assertEqual(missing, [], f"{locale} missing dynamic JS i18n keys")

    def test_high_visibility_dynamic_notices_use_i18n_resources(self) -> None:
        app_js = (WEB / "app.js").read_text(encoding="utf-8")

        for stale_literal in (
            'curationHistoryError = "暂时无法读取最近操作"',
            '$("#uploadHint").textContent = "正在整理上传图片..."',
            'window.confirm("清空评分记录',
            'window.confirm("删除本机模型文件',
            'window.confirm("清除后，大模型评审',
            'state: "正在撤销"',
            'label: "撤销"',
            'state: "已批量标记"',
            'title: "模型列表已更新"',
            'title: "没有保存大模型配置"',
        ):
            self.assertNotIn(stale_literal, app_js)

        for expected_key in (
            't("history.error")',
            't("source.uploading")',
            't("maintenance.clearScoresConfirm")',
            't("maintenance.clearScoresConfirmTitle")',
            't("maintenance.clearLocalDataConfirm")',
            't("maintenance.clearLocalDataConfirmTitle")',
            't("maintenance.removeModelsConfirm")',
            't("maintenance.removeModelsConfirmTitle")',
            't("llm.clearKeyConfirm")',
            't("llm.clearKeyConfirmTitle")',
            't("restore.restoringState")',
            't("restore.restoredState")',
            't("batch.statusMarkedState")',
            't("llm.modelsLoadedTitle")',
            't("filters.saveTitle"',
        ):
            self.assertIn(expected_key, app_js)

    def test_i18n_runtime_normalizes_and_translates(self) -> None:
        script = textwrap.dedent(
            f"""
            const fs = require("fs");
            const vm = require("vm");
            const sandbox = {{
              console,
              navigator: {{ language: "en-US" }},
              localStorage: {{ getItem: () => null, setItem: () => {{}} }},
              CustomEvent: function CustomEvent(name, init) {{ return {{ name, detail: init.detail }}; }},
              document: {{
                title: "",
                readyState: "loading",
                documentElement: {{}},
                addEventListener: () => {{}},
                querySelector: () => null,
                querySelectorAll: () => [],
              }},
              window: {{
                addEventListener: () => {{}},
                dispatchEvent: () => {{}},
              }},
            }};
            vm.createContext(sandbox);
            {load_locale_scripts_js()}
            vm.runInContext(fs.readFileSync({json.dumps(str(WEB / "i18n_messages.js"))}, "utf8"), sandbox);
            vm.runInContext(fs.readFileSync({json.dumps(str(WEB / "i18n.js"))}, "utf8"), sandbox);
            const api = sandbox.window.CulviaI18n;
            const output = {{
              language: api.language(),
              normalized: api.normalizeLanguage("en-US"),
              start: api.t("command.start"),
              fallback: api.t("missing.key"),
              next: api.setLanguage("zh-Hans"),
              zhStart: api.t("command.start"),
              title: sandbox.document.title,
              lang: sandbox.document.documentElement.lang,
            }};
            console.log(JSON.stringify(output));
            """,
        )

        result = subprocess.run(["node", "-e", script], text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        output = json.loads(result.stdout)
        self.assertEqual(output["language"], "en")
        self.assertEqual(output["normalized"], "en")
        self.assertEqual(output["start"], "Score")
        self.assertEqual(output["fallback"], "missing.key")
        self.assertEqual(output["next"], "zh-CN")
        self.assertEqual(output["zhStart"], "评分")
        self.assertEqual(output["title"], "Culvia")
        self.assertEqual(output["lang"], "zh-CN")

    def test_language_messages_are_resource_driven(self) -> None:
        messages = load_i18n_messages()
        for locale, dictionary in messages.items():
            for key in (
                "settings.languageName.zh-CN",
                "settings.languageName.en",
                "settings.languageShort.zh-CN",
                "settings.languageShort.en",
                "settings.languageBadge.zh-CN",
                "settings.languageBadge.en",
            ):
                self.assertIn(key, dictionary, f"{locale} missing {key}")

    def test_score_signal_labels_stay_compact_for_inspector_chips(self) -> None:
        messages = load_i18n_messages()
        signal_keys = (
            "score.signal.overall",
            "score.signal.aestheticReference",
            "score.signal.llm",
            "score.signal.technical",
            "score.signal.notCalculated",
            "score.signal.notReviewed",
        )

        for locale, dictionary in messages.items():
            for key in signal_keys:
                self.assertIn(key, dictionary, f"{locale} missing {key}")

        english = messages["en"]
        for key in signal_keys:
            self.assertLessEqual(len(english[key]), 15, f"{key} is too long for compact inspector chips")

    def test_app_localizes_cached_score_levels_and_missing_metric_text(self) -> None:
        app_js = (WEB / "app.js").read_text(encoding="utf-8")
        gallery_view_js = (WEB / "gallery_view.js").read_text(encoding="utf-8")
        frontend_js = app_js + gallery_view_js
        messages = load_i18n_messages()

        for key in (
            "scoreLevel.coverCandidate",
            "scoreLevel.worthRetouching",
            "scoreLevel.keepForReview",
            "scoreLevel.lowPriority",
            "scoreLevel.unrated",
            "technicalTag.sharpStable",
            "technicalTag.exposureStable",
            "technicalTag.tonalClear",
            "manual.source.manual",
            "manual.source.model",
            "manual.source.llm",
            "manual.source.modelBatch",
            "manual.source.llmBatch",
        ):
            self.assertIn(key, messages["zh-CN"])
            self.assertIn(key, messages["en"])

        self.assertIn("localizedScoreLevel", frontend_js)
        self.assertIn("localizedMetricText", frontend_js)
        self.assertIn("localizedTechnicalTag", frontend_js)
        self.assertIn("localizedManualSource", frontend_js)
        self.assertIn('text === "暂无"', app_js)
        self.assertIn('text === "未判断"', app_js)
        self.assertIn('localizedMetricText?.(value, options.t?.("common.noData"))', gallery_view_js)

    def test_app_localizes_api_error_codes(self) -> None:
        api_client_js = (WEB / "api_client.js").read_text(encoding="utf-8")
        messages = load_i18n_messages()

        for key in (
            "apiError.exportDestinationRequired",
            "apiError.exportNoPicks",
            "apiError.llmModelListInvalid",
            "apiError.revealOutsideSource",
            "apiError.jobRunningLlmConfig",
            "apiError.desktopActionCancelled",
            "apiError.selectedPhotosMissing",
            "apiError.restoreMarksMissing",
            "apiError.curationUndoAlreadyUndone",
            "apiError.curationUndoNoRestorableAction",
            "apiError.curationUndoOutsideSource",
            "apiError.curationUndoConflict",
            "apiError.imageAccessDenied",
            "apiError.thumbnailAccessDenied",
            "apiError.mediaNotFound",
            "apiError.imageGenerationFailed",
            "apiError.thumbnailGenerationFailed",
        ):
            self.assertIn(key, messages["zh-CN"])
            self.assertIn(key, messages["en"])

        self.assertIn("parsed?.errorCode", api_client_js)
        self.assertIn("errorParams", api_client_js)
        self.assertIn("apiError.${parsed.errorCode}", api_client_js)

    def test_distribution_deep_chart_labels_use_i18n_resources(self) -> None:
        distribution_view_js = (WEB / "distribution_view.js").read_text(encoding="utf-8")
        messages = load_i18n_messages()

        for key in (
            "distribution.radarKicker",
            "distribution.radarCurrent",
            "distribution.stackKicker",
            "distribution.lowScoreBand",
            "distribution.metric.recommendation.label",
            "distribution.metric.composition.axis",
            "distribution.metric.llmCoverage.label",
        ):
            self.assertIn(key, messages["zh-CN"])
            self.assertIn(key, messages["en"])

        for stale_literal in (
            "<span>总览画像</span>",
            "当前筛选 · ${metrics.length} 项指标",
            "<span>低分段</span>",
            "大模型覆盖",
        ):
            self.assertNotIn(stale_literal, distribution_view_js)

        self.assertIn("distributionMetricLabel", distribution_view_js)
        self.assertIn("distributionMetricAxis", distribution_view_js)


if __name__ == "__main__":
    unittest.main()
