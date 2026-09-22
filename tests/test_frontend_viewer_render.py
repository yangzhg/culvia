from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

INSPECTOR_BOOTSTRAP = """
const fs = require("fs");
const vm = require("vm");
const context = {
  navigator: { language: "en-US" },
  localStorage: { getItem: () => "en", setItem() {} },
  document: {
    readyState: "loading", documentElement: {}, addEventListener() {},
    querySelectorAll: () => [], querySelector: () => null,
  },
  CustomEvent: function CustomEvent(name, init) { return { name, detail: init?.detail }; },
  dispatchEvent() {},
};
context.window = context;
vm.createContext(context);
[
  "web/locales/zh-CN.js", "web/locales/en.js", "web/i18n_messages.js", "web/i18n.js",
  "web/app_config.js", "web/ui_helpers.js", "web/manual_status.js", "web/viewer_inspector.js",
].forEach((file) => vm.runInContext(fs.readFileSync(file, "utf8"), context, { filename: file }));
const inspector = context.CulviaViewerInspector;
const i18n = context.CulviaI18n;
function detailRows(photo, activeTab, showMissingScoreDetails = true) {
  const { html } = inspector.scoreRowsMarkup({ path: "/photos/sample.jpg", ...photo }, { activeTab, showMissingScoreDetails });
  return [...html.matchAll(/<div class="score-row([^"]*)">([\\s\\S]*?)<\\/div>/g)].map((match) => {
    const spans = [...match[2].matchAll(/<span class="([^"]*)"[^>]*>([^<]*)<\\/span>/g)];
    const text = (className) => spans.find((span) => span[1].split(" ").includes(className))?.[2];
    return { name: text("score-name"), stars: text("score-stars"), value: text("score-num"), missing: match[1].includes("is-missing") };
  });
}
function metricRow(rows, key) {
  return rows.find((row) => row.name === i18n.t(key));
}
"""


