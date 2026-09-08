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
