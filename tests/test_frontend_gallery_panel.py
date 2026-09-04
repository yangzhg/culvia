from __future__ import annotations

import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendGalleryPanelTests(unittest.TestCase):
    def test_rating_tooltip_placement_stays_inside_the_viewport(self) -> None:
        script = textwrap.dedent(
            """
            const fs = require("fs");
            const vm = require("vm");
            const context = { console, window: {} };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/gallery_panel.js", "utf8"), context);

            const place = context.window.CulviaGalleryPanel.ratingTooltipPlacement;
            const firstCard = place({
              anchorRect: { top: 430, bottom: 470 },
              naturalHeight: 520,
              toolbarRect: { top: 0, bottom: 170 },
              tooltipRect: { left: -140, right: 180, width: 320, height: 520 },
              viewportHeight: 800,
              viewportWidth: 600,
            });
            if (!firstCard.below) throw new Error("first-row tooltip should use the larger lower space");
            if (firstCard.maxHeight > 302) throw new Error(`tooltip max height escaped the viewport: ${firstCard.maxHeight}`);
            if (-140 + firstCard.shiftX < 16) throw new Error("left edge was not clamped");
            if (firstCard.arrowRight <= 18 || firstCard.arrowRight >= 296) {
              throw new Error("arrow no longer points back toward the anchor");
            }

            const lastCard = place({
              anchorRect: { top: 700, bottom: 740 },
              naturalHeight: 600,
              toolbarRect: { top: 0, bottom: 150 },
              tooltipRect: { left: 500, right: 820, width: 320, height: 480 },
              viewportHeight: 800,
              viewportWidth: 600,
            });
            if (lastCard.below) throw new Error("low tooltip should open above its anchor");
            if (820 + lastCard.shiftX > 584) throw new Error("right edge was not clamped");
            if (lastCard.maxHeight > 530) throw new Error("upper tooltip overlapped the toolbar");
            """
        )

        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
