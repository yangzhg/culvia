from __future__ import annotations

import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendFilterStateTests(unittest.TestCase):
    def test_filter_preset_view_helpers(self) -> None:
        script = textwrap.dedent(
            """
            const fs = require("fs");
            const vm = require("vm");
            const context = { console };
            context.window = context;
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/filter_presets.js", "utf8"), context);

            const view = context.window.CulviaFilterPresets;
            const contextPayload = {
              options: {
                manualStatusOptions: [{ value: "pick", label: "入选" }],
                colorLabelOptions: [{ value: "green", label: "绿色" }],
                modelAgreementOptions: [{ value: "disagreement", label: "分歧" }],
                sortOptions: [{ value: "technical_overall_0_10", label: "技术质检" }],
                weightPresets: [{ value: "aesthetic", label: "审美优先" }],
              },
              manualStatusLabel(value) {
                return `状态 ${value}`;
              },
              colorLabelMeta(value) {
                return { label: `色标 ${value}` };
              },
            };

            const filters = {
              manualStatus: "pick",
              colorLabel: "green",
              modelAgreement: "disagreement",
              minScore: 7.6,
              minTechnical: 6.2,
              sortField: "technical_overall_0_10",
              limit: 120,
              weightPreset: "aesthetic",
            };
            const chips = view.activeFilterChips(filters, contextPayload);
            if (chips[0] !== "人工：入选") throw new Error("manual status chip missing option label");
            if (!chips.includes("色标：绿色")) throw new Error("color chip missing option label");
            if (!chips.includes("评审：分歧")) throw new Error("agreement chip missing option label");
            if (!chips.includes("推荐 ≥ 7.6")) throw new Error("threshold chip missing");
            if (!chips.includes("技术 ≥ 6.2")) throw new Error("technical threshold chip missing");
            if (!chips.includes("排序：技术质检")) throw new Error("sort chip missing");
            if (!chips.includes("最多 120 张")) throw new Error("limit chip missing");
            if (!chips.includes("权重：审美优先")) throw new Error("weight chip missing");
            if (view.suggestedName(filters, contextPayload) !== "人工：入选 · 色标：绿色") {
              throw new Error("suggested name should use first two chips");
            }
            if (view.summary(filters, contextPayload) !== "人工：入选 · 色标：绿色 · 评审：分歧") {
              throw new Error("summary should use first three chips");
            }
            if (view.summary({}, contextPayload) !== "默认范围") throw new Error("default summary missing");
            if (view.suggestedName({}, contextPayload) !== "全量照片") throw new Error("default name missing");
            if (view.updatedText(0) !== "本地视图") throw new Error("empty updated text missing");
            const now = Date.now();
            if (view.updatedText(now - 30 * 1000, now) !== "刚刚保存") throw new Error("recent updated text missing");
            if (view.updatedText(now - 3 * 60 * 1000, now) !== "3 分钟前") throw new Error("minute updated text missing");
            if (!view.metaText({ name: "待定", filters, updatedAt: now }, contextPayload).startsWith("人工：入选")) {
              throw new Error("meta text should include filter summary when name differs");
            }
            """
        )
        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_filter_state_storage_behaviour(self) -> None:
        script = textwrap.dedent(
            """
            const fs = require("fs");
            const vm = require("vm");
            const store = new Map();
            const localStorage = {
              getItem(key) {
                return store.has(key) ? store.get(key) : null;
              },
              setItem(key, value) {
                store.set(key, String(value));
              },
              removeItem(key) {
                store.delete(key);
              },
            };
            const context = { console, localStorage };
            context.window = context;
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/filter_state.js", "utf8"), context);

            const state = context.window.CulviaFilterState;
            if (!state.filtersAreDefault({})) throw new Error("empty filters should be default");

            state.persistFilterPayload({ manualStatus: "all" });
            if (localStorage.getItem(state.FILTER_STORAGE_KEY) !== null) {
              throw new Error("default filters should not be stored");
            }

            state.persistFilterPayload({ manualStatus: "pending", minScore: "7.5" });
            const stored = JSON.parse(localStorage.getItem(state.FILTER_STORAGE_KEY));
            if (stored.manualStatus !== "pending") throw new Error("manualStatus was not stored");
            if (stored.minScore !== 7.5) throw new Error("minScore was not normalized");

            const restored = state.savedFilterPayload();
            if (restored.manualStatus !== "pending") throw new Error("saved filters did not restore");
            if (restored.customWeights.aesthetic !== 0.6) throw new Error("custom defaults missing");

            localStorage.setItem(state.FILTER_STORAGE_KEY, "{broken json");
            if (state.savedFilterPayload() !== null) throw new Error("broken payload should return null");
            if (localStorage.getItem(state.FILTER_STORAGE_KEY) !== null) {
              throw new Error("broken payload should be removed");
            }

            let presets = state.saveFilterPreset("  待定  复核  ", { manualStatus: "pending", minScore: "6.5" });
            if (presets.length !== 1) throw new Error("preset was not saved");
            if (presets[0].name !== "待定 复核") throw new Error("preset name was not cleaned");
            if (presets[0].filters.minScore !== 6.5) throw new Error("preset filters were not normalized");

            state.persistFilterPresets([
              { id: "first", name: "淘汰视图", filters: { manualStatus: "reject" }, updatedAt: 1 },
              { id: "second", name: "待复核视图", filters: { manualStatus: "pending" }, updatedAt: 2 },
            ]);
            presets = state.savedFilterPresets();
            if (presets[0].id !== "second") throw new Error("presets should sort by recency");

            presets = state.renameFilterPreset("first", "  重命名 视图  ");
            if (presets[0].id !== "first") throw new Error("renamed preset should become most recent");
            if (presets[0].name !== "重命名 视图") throw new Error("renamed preset name was not cleaned");

            presets = state.updateFilterPreset("first", { manualStatus: "pick", minScore: "8.2" });
            if (presets[0].id !== "first") throw new Error("updated preset should become most recent");
            if (presets[0].name !== "重命名 视图") throw new Error("updating filters should keep the preset name");
            if (presets[0].filters.manualStatus !== "pick") throw new Error("updated preset manual status was not stored");
            if (presets[0].filters.minScore !== 8.2) throw new Error("updated preset filters were not normalized");

            presets = state.saveFilterPreset("待定 复核", { manualStatus: "pick" });
            if (presets.length !== 3) throw new Error("same-name preset should replace only matching names");
            if (presets[0].filters.manualStatus !== "pick") throw new Error("same-name preset was not updated");

            presets = state.deleteFilterPreset("second");
            if (presets.some((preset) => preset.id === "second")) throw new Error("preset was not deleted");
            presets = state.deleteFilterPreset("first");
            presets = state.deleteFilterPreset(presets[0].id);
            if (presets.length !== 0) throw new Error("all presets should be deleted");
            if (localStorage.getItem(state.FILTER_PRESETS_STORAGE_KEY) !== null) {
              throw new Error("empty presets should remove storage");
            }

            localStorage.setItem(state.FILTER_PRESETS_STORAGE_KEY, "{broken json");
            if (state.savedFilterPresets().length !== 0) throw new Error("broken preset payload should return empty");
            if (localStorage.getItem(state.FILTER_PRESETS_STORAGE_KEY) !== null) {
              throw new Error("broken preset payload should be removed");
            }
            """
        )
        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
