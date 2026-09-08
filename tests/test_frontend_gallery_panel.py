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

    def test_rating_tooltip_repositions_and_releases_tracking(self) -> None:
        script = textwrap.dedent(
            """
            const fs = require("fs");
            const vm = require("vm");

            const listeners = { resize: new Set(), scroll: new Set() };
            const frames = new Map();
            let frameRequests = 0;
            let frameCancellations = 0;
            let scrollOptions = null;

            const windowObject = {
              innerHeight: 800,
              innerWidth: 600,
              addEventListener(type, listener, options) {
                listeners[type]?.add(listener);
                if (type === "scroll") scrollOptions = options;
              },
              removeEventListener(type, listener) {
                listeners[type]?.delete(listener);
              },
              requestAnimationFrame(callback) {
                frameRequests += 1;
                frames.set(frameRequests, callback);
                return frameRequests;
              },
              cancelAnimationFrame(id) {
                if (frames.delete(id)) frameCancellations += 1;
              },
              setTimeout,
              clearTimeout,
            };

            let tooltipPresent = true;
            let tooltipRectReads = 0;
            const cardClasses = new Set();
            let state = { photos: [{}] };

            const tooltip = {
              classList: { remove() {}, toggle() {} },
              style: {
                removeProperty() {},
                setProperty() {},
                set maxHeight(_value) {},
              },
              getBoundingClientRect() {
                tooltipRectReads += 1;
                return { left: -140, right: 180, width: 320, height: 520 };
              },
              remove() { tooltipPresent = false; },
            };
            const card = {
              dataset: { index: "0" },
              classList: {
                add: (name) => cardClasses.add(name),
                remove: (name) => cardClasses.delete(name),
              },
            };
            const rating = {
              isConnected: true,
              classList: {
                add() {},
                remove() {},
              },
              closest(selector) {
                if (selector === "#galleryGrid .gallery-rating") return this;
                if (selector === "#galleryGrid .photo-card" || selector === ".photo-card") return card;
                return null;
              },
              querySelector(selector) {
                return selector === ".rating-tooltip" && tooltipPresent ? tooltip : null;
              },
              getBoundingClientRect() { return { top: 430, bottom: 470 }; },
            };
            const documentObject = { querySelectorAll: () => [] };
            const dispatch = (type, event) => listeners[type].forEach((listener) => listener(event));

            const context = { console, document: documentObject, window: windowObject };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/gallery_panel.js", "utf8"), context);

            const panel = context.window.CulviaGalleryPanel.create({
              $: () => null,
              getAppState: () => state,
              getActiveView: () => "gallery",
            });

            panel.handleGalleryTooltipIntent({ target: rating, type: "focusin" });
            if (tooltipRectReads !== 1) throw new Error("initial focus did not place the tooltip");
            if (listeners.resize.size !== 1 || listeners.scroll.size !== 1) {
              throw new Error("open tooltip did not start viewport tracking");
            }
            if (!scrollOptions?.capture || !scrollOptions?.passive) {
              throw new Error("scroll tracking must be passive and observe scroll containers");
            }

            dispatch("resize", { type: "resize", target: windowObject });
            dispatch("resize", { type: "resize", target: windowObject });
            if (frameRequests !== 1 || frames.size !== 1) {
              throw new Error("resize tracking was not limited to one animation frame");
            }
            const resizeFrame = [...frames.entries()][0];
            frames.delete(resizeFrame[0]);
            resizeFrame[1]();
            if (tooltipRectReads !== 2) throw new Error("resize did not recompute the open tooltip position");

            dispatch("scroll", { type: "scroll", target: tooltip });
            if (frames.size !== 0) throw new Error("scrolling tooltip content scheduled needless placement work");

            const workspace = {};
            dispatch("scroll", { type: "scroll", target: workspace });
            dispatch("scroll", { type: "scroll", target: workspace });
            if (frameRequests !== 2 || frames.size !== 1) {
              throw new Error("scroll tracking was not limited to one animation frame");
            }

            panel.closeRatingTooltip();
            if (tooltipPresent || cardClasses.has("is-tooltip-open")) {
              throw new Error("closing the tooltip left rendered state behind");
            }
            if (listeners.resize.size || listeners.scroll.size) {
              throw new Error("tooltip viewport listeners leaked after close");
            }
            if (frames.size || frameCancellations !== 1) {
              throw new Error("pending tooltip placement frame was not cancelled");
            }

            state = { photos: [] };
            panel.handleGalleryTooltipIntent({ target: rating, type: "focusin" });
            if (cardClasses.has("is-tooltip-open")) {
              throw new Error("failed tooltip creation left the card elevated");
            }
            if (listeners.resize.size || listeners.scroll.size) {
              throw new Error("failed tooltip creation started viewport tracking");
            }
            """
        )

        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
