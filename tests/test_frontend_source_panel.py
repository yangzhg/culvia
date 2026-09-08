from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def render_summary_scenarios() -> dict[str, dict[str, object]]:
    script = textwrap.dedent(
        """
        const fs = require("fs");
        const vm = require("vm");

        const context = { console };
        context.window = context;
        vm.createContext(context);
        vm.runInContext(fs.readFileSync("web/locales/en.js", "utf8"), context);
        vm.runInContext(fs.readFileSync("web/locales/zh-CN.js", "utf8"), context);
        vm.runInContext(fs.readFileSync("web/source_panel.js", "utf8"), context);

        let folders = [];
        let state = {};
        const summary = {
          _html: "",
          _text: "",
          attributes: { "data-i18n": "source.empty" },
          dataset: {},
          get innerHTML() {
            return this._html;
          },
          set innerHTML(value) {
            this._html = String(value);
            this._text = "";
          },
          get textContent() {
            return this._text;
          },
          set textContent(value) {
            this._text = String(value);
            this._html = "";
          },
          removeAttribute(name) {
            delete this.attributes[name];
          },
          setAttribute(name, value) {
            this.attributes[name] = String(value);
          },
        };
        const elements = {
          "#folderSummary": summary,
          "#folderList": {
            querySelectorAll() {
              return folders.map((value) => ({ value }));
            },
          },
        };
        const $ = (selector) => elements[selector] || null;
        const escapeHtml = (value) =>
          String(value)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
        const pathName = (path) => {
          const normalized = String(path || "").replaceAll("\\\\", "/").replace(/\\/+$/, "");
          return normalized.split("/").filter(Boolean).pop() || normalized || "Unknown";
        };
        const translate = (language, key, params = {}) => {
          let value = context.window.CulviaLocaleMessages[language][key] || key;
          Object.entries(params).forEach(([name, replacement]) => {
            value = value.replaceAll(`{${name}}`, String(replacement));
          });
          return value;
        };
        const panel = (language) =>
          context.window.CulviaSourcePanel.create({
            $,
            $$: () => [],
            t: (key, params) => translate(language, key, params),
            tr: (key, params) => translate(language, key, params),
            escapeHtml,
            iconMarkup: () => "",
            pathName,
            setText(selector, value) {
              const node = $(selector);
              if (node) node.textContent = value;
            },
            getAppState: () => state,
          });
        const snapshot = () => ({
          html: summary.innerHTML,
          text: summary.textContent,
          attributes: { ...summary.attributes },
          dataset: { ...summary.dataset },
        });
        const scenarios = {};

        folders = ["/Volumes/Weddings/2030-01-01"];
        state = {
          job: { running: false },
          sourcePreview: { mode: "folders", ready: true, folders: [...folders], total: 42 },
        };
        panel("en").updatePathSummaries();
        scenarios.englishReady = snapshot();

        folders = ["/Volumes/Weddings/May 31", "/Volumes/Weddings/June 1"];
        state = { job: { running: true, kind: "source_preview" } };
        panel("en").updatePathSummaries();
        scenarios.englishScanning = snapshot();

        folders = ["/照片/2030-01-01", "/照片/<夏日>&\\\"精选", "/照片/2030-01-02"];
        state = {
          job: { running: false },
          sourcePreview: { mode: "folders", ready: true, folders: [...folders], total: 18 },
        };
        panel("zh-CN").updatePathSummaries();
        scenarios.chineseReady = snapshot();

        folders = ["/Volumes/Weddings/Edited"];
        state = {
          job: { running: false },
          sourcePreview: { mode: "folders", ready: true, folders: ["/Volumes/Weddings/Originals"], total: 99 },
        };
        panel("en").updatePathSummaries();
        scenarios.stalePreview = snapshot();

        folders = ["/temporary/source"];
        state = {};
        const englishPanel = panel("en");
        englishPanel.updatePathSummaries();
        folders = [];
        englishPanel.updatePathSummaries();
        scenarios.empty = snapshot();

        console.log(JSON.stringify(scenarios));
        """,
    )
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return json.loads(result.stdout)


class FrontendSourcePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scenarios = render_summary_scenarios()

    def test_summary_separates_status_from_folder_names(self) -> None:
        summary = self.scenarios["englishReady"]

        self.assertIn('class="path-summary-meta"', summary["html"])
        self.assertIn('class="path-summary-folders"', summary["html"])
        self.assertIn("1 folder", summary["html"])
        self.assertIn("42 found", summary["html"])
        self.assertIn(">2030-01-01</span>", summary["html"])
        self.assertNotIn("Weddings", summary["html"])

    def test_summary_uses_locale_specific_folder_separators(self) -> None:
        english = self.scenarios["englishScanning"]
        chinese = self.scenarios["chineseReady"]

        self.assertIn("2 folders", english["html"])
        self.assertIn("Scanning", english["html"])
        self.assertIn(">, </span>", english["html"])
        self.assertNotIn("、", english["html"])
        self.assertIn("3 个目录", chinese["html"])
        self.assertIn("发现 18 张", chinese["html"])
        self.assertIn(">、</span>", chinese["html"])

    def test_summary_hint_keeps_every_full_stable_path(self) -> None:
        english = self.scenarios["englishReady"]
        chinese = self.scenarios["chineseReady"]

        english_hint = "1 folder · 42 found · /Volumes/Weddings/2030-01-01"
        chinese_hint = '3 个目录 · 发现 18 张 · /照片/2030-01-01、/照片/<夏日>&"精选、/照片/2030-01-02'
        self.assertEqual(english["attributes"]["aria-label"], english_hint)
        self.assertEqual(english["dataset"]["uiTooltip"], english_hint)
        self.assertEqual(chinese["attributes"]["aria-label"], chinese_hint)
        self.assertEqual(chinese["dataset"]["uiTooltip"], chinese_hint)
        self.assertEqual(english["attributes"]["tabindex"], "0")
        self.assertEqual(chinese["attributes"]["tabindex"], "0")
        self.assertNotIn("title", english["attributes"])
        self.assertNotIn("title", chinese["attributes"])

    def test_summary_escapes_visible_folder_names(self) -> None:
        html = self.scenarios["chineseReady"]["html"]

        self.assertIn("&lt;夏日&gt;&amp;&quot;精选", html)
        self.assertNotIn("<夏日>", html)
        self.assertEqual(html.count('class="path-summary-folder"'), 2)

    def test_summary_ignores_preview_for_different_folders(self) -> None:
        summary = self.scenarios["stalePreview"]

        self.assertIn("1 folder", summary["html"])
        self.assertIn("Edited", summary["html"])
        self.assertNotIn("99 found", summary["html"])
        self.assertNotIn("Scanning", summary["html"])

    def test_empty_summary_clears_path_hints(self) -> None:
        summary = self.scenarios["empty"]

        self.assertEqual(summary["text"], "No source selected")
        self.assertEqual(summary["html"], "")
        self.assertNotIn("aria-label", summary["attributes"])
        self.assertNotIn("data-i18n", summary["attributes"])
        self.assertNotIn("tabindex", summary["attributes"])
        self.assertNotIn("uiTooltip", summary["dataset"])
        self.assertNotIn("title", summary["attributes"])


if __name__ == "__main__":
    unittest.main()