class FrontendViewerRenderTests(unittest.TestCase):
    def assert_inspector_script_passes(self, body: str) -> None:
        script = textwrap.dedent(f"{INSPECTOR_BOOTSTRAP}\n{body}")
        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_missing_detail_scores_show_localized_status_without_empty_stars(self) -> None:
        self.assert_inspector_script_passes(
            """
            for (const language of ["en", "zh-CN"]) {
              i18n.setLanguage(language);
              for (const missing of [undefined, null, "", "暂无"]) {
                const cases = [
                  ["overview", { overallText: "7.0", scoreTexts: { quality: missing } }, "sort.quality_0_10", "score.notCalculated"],
                  ["technical", { technicalTexts: { sharpness: missing } }, "sort.sharpness_0_10", "score.notCalculated"],
                  ["llm", { llmReviewTexts: { llm_review_overall: "7.0", llm_quality: missing } }, "sort.quality_0_10", "score.notReviewed"],
                ];
                for (const [tab, photo, label, status] of cases) {
                  const row = metricRow(detailRows(photo, tab), label);
                  if (!row || row.value !== i18n.t(status) || row.stars !== undefined || !row.missing) {
                    throw new Error(`${language} ${tab}: missing score must be an explicit status without empty stars: ${JSON.stringify(row)}`);
                  }
                  if (metricRow(detailRows(photo, tab, false), label)) {
                    throw new Error("hiding missing scores must continue to omit missing rows");
                  }
                }
              }
            }
            """
        )

    def test_zero_and_mixed_detail_scores_keep_numeric_results_and_stars(self) -> None:
        self.assert_inspector_script_passes(
            """
            const cases = [
              ["overview", {
                overallText: "7.5",
                scoreTexts: { quality: 0, composition: "0.0", lighting: "7.5", color: null },
                scoreStars: { quality: "☆☆☆☆☆", composition: "☆☆☆☆☆", lighting: "★★★★☆" },
              }, ["sort.quality_0_10", "sort.composition_0_10", "sort.lighting_0_10"]],
              ["technical", {
                technicalTexts: { sharpness: 0, exposure: "0.0", contrast: "7.5", cleanliness: "暂无" },
                technicalStars: { sharpness: "☆☆☆☆☆", exposure: "☆☆☆☆☆", contrast: "★★★★☆" },
              }, ["sort.sharpness_0_10", "sort.exposure_0_10", "sort.contrast_0_10"]],
              ["llm", {
                llmReviewTexts: { llm_review_overall: "7.0", llm_quality: 0, llm_composition: "0.0", llm_lighting: "7.5", llm_color: null },
                llmReviewStars: { llm_quality: "☆☆☆☆☆", llm_composition: "☆☆☆☆☆", llm_lighting: "★★★★☆" },
              }, ["sort.quality_0_10", "sort.composition_0_10", "sort.lighting_0_10"]],
            ];
            for (const language of ["en", "zh-CN"]) {
              i18n.setLanguage(language);
              for (const [tab, photo, labels] of cases) {
                for (const showMissing of [true, false]) {
                  const rows = detailRows(photo, tab, showMissing);
                  for (const [index, value, stars] of [[0, "0", "☆☆☆☆☆"], [1, "0.0", "☆☆☆☆☆"], [2, "7.5", "★★★★☆"]]) {
                    const row = rows.find((item) => item.name === i18n.t(labels[index]) && !item.missing);
                    if (!row || row.missing || row.value !== value || row.stars !== stars) {
                      throw new Error(`${language} ${tab}: real numeric result changed: ${JSON.stringify(row)}`);
                    }
                  }
                  if (showMissing && !rows.some((row) => row.missing && row.stars === undefined)) {
                    throw new Error("mixed results must distinguish missing values from real scores");
                  }
                }
              }
            }
            """
        )

    def test_file_header_does_not_repeat_long_filename_and_keeps_full_metadata_hint(self) -> None:
        self.assert_inspector_script_passes(
            """
            const name = `session_${"0123456789".repeat(10)}.jpg`;
            for (const language of ["en", "zh-CN"]) {
              i18n.setLanguage(language);
              const { html } = inspector.scoreRowsMarkup({ path: `/photos/${name}` }, { activeTab: "file" });
              const header = html.split('<div class="file-meta-list">')[0];
              if (header.includes(name) || !header.includes(i18n.t("score.file.title")) || !header.includes(i18n.t("score.file.source"))) {
                throw new Error("file header must retain its context without duplicating the filename");
              }
              const row = html.match(/<div class="file-meta-row[^"]*" data-file-meta="name">([\\s\\S]*?)<\\/div>/)?.[1] || "";
              if (!row.includes(`>${name}</strong>`) || !row.includes(`aria-label="${name}"`) || !row.includes(`data-ui-tooltip="${name}"`)) {
                throw new Error("the metadata row must retain the complete visible filename and hint");
              }
              const scored = inspector.scoreRowsMarkup({ overallText: "7.5", scoreTexts: { quality: "7.5" } }, { activeTab: "overview" }).html;
              if (!scored.includes('<strong class="">7.5</strong>')) throw new Error("numeric score group headings must remain unchanged");
            }
            """
        )

    def test_viewer_renders_filmstrip_signals_and_score_details(self) -> None:
        state = {
            "app": {},
            "capabilities": {"revealInFileManager": True},
            "llm": {"model": "vision-model"},
            "photos": [
                {
                    "path": "/tmp/photo.jpg",
                    "preview": "/api/image?path=/tmp/photo.jpg",
                    "thumb": "/api/thumbnail?path=/tmp/photo.jpg",
                    "recommendation": 7.9,
                    "recommendationText": "7.9",
                    "recommendationStars": "★★★★☆",
                    "overallText": "7.9",
                    "level": "keep",
                    "manual": {},
                    "scoreTexts": {
                        "quality": "7.6",
                        "composition": "7.2",
                        "lighting": "7.4",
                        "color": "6.5",
                        "depth_of_field": "7.3",
                        "content": "6.6",
                    },
                    "scoreStars": {},
                    "technicalTexts": {"technical_overall": "7.1", "exposure": "7.0"},
                    "technicalStars": {},
                    "modelQualityTexts": {"clip_iqa_overall": "7.0"},
                    "modelQualityStars": {},
                    "aestheticReferenceTexts": {"clip_aesthetic": "7.5"},
                    "aestheticReferenceStars": {},
                    "llmReviewTexts": {},
                    "llmReviewStars": {},
                    "technicalTags": [],
                }
            ],
        }
        script = textwrap.dedent(
            f"""
            const fs = require("fs");
            const vm = require("vm");
            const state = {json.dumps(state)};
            state.photos.push({{
              ...state.photos[0],
              path: "/tmp/unrated.jpg",
              thumb: "/api/thumbnail?path=/tmp/unrated.jpg",
              recommendation: null,
              recommendationText: "暂无",
              overallText: "暂无",
              level: "未评分",
            }});
            class FakeClassList {{
              constructor() {{ this.values = new Set(); }}
              add(...items) {{ items.forEach((item) => this.values.add(item)); }}
              remove(...items) {{ items.forEach((item) => this.values.delete(item)); }}
              toggle(item, force) {{
                const next = force === undefined ? !this.values.has(item) : Boolean(force);
                next ? this.add(item) : this.remove(item);
                return next;
              }}
              contains(item) {{ return this.values.has(item); }}
            }}
            class FakeElement {{
              constructor(selector) {{
                this.selector = selector;
                this.dataset = {{}};
                this.classList = new FakeClassList();
                this.style = {{}};
                this.attributes = {{}};
                this.disabled = false;
                this.complete = false;
                this.naturalHeight = 1;
                this.naturalWidth = 1;
                this.clientWidth = 500;
                this.scrollWidth = 1000;
                this.offsetLeft = 0;
                this.offsetWidth = 100;
                this._html = "";
              }}
              set innerHTML(value) {{ this._html = String(value || ""); }}
              get innerHTML() {{ return this._html; }}
              set textContent(value) {{ this._text = String(value || ""); }}
              get textContent() {{ return this._text || ""; }}
              set src(value) {{ this._src = value; }}
              get src() {{ return this._src || ""; }}
              set href(value) {{ this._href = value; }}
              get href() {{ return this._href || ""; }}
              set alt(value) {{ this._alt = value; }}
              get alt() {{ return this._alt || ""; }}
              set value(value) {{ this._value = value; }}
              get value() {{ return this._value || ""; }}
              setAttribute(key, value) {{ this.attributes[key] = String(value); }}
              removeAttribute(key) {{ delete this.attributes[key]; }}
              addEventListener() {{}}
              appendChild() {{}}
              remove() {{}}
              scrollTo() {{}}
              focus() {{}}
              getBoundingClientRect() {{ return {{ left: 0, top: 0, right: 100, bottom: 30, width: 100, height: 30 }}; }}
              querySelectorAll(selector) {{
                if (selector === ".thumb" && this._html.includes('class="thumb')) return [new FakeElement(".thumb")];
                return [];
              }}
              querySelector() {{ return null; }}
            }}
            const elements = new Map();
            [
              "#emptyState", "#viewerStage", "#filmstrip", ".image-stage", "#mainImage",
              "#mainScore", "#mainStars", "#mainLevel", "#viewerCounter", "#viewerLevel",
              "#previewLink", "#revealBtn", "#prevBtn", "#nextBtn", "#manualStatusText",
              "#manualStars", "#manualColorLabels", "#manualPickBtn", "#manualHoldBtn",
              "#manualRejectBtn", "#manualSourceText", "#markAdvanceToggle", "#acceptModelBtn",
              "#acceptLlmBtn", "#signalChips", "#scoreRows",
            ].forEach((selector) => elements.set(selector, new FakeElement(selector)));
            const document = {{
              title: "",
              readyState: "complete",
              documentElement: new FakeElement("html"),
              body: new FakeElement("body"),
              createElement: (tag) => new FakeElement(tag),
              addEventListener() {{}},
              querySelector: (selector) => elements.get(selector) || null,
              querySelectorAll: () => [],
            }};
            const storage = new Map();
            const localStorage = {{
              getItem: (key) => storage.has(key) ? storage.get(key) : null,
              setItem: (key, value) => storage.set(key, String(value)),
              removeItem: (key) => storage.delete(key),
            }};
            const context = {{
              console,
              window: {{}},
              document,
              navigator: {{ language: "en-US" }},
              localStorage,
              addEventListener() {{}},
              dispatchEvent() {{}},
              setTimeout: () => 0,
              clearTimeout() {{}},
              requestAnimationFrame: (fn) => {{ fn(); return 1; }},
              cancelAnimationFrame() {{}},
              URLSearchParams,
              FormData: function FormData() {{}},
              CustomEvent: function CustomEvent(name, init) {{ return {{ name, detail: init?.detail }}; }},
            }};
            context.window = context;
            vm.createContext(context);
            [
              "web/locales/zh-CN.js", "web/locales/en.js", "web/i18n_messages.js", "web/i18n.js",
              "web/filter_state.js", "web/filter_presets.js", "web/culling_flow.js",
              "web/shortcuts.js", "web/gallery_keyboard.js", "web/viewer_keyboard.js",
              "web/manual_status.js", "web/llm_config_view.js", "web/command_view.js",
              "web/export_preflight.js", "web/export_preflight_state.js",
              "web/export_result_data.js", "web/export_result.js", "web/export_actions.js",
              "web/export_list.js", "web/batch_actions.js", "web/clipboard.js",
              "web/api_client.js", "web/update_panel.js", "web/distribution_model.js", "web/app_config.js",
              "web/icons.js", "web/ui_helpers.js", "web/gallery_view.js",
              "web/distribution_view.js", "web/distribution_panel.js", "web/export_panel.js",
              "web/llm_config_panel.js", "web/gallery_panel.js", "web/viewer_panel.js",
              "web/source_panel.js", "web/filter_panel.js", "web/viewer_inspector.js",
            ].forEach((file) => vm.runInContext(fs.readFileSync(file, "utf8"), context, {{ filename: file }}));
            let app = fs.readFileSync("web/app.js", "utf8").replace(/\\nrenderStaticIcons\\(\\);[\\s\\S]*$/, "\\n");
            app += `\\nappState = ${{JSON.stringify(state)}}; selectedIndex = 0; renderViewer();`;
            vm.runInContext(app, context, {{ filename: "web/app.js" }});
            const result = {{
              filmstrip: document.querySelector("#filmstrip").innerHTML,
              signalChips: document.querySelector("#signalChips").innerHTML,
              scoreRows: document.querySelector("#scoreRows").innerHTML,
              manualClass: document.querySelector("#manualStatusText").classList.contains("is-unreviewed"),
            }};
            if (!result.filmstrip.includes("thumb")) throw new Error("filmstrip was not rendered");
            if (result.filmstrip.includes("暂无") || !result.filmstrip.includes("None")) {{
              throw new Error("filmstrip did not localize its missing score");
            }}
            if (!result.signalChips.includes("signal-chip")) throw new Error("score signals were not rendered");
            if (!result.scoreRows.includes("score-detail-panel")) throw new Error("score details were not rendered");
            if (!result.manualClass) throw new Error("manual status class was not applied");
            """
        )

        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
