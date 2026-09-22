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


class FrontendI18nTests(unittest.TestCase):
    def assert_i18n_script_passes(self, body: str) -> None:
        bootstrap = textwrap.dedent(
            """
            const assert = require("node:assert/strict");
            const fs = require("fs");
            const vm = require("vm");
            const sandbox = {
              navigator: { language: "en-US" },
              localStorage: { getItem: () => null, setItem() {} },
              CustomEvent: function(name, init) { return { name, detail: init?.detail }; },
              document: {
                readyState: "loading", documentElement: {}, addEventListener() {},
                querySelector: () => null, querySelectorAll: () => [],
              },
              dispatchEvent() {},
            };
            sandbox.window = sandbox;
            vm.createContext(sandbox);
            function load(name) {
              vm.runInContext(fs.readFileSync(`web/${name}.js`, "utf8"), sandbox);
            }
            for (const name of ["locales/zh-CN", "locales/en", "i18n_messages", "i18n"]) load(name);
            const api = sandbox.CulviaI18n;
            const messages = sandbox.CulviaI18nMessages;
            """
        )
        result = subprocess.run(
            ["node", "-e", bootstrap + textwrap.dedent(body)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_photo_count_uses_singular_only_for_one(self) -> None:
        self.assert_i18n_script_passes(
            """
            for (const count of [0, 1, 2, 23, "1"]) {
              assert.equal(api.t("common.photoCount", { count }), `${count} ${Number(count) === 1 ? "photo" : "photos"}`);
              assert.equal(api.t("common.photoCount", { count }, "zh-CN"), `${count} 张`);
            }
            assert.equal(api.t("common.minutesAgo", { count: 1 }), "1 min ago");
            assert.equal(api.t("missing.key", { count: 1 }), "missing.key");
            """
        )

    def test_counted_workflow_messages_use_natural_singular_grammar(self) -> None:
        self.assert_i18n_script_passes(
            """
            const cases = [
              ["source.folderCount", "1 folder"],
              ["source.previewReadyTitle", "1 photo found"],
              ["source.uploadedCount", "1 image selected"],
              ["source.desktopDropDetail", "1 local path added. Scanning thumbnails now."],
              ["filters.remainingViews", "1 view remaining"],
              ["model.scoreRefreshNotice", "1 outdated or incomplete model result will be refreshed on the next scoring run."],
              ["jobText.photosReadyDetail", "Found 1 photo to score"],
              ["jobText.scoringDoneDetail", "1 photo · CPU"],
              ["jobText.sourceUpdatedDetail", "1 photo after deduplication"],
              ["jobText.llmPendingDetail", "1 photo needs review"],
              ["jobText.llmDoneDetail", "Reviewed 1 photo"],
              ["manual.ratingStars", "1 star"],
              ["score.missingTooltip", "1 uncalculated or unreviewed metric"],
              ["gallery.sourceCount", "1 unique photo"],
              ["export.guidanceReady", "2 picked for delivery; 1 still needs a decision."],
              ["export.guidancePending", "1 still needs a decision. Mark picks from Gallery or Review."],
              ["export.waitDestinationHint", "1 picked photo is waiting for an export destination."],
              ["export.preflightMissing", "1 original file is missing"],
              ["distribution.llmCoverage", "LLM 1 photo"],
              ["distribution.bucketTitle", "7-8: 1 photo"],
              ["distribution.heatTitle", "Hot zone 1 photo · average 7.5"],
              ["distribution.radarCurrent", "Current filter · 1 metric"],
              ["distribution.radarPriorityMeta", "Priority 8 · 1 photo"],
              ["distribution.dimensionMeta", "Average 8 · 1 photo"],
              ["batch.scopeSummary", "Selected · 1 photo"],
              ["batch.confirmCount", "1 photo · Selected"],
              ["batch.filteredLimitDetail", "Confirm. This updates the 1 matching photo; currently shown: 1."],
              ["llm.modelsCount", "1 model loaded"],
              ["history.summary.mark", "Updated 1 manual decision"],
            ];
            const params = {
              count: 1, device: "CPU", pending: 1, selected: 2, min: 7, max: 8,
              average: 7.5, score: 8, meta: "Average 8", scope: "Selected", detail: "Confirm.", showing: 1,
            };
            const format = (template, values) => template.replace(/\\{([A-Za-z0-9_]+)\\}/g, (_, key) => values[key] ?? "");
            for (const [key, expected] of cases) {
              assert.equal(api.t(key, params), expected, key);
              for (const count of [0, 2, 23]) {
                const values = { ...params, count, pending: count };
                assert.equal(api.t(key, values), format(messages.en[key], values), `${key}: ${count}`);
              }
              for (const count of [0, 1, 2, 23]) {
                const values = { ...params, count, pending: count };
                assert.equal(api.t(key, values, "zh-CN"), format(messages["zh-CN"][key], values), `${key}: Chinese ${count}`);
              }
            }
            assert.equal(api.t("batch.filteredLimitDetail", { ...params, count: 23 }),
              "Confirm. This updates all 23 matching photos; currently shown: 1.");
            """
        )

    def test_plural_selection_requires_a_valid_explicit_count(self) -> None:
        self.assert_i18n_script_passes(
            """
            Object.assign(messages.en, {
              "test.count": "Base {label}", "test.count.one": "One {label}", "test.count.other": "Other {label}",
            });
            for (const params of [{}, { shown: 1 }, { total: 1 }, ...[undefined, null, "", " ", "invalid", NaN, Infinity, true, false, [], [1], {}].map(count => ({ count }))]) {
              assert.equal(api.t("test.count", { ...params, label: "value" }), "Base value");
            }
            for (const count of [1, "1", " 1 "]) {
              assert.equal(api.t("test.count", { count, label: "value" }), "One value");
            }
            for (const count of [0, 2, 23, 1.5]) {
              assert.equal(api.t("test.count", { count, label: "value" }), "Other value");
            }
            assert.equal(api.t("export.resultPreview", { shown: 1, total: 23 }),
              "Showing 1 of 23 files. Download the full manifest for all results.");
            """
        )

    def test_plural_selection_uses_the_requested_language(self) -> None:
        self.assert_i18n_script_passes(
            """
            assert.equal(api.language(), "en");
            assert.equal(api.t("common.photoCount", { count: 1 }, "zh-Hans"), "1 张");
            assert.equal(api.t("common.photoCount", { count: 1 }, "en-GB"), "1 photo");
            api.setLanguage("zh-CN");
            assert.equal(api.t("common.photoCount", { count: 1 }), "1 张");
            assert.equal(api.t("common.photoCount", { count: 1 }, "en-US"), "1 photo");
            assert.equal(api.t("common.photoCount", { count: 1 }, "unsupported"), "1 张");
            """
        )

    def test_plural_fallback_preserves_the_resolved_dictionary_language(self) -> None:
        self.assert_i18n_script_passes(
            """
            Object.assign(messages["zh-CN"], {
              "test.fallback": "默认 {count}",
              "test.fallback.one": "错误单数 {count}",
              "test.fallback.other": "默认其他 {count}",
            });
            assert.equal(api.t("test.fallback", { count: 1 }, "en"), "默认其他 1");
            assert.equal(api.t("test.fallback", {}, "en"), "默认 ");
            messages.en["test.fallback"] = "English base {count}";
            assert.equal(api.t("test.fallback", { count: 1 }, "en"), "English base 1");
            messages.en["test.fallback.other"] = "English other {count}";
            assert.equal(api.t("test.fallback", { count: 1 }, "en"), "English other 1");
            messages.ru = {
              "test.category.one": "one", "test.category.few": "few",
              "test.category.many": "many", "test.category.other": "other",
            };
            for (const [count, expected] of [[1, "one"], [2, "few"], [5, "many"], [1.5, "other"]]) {
              assert.equal(api.t("test.category", { count }, "ru"), expected);
            }
            """
        )

    def test_delivery_guidance_does_not_require_scoring_or_pluralize_labels(self) -> None:
        self.assert_i18n_script_passes(
            """
            assert.equal(api.t("export.guidanceEmpty"), "Add photos, then mark picks in Gallery or Review.");
            assert.equal(api.t("export.guidanceEmpty", {}, "zh-CN"), "添加照片后，可在照片墙或逐张审看中标记入选。");
            assert.equal(api.t("export.curationSummary", { selected: 1, rated: 1, filteredSelected: 1 }),
              "Picked: 1 · Manually rated: 1 · Picks in filter: 1");
            """
        )

    def test_export_manifest_grammar_uses_total_not_preview_count(self) -> None:
        self.assert_i18n_script_passes(
            """
            for (const name of ["ui_helpers", "export_result_data", "export_result"]) load(name);
            const helpers = {
              ...sandbox.CulviaUiHelpers,
              pathName: value => value.split("/").pop(), parentPath: () => "/photos",
            };
            for (const total of [1, 23]) {
              const receipt = sandbox.CulviaExportResult.renderMarkup({
                operationId: "receipt", status: "completed", copied: total, totalEntryCount: total,
                previewEntries: [{ source: "/photos/photo.jpg", status: "copied" }],
              }, helpers);
              const legacy = sandbox.CulviaExportResult.renderMarkup({
                copied: total, copiedFiles: ["/photos/photo.jpg"],
              }, helpers);
              const expected = `Showing 1 of ${total} ${total === 1 ? "file" : "files"}.`;
              assert.ok(receipt.includes(expected), receipt);
              assert.ok(legacy.includes(expected), legacy);
            }
            """
        )

    def test_distribution_decision_grammar_uses_each_sentences_photo_count(self) -> None:
        self.assert_i18n_script_passes(
            """
            for (const name of ["ui_helpers", "distribution_model", "distribution_view"]) load(name);
            const view = sandbox.CulviaDistributionView;
            const cases = [
              ["overview", "1 photo is in the priority zone"],
              ["technical", "1 photo is below the technical stability line"],
              ["llm", "LLM covers 1/1 photo."],
              ["aesthetic", "1 photo has stronger aesthetic detail."],
              ["disagreement", "1 photo shows clear model disagreement."],
            ];
            const entries = [{ score: 1, llm: 8 }];
            const stats = sandbox.CulviaDistributionModel.stats([1]);
            for (const [lens, expected] of cases) {
              const html = view.distributionDecision(lens, entries, entries, view.distributionLensConfig(lens), stats, 0, 1, "0-1");
              assert.ok(html.includes(expected), `${lens}: ${html}`);
              assert.ok(!html.includes("1 photos"), `${lens}: ${html}`);
            }
            const allEntries = [...entries, ...Array.from({ length: 22 }, () => ({ llm: null }))];
            const html = view.distributionDecision("llm", entries, allEntries, view.distributionLensConfig("llm"), stats, 0, 1, "0-1");
            assert.ok(html.includes("LLM covers 1/23 photos."), html);
            """
        )

    def test_message_locales_have_matching_keys(self) -> None:
        messages = load_i18n_messages()

        self.assertIn("zh-CN", messages)
        self.assertIn("en", messages)
        self.assertEqual(set(messages["zh-CN"]), set(messages["en"]))

    def test_message_locale_blocks_do_not_repeat_keys(self) -> None:
        messages = load_i18n_messages()

        for locale in messages:
            text = locale_script(locale).read_text(encoding="utf-8")
            keys = re.findall(r'^\s*"([^"]+)"\s*:', text, flags=re.MULTILINE)
            duplicates = sorted({key for key in keys if keys.count(key) > 1})
            self.assertEqual(duplicates, [], f"{locale} duplicate i18n keys")

    def test_dynamic_js_i18n_keys_exist_in_all_locales(self) -> None:
        messages = load_i18n_messages()
        keys: set[str] = set()
        for path in WEB.glob("*.js"):
            if path.name == "i18n_messages.js":
                continue
            text = path.read_text(encoding="utf-8")
            keys.update(re.findall(r'\b(?:t|tr)\(\s*["\']([^"\']+)["\']', text))

        self.assertTrue(keys)
        for locale, dictionary in messages.items():
            missing = sorted(keys - set(dictionary))
            self.assertEqual(missing, [], f"{locale} missing dynamic JS i18n keys")

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

    def test_language_switch_refreshes_tooltip_derived_accessible_names(self) -> None:
        script = textwrap.dedent(
            f"""
            const fs = require("fs");
            const vm = require("vm");
            class FakeElement {{
              constructor(attributes) {{
                this.attributes = {{ ...attributes }};
                this.dataset = {{}};
              }}
              getAttribute(name) {{ return this.attributes[name] ?? null; }}
              hasAttribute(name) {{ return Object.hasOwn(this.attributes, name); }}
              setAttribute(name, value) {{ this.attributes[name] = String(value); }}
              removeAttribute(name) {{ delete this.attributes[name]; }}
            }}
            const tooltipOnly = new FakeElement({{
              "data-i18n-tooltip": "views.viewer",
              "aria-label": "stale label",
            }});
            const explicitAria = new FakeElement({{
              "data-i18n-tooltip": "views.viewer",
              "data-i18n-aria-label": "viewer.prev",
              "aria-label": "stale label",
            }});
            const sandbox = {{
              console,
              navigator: {{ language: "zh-CN" }},
              localStorage: {{ getItem: () => null, setItem: () => {{}} }},
              CustomEvent: function CustomEvent(name, init) {{ return {{ name, detail: init.detail }}; }},
              document: {{
                title: "",
                readyState: "loading",
                documentElement: {{}},
                addEventListener: () => {{}},
                querySelector: () => null,
                querySelectorAll: (selector) => {{
                  if (selector === "[data-i18n-tooltip]") return [tooltipOnly, explicitAria];
                  if (selector === "[data-i18n-aria-label]") return [explicitAria];
                  return [];
                }},
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
            api.apply();
            const zh = {{
              tooltipOnly: tooltipOnly.getAttribute("aria-label"),
              explicitAria: explicitAria.getAttribute("aria-label"),
            }};
            api.setLanguage("en");
            console.log(JSON.stringify({{
              zh,
              en: {{
                tooltipOnly: tooltipOnly.getAttribute("aria-label"),
                explicitAria: explicitAria.getAttribute("aria-label"),
                tooltip: explicitAria.dataset.uiTooltip,
              }},
            }}));
            """
        )

        result = subprocess.run(["node", "-e", script], text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        output = json.loads(result.stdout)
        self.assertEqual(output["zh"], {"tooltipOnly": "逐张审看", "explicitAria": "上一张"})
        self.assertEqual(
            output["en"],
            {"tooltipOnly": "Review", "explicitAria": "Previous photo", "tooltip": "Review"},
        )

    def test_gallery_localizes_missing_score_text_in_cards_and_tooltips(self) -> None:
        script = textwrap.dedent(
            """
            const fs = require("fs");
            const vm = require("vm");
            const context = { console };
            context.window = context;
            context.CulviaI18n = {
              t(key) { return key === "export.listNoRecommendation" ? "No recommendation yet" : key; },
            };
            vm.createContext(context);
            ["web/manual_status.js", "web/icons.js", "web/ui_helpers.js", "web/gallery_view.js", "web/export_list.js"]
              .forEach((file) => vm.runInContext(fs.readFileSync(file, "utf8"), context, { filename: file }));

            const photo = {
              fileId: "photo-1",
              path: "/photos/photo-1.jpg",
              thumb: "thumb.jpg",
              level: "未评分",
              recommendationText: "暂无",
              overallText: "暂无",
              recommendationStars: "☆☆☆☆☆",
              manual: {},
            };
            const options = {
              t(key) { return key === "common.noData" ? "None" : key; },
              localizedMetricText(value, missing) { return value === "暂无" ? missing : value; },
              localizedScoreLevel() { return "Unrated"; },
              localizedManualSource() { return "Unconfirmed"; },
              manualStatusLabel() { return "Unreviewed"; },
              manualStars() { return "☆☆☆☆☆"; },
              galleryColorBadgeMarkup() { return ""; },
              galleryQuickActionLabel() { return "Action"; },
              gallerySelectLabel() { return "Select"; },
            };
            const card = context.CulviaGalleryView.cardMarkup(photo, 0, false, "signature", options);
            const tooltip = context.CulviaGalleryView.tooltipMarkup(photo, options);
            const exportList = context.CulviaExportList.renderMarkup([photo], {
              canRevealFile: false,
              escapeHtml: context.CulviaUiHelpers.escapeHtml,
              iconMarkup: context.CulviaUiHelpers.iconMarkup,
              localizedMetricText: options.localizedMetricText,
              localizedScoreLevel: options.localizedScoreLevel,
              manualBadgeMarkup() { return ""; },
              pathName() { return "photo-1.jpg"; },
            });
            if (card.includes("暂无") || tooltip.includes("暂无") || exportList.includes("暂无")) {
              throw new Error("Chinese missing-score text leaked into English markup");
            }
            if (!card.includes(">None</strong>") || !tooltip.includes(">None</strong>")) {
              throw new Error("localized missing-score text was not rendered");
            }
            if (!exportList.includes("No recommendation yet")) {
              throw new Error("export list did not localize its missing score");
            }
            """
        )
        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
