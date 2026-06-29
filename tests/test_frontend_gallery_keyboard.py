from __future__ import annotations

import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendGalleryKeyboardTests(unittest.TestCase):
    def assert_js_passes(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            const fs = require("fs");
            const vm = require("vm");
            const context = {{ console }};
            context.window = context;
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/gallery_keyboard.js", "utf8"), context);

            const keyboard = context.window.CulviaGalleryKeyboard;
            if (!keyboard) throw new Error("module was not registered");

            {body}
            """
        )
        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_actions_and_status_shortcuts_are_stable(self) -> None:
        self.assert_js_passes(
            """
            if (keyboard.actions.none !== "") throw new Error("none action should stay empty");
            if (keyboard.actions.selectVisible !== "selectVisible") throw new Error("select action is wrong");
            if (keyboard.actions.clearSelection !== "clearSelection") throw new Error("clear action is wrong");
            if (keyboard.actions.batchStatus !== "batchStatus") throw new Error("batch action is wrong");
            if (keyboard.galleryStatusShortcut("p") !== "pick") throw new Error("pick shortcut is wrong");
            if (keyboard.galleryStatusShortcut("P") !== "pick") throw new Error("pick shortcut should normalize case");
            if (keyboard.galleryStatusShortcut("u") !== "hold") throw new Error("pending shortcut is wrong");
            if (keyboard.galleryStatusShortcut("x") !== "reject") throw new Error("reject shortcut is wrong");
            if (keyboard.galleryStatusShortcut("?") !== undefined) throw new Error("unknown shortcut should be ignored");
            """
        )

    def test_gallery_shortcut_actions_respect_view_and_selection(self) -> None:
        self.assert_js_passes(
            """
            const inViewer = keyboard.shortcutActionFromEvent({ key: "a", metaKey: true }, {
              activeView: "viewer",
              selectedCount: 3,
            });
            if (inViewer.action !== keyboard.actions.none) throw new Error("viewer should not receive gallery shortcuts");

            const selectAll = keyboard.shortcutActionFromEvent({ key: "a", metaKey: true }, {
              activeView: "gallery",
              selectedCount: 0,
            });
            if (selectAll.action !== keyboard.actions.selectVisible) throw new Error("select all action is wrong");

            const ctrlSelectAll = keyboard.shortcutActionFromEvent({ key: "A", ctrlKey: true }, {
              activeView: "gallery",
              selectedCount: 0,
            });
            if (ctrlSelectAll.action !== keyboard.actions.selectVisible) throw new Error("ctrl select all action is wrong");

            const clear = keyboard.shortcutActionFromEvent({ key: "Escape" }, {
              activeView: "gallery",
              selectedCount: 2,
            });
            if (clear.action !== keyboard.actions.clearSelection) throw new Error("clear selection action is wrong");

            const emptyClear = keyboard.shortcutActionFromEvent({ key: "Escape" }, {
              activeView: "gallery",
              selectedCount: 0,
            });
            if (emptyClear.action !== keyboard.actions.none) throw new Error("empty clear should be ignored");

            const batchPick = keyboard.shortcutActionFromEvent({ key: "p" }, {
              activeView: "gallery",
              selectedCount: 2,
            });
            if (batchPick.action !== keyboard.actions.batchStatus || batchPick.status !== "pick") {
              throw new Error("batch pick action is wrong");
            }

            const batchPending = keyboard.shortcutActionFromEvent({ key: "u" }, {
              activeView: "gallery",
              selectedCount: 2,
            });
            if (batchPending.action !== keyboard.actions.batchStatus || batchPending.status !== "hold") {
              throw new Error("batch pending action is wrong");
            }

            const noSelectionPick = keyboard.shortcutActionFromEvent({ key: "p" }, {
              activeView: "gallery",
              selectedCount: 0,
            });
            if (noSelectionPick.action !== keyboard.actions.none) {
              throw new Error("empty gallery pick should be ignored");
            }

            const shiftedPick = keyboard.shortcutActionFromEvent({ key: "p", shiftKey: true }, {
              activeView: "gallery",
              selectedCount: 2,
            });
            if (shiftedPick.action !== keyboard.actions.none) {
              throw new Error("modified status shortcut should be ignored");
            }

            const repeatedPick = keyboard.shortcutActionFromEvent({ key: "p", repeat: true }, {
              activeView: "gallery",
              selectedCount: 2,
            });
            if (repeatedPick.action !== keyboard.actions.none) {
              throw new Error("repeated status shortcut should be ignored");
            }

            const repeatedClear = keyboard.shortcutActionFromEvent({ key: "Escape", repeat: true }, {
              activeView: "gallery",
              selectedCount: 2,
            });
            if (repeatedClear.action !== keyboard.actions.none) {
              throw new Error("repeated clear shortcut should be ignored");
            }

            const repeatedSelectAll = keyboard.shortcutActionFromEvent({ key: "a", metaKey: true, repeat: true }, {
              activeView: "gallery",
              selectedCount: 0,
            });
            if (repeatedSelectAll.action !== keyboard.actions.none) {
              throw new Error("repeated select all shortcut should be ignored");
            }
            """
        )


if __name__ == "__main__":
    unittest.main()
