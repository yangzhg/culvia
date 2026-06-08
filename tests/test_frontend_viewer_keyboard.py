from __future__ import annotations

import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendViewerKeyboardTests(unittest.TestCase):
    def assert_js_passes(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            const fs = require("fs");
            const vm = require("vm");
            const context = {{ console }};
            context.window = context;
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/viewer_keyboard.js", "utf8"), context);

            const keyboard = context.window.CulviaViewerKeyboard;
            if (!keyboard) throw new Error("module was not registered");

            {body}
            """
        )
        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_actions_and_shortcuts_are_stable(self) -> None:
        self.assert_js_passes(
            """
            if (keyboard.actions.none !== "") throw new Error("none action should stay empty");
            if (keyboard.actions.navigate !== "navigate") throw new Error("navigate action is wrong");
            if (keyboard.actions.rating !== "rating") throw new Error("rating action is wrong");
            if (keyboard.actions.status !== "status") throw new Error("status action is wrong");
            if (keyboard.actions.color !== "color") throw new Error("color action is wrong");
            if (keyboard.ratingShortcut("0") !== 0) throw new Error("clear rating shortcut is wrong");
            if (keyboard.ratingShortcut("5") !== 5) throw new Error("rating shortcut is wrong");
            if (keyboard.statusShortcut("P") !== "pick") throw new Error("pick shortcut should normalize case");
            if (keyboard.statusShortcut("u") !== "hold") throw new Error("hold shortcut is wrong");
            if (keyboard.statusShortcut("x") !== "reject") throw new Error("reject shortcut is wrong");
            if (keyboard.colorShortcut("g") !== "green") throw new Error("green shortcut is wrong");
            if (keyboard.colorShortcut("C") !== "") throw new Error("clear color shortcut is wrong");
            if (keyboard.colorShortcut("?") !== undefined) throw new Error("unknown color shortcut should be ignored");
            """
        )

    def test_viewer_shortcuts_respect_view_selection_repeat_and_modifiers(self) -> None:
        self.assert_js_passes(
            """
            const inGallery = keyboard.shortcutActionFromEvent({ key: "4" }, {
              activeView: "gallery",
              hasSelectedPhoto: true,
            });
            if (inGallery.action !== keyboard.actions.none) throw new Error("gallery should not receive viewer shortcuts");

            const left = keyboard.shortcutActionFromEvent({ key: "ArrowLeft", repeat: true }, {
              activeView: "viewer",
              hasSelectedPhoto: true,
            });
            if (left.action !== keyboard.actions.navigate || left.direction !== -1) {
              throw new Error("plain repeated left arrow should keep navigating");
            }

            const modifiedArrow = keyboard.shortcutActionFromEvent({ key: "ArrowRight", metaKey: true }, {
              activeView: "viewer",
              hasSelectedPhoto: true,
            });
            if (modifiedArrow.action !== keyboard.actions.none) throw new Error("modified arrow should be ignored");

            const noSelectionRating = keyboard.shortcutActionFromEvent({ key: "4" }, {
              activeView: "viewer",
              hasSelectedPhoto: false,
            });
            if (noSelectionRating.action !== keyboard.actions.none) throw new Error("rating needs selected photo");

            const rating = keyboard.shortcutActionFromEvent({ key: "4" }, {
              activeView: "viewer",
              hasSelectedPhoto: true,
            });
            if (rating.action !== keyboard.actions.rating || rating.rating !== 4) {
              throw new Error("plain rating shortcut is wrong");
            }

            const repeatedRating = keyboard.shortcutActionFromEvent({ key: "4", repeat: true }, {
              activeView: "viewer",
              hasSelectedPhoto: true,
            });
            if (repeatedRating.action !== keyboard.actions.none) throw new Error("repeated rating should be ignored");

            const modifiedStatus = keyboard.shortcutActionFromEvent({ key: "p", ctrlKey: true }, {
              activeView: "viewer",
              hasSelectedPhoto: true,
            });
            if (modifiedStatus.action !== keyboard.actions.none) throw new Error("modified status should be ignored");

            const shiftedColor = keyboard.shortcutActionFromEvent({ key: "g", shiftKey: true }, {
              activeView: "viewer",
              hasSelectedPhoto: true,
            });
            if (shiftedColor.action !== keyboard.actions.none) throw new Error("modified color should be ignored");
            """
        )


if __name__ == "__main__":
    unittest.main()
