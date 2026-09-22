from __future__ import annotations

import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

BOOTSTRAP = """
const assert = require("node:assert/strict");
const fs = require("fs");
const vm = require("vm");
const context = { navigator: { language: "en" },
  localStorage: { getItem: () => "en", setItem() {} },
  document: { readyState: "loading", documentElement: {}, addEventListener() {}, querySelectorAll: () => [], querySelector: () => null },
  CustomEvent: function(name, init) { return { name, detail: init?.detail }; },
  dispatchEvent() {},
};
context.window = context;
vm.createContext(context);
for (const name of ["locales/en", "locales/zh-CN", "i18n_messages", "i18n", "ui_helpers", "distribution_model", "distribution_view"]) {
  vm.runInContext(fs.readFileSync(`web/${name}.js`, "utf8"), context);
}
const view = context.CulviaDistributionView;
const i18n = context.CulviaI18n;
const helpers = context.CulviaUiHelpers;
const entries = [8.5, 7.5, 6.5].map((score, index) => ({ score, llm: index < 2 ? score : null }));
const allEntries = [...entries, { score: null, llm: null }];
const stats = context.CulviaDistributionModel.stats(entries.map(entry => entry.score));
function cards(html) {
  return [...html.matchAll(/<article class="decision-metric">([\\s\\S]*?)<\\/article>/g)].map(match => match[1]);
}
function assertReadable(card, tag, text) {
  const escaped = helpers.escapeHtml(text);
  assert.ok(card.includes(`<${tag}${helpers.textHintAttributes(text)}>${escaped}</${tag}>`), `missing complete ${tag} text and accessible hint: ${text}`);
}
"""


class FrontendDistributionViewTests(unittest.TestCase):
    def assert_script_passes(self, body: str) -> None:
        result = subprocess.run(
            ["node", "-e", BOOTSTRAP + textwrap.dedent(body)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_decision_metrics_keep_full_localized_labels_values_and_context(self) -> None:
        self.assert_script_passes(
            """
            for (const language of ["en", "zh-CN"]) {
              i18n.setLanguage(language);
              for (const lens of ["overview", "technical", "llm", "aesthetic", "disagreement"]) {
                const config = view.distributionLensConfig(lens);
                const rendered = cards(view.distributionDecision(lens, entries, allEntries, config, stats, 2, 1, "7.5-7.9"));
                assert.equal(rendered.length, 4);
                const labels = [i18n.t(lens === "disagreement" ? "distribution.strongDisagreement" : "distribution.priorityZone"), config.passLabel, config.summaryLabel, i18n.t("distribution.coverage")];
                const values = ["1", "2", "7.5", "3/4"];
                const contexts = ["33%", "67%", i18n.t("distribution.peak", { peak: "7.5-7.9" }), i18n.t("distribution.llmCoverage", { count: 2 })];
                rendered.forEach((card, index) => {
                  assertReadable(card, "span", labels[index]);
                  assertReadable(card, "strong", values[index]);
                  assertReadable(card, "small", contexts[index]);
                });
              }
            }
            """
        )

    def test_decision_metric_hints_escape_text_without_changing_the_value(self) -> None:
        self.assert_script_passes(
            """
            const label = 'Review "A&B" <candidates>';
            const config = { ...view.distributionLensConfig("overview"), summaryLabel: label };
            const card = cards(view.distributionDecision("overview", entries, allEntries, config, stats, 2, 1, label))[2];
            assertReadable(card, "span", label);
            assertReadable(card, "strong", "7.5");
            assertReadable(card, "small", i18n.t("distribution.peak", { peak: label }));
            assert.ok(!card.includes("<candidates>"));
            """
        )


if __name__ == "__main__":
    unittest.main()
