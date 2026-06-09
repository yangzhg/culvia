from __future__ import annotations

import json
import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendViewerRenderTests(unittest.TestCase):
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
              navigator: {{ language: "zh-CN" }},
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
              "web/api_client.js", "web/distribution_model.js", "web/app_config.js",
              "web/icons.js", "web/ui_helpers.js", "web/gallery_view.js",
              "web/distribution_view.js", "web/viewer_inspector.js",
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
            if (!result.signalChips.includes("signal-chip")) throw new Error("score signals were not rendered");
            if (!result.scoreRows.includes("score-detail-panel")) throw new Error("score details were not rendered");
            if (!result.manualClass) throw new Error("manual status class was not applied");
            """
        )

        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
