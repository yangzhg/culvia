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

    def test_rating_tooltip_tracks_viewport_changes_until_focus_leaves(self) -> None:
        script = textwrap.dedent(
            """
            const fs = require("fs");
            const vm = require("vm");

            const listeners = new Map();
            const listenerOptions = new Map();
            const frames = new Map();
            let nextFrameId = 1;
            let frameRequests = 0;
            let frameCancellations = 0;
            const observers = [];

            class FakeMutationObserver {
              constructor(callback) {
                this.callback = callback;
                this.disconnected = false;
                this.targets = [];
                observers.push(this);
              }
              observe(target, options) { this.targets.push({ target, options }); }
              disconnect() { this.disconnected = true; }
              notify() { this.callback(); }
            }

            const windowObject = {
              innerHeight: 800,
              innerWidth: 600,
              MutationObserver: FakeMutationObserver,
              addEventListener(type, listener, options) {
                if (!listeners.has(type)) listeners.set(type, new Set());
                listeners.get(type).add(listener);
                listenerOptions.set(type, options);
              },
              removeEventListener(type, listener, options) {
                const addedOptions = listenerOptions.get(type);
                const addedWithCapture = addedOptions === true || Boolean(addedOptions?.capture);
                const removedWithCapture = options === true || Boolean(options?.capture);
                if (addedWithCapture === removedWithCapture) listeners.get(type)?.delete(listener);
              },
              requestAnimationFrame(callback) {
                const id = nextFrameId++;
                frameRequests += 1;
                frames.set(id, callback);
                return id;
              },
              cancelAnimationFrame(id) {
                if (frames.delete(id)) frameCancellations += 1;
              },
              setTimeout,
              clearTimeout,
            };

            let anchorRect = { top: 430, bottom: 470 };
            let tooltipRect = { left: -140, right: 180, width: 320, height: 520 };
            let tooltipPresent = true;
            let tooltipRectReads = 0;
            const tooltipClasses = new Set();
            const cardClasses = new Set();
            const ratingClasses = new Set();
            const styleValues = {};
            const insideTooltip = {};
            const outside = {};
            const galleryViewRoot = {};
            const galleryGrid = {};
            let activeView = "gallery";

            const tooltip = {
              classList: {
                remove: (name) => tooltipClasses.delete(name),
                toggle(name, value) {
                  if (value) tooltipClasses.add(name);
                  else tooltipClasses.delete(name);
                },
              },
              style: {
                removeProperty: (name) => delete styleValues[name],
                setProperty: (name, value) => { styleValues[name] = value; },
                set maxHeight(value) { styleValues.maxHeight = value; },
                get maxHeight() { return styleValues.maxHeight; },
              },
              getBoundingClientRect() {
                tooltipRectReads += 1;
                return tooltipRect;
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
                add: (name) => ratingClasses.add(name),
                remove: (name) => ratingClasses.delete(name),
              },
              closest(selector) {
                if (selector === "#galleryGrid .gallery-rating") return this;
                if (selector === "#galleryGrid .photo-card" || selector === ".photo-card") return card;
                return null;
              },
              contains(node) { return node === tooltip || node === insideTooltip; },
              querySelector(selector) {
                return selector === ".rating-tooltip" && tooltipPresent ? tooltip : null;
              },
              getBoundingClientRect() { return anchorRect; },
            };
            const toolbar = {
              getBoundingClientRect: () => ({ top: 0, bottom: 170 }),
            };
            const documentObject = {
              querySelectorAll(selector) {
                return selector === ".gallery-bulk-toolbar" ? [toolbar] : [];
              },
            };

            const context = { console, document: documentObject, window: windowObject };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/gallery_panel.js", "utf8"), context);

            const panel = context.window.CulviaGalleryPanel.create({
              $: (selector) => ({ "#galleryView": galleryViewRoot, "#galleryGrid": galleryGrid })[selector] || null,
              $$: () => [],
              t: () => "",
              setText: () => {},
              escapeHtml: (value) => String(value),
              pathName: (value) => value,
              i18n: { language: () => "en" },
              galleryView: {},
              galleryKeyboard: { actions: { none: "none" } },
              cullingFlow: {},
              getAppState: () => ({ photos: [] }),
              getActiveView: () => activeView,
              getSourceMode: () => "folders",
            });

            panel.handleGalleryTooltipIntent({ target: rating, type: "focusin" });
            if (tooltipRectReads !== 1 || styleValues.maxHeight !== "302px") {
              throw new Error("initial focus did not place the tooltip");
            }
            if (listeners.get("resize")?.size !== 1 || listeners.get("scroll")?.size !== 1) {
              throw new Error("open tooltip did not start viewport tracking");
            }
            if (observers.length !== 1 || observers[0].targets.length !== 2) {
              throw new Error("open tooltip did not track view and card removal");
            }
            const scrollOptions = listenerOptions.get("scroll");
            if (!scrollOptions?.capture || !scrollOptions?.passive) {
              throw new Error("scroll tracking must be passive and observe scroll containers");
            }

            anchorRect = { top: 700, bottom: 740 };
            tooltipRect = { left: 500, right: 820, width: 320, height: 480 };
            for (const listener of listeners.get("resize")) {
              listener({ type: "resize", target: windowObject });
              listener({ type: "resize", target: windowObject });
            }
            if (frameRequests !== 1 || frames.size !== 1) {
              throw new Error("resize tracking was not limited to one animation frame");
            }
            const resizeFrame = [...frames.entries()][0];
            frames.delete(resizeFrame[0]);
            resizeFrame[1]();
            if (tooltipRectReads !== 2 || tooltipClasses.has("is-placement-below")) {
              throw new Error("resize did not recompute the open tooltip position");
            }
            if (styleValues["--rating-tooltip-shift-x"] !== "-236px") {
              throw new Error("resize kept stale horizontal placement");
            }

            for (const listener of listeners.get("scroll")) {
              listener({ type: "scroll", target: tooltip });
            }
            if (frames.size !== 0) throw new Error("scrolling tooltip content scheduled needless placement work");

            const workspace = {};
            for (const listener of listeners.get("scroll")) {
              listener({ type: "scroll", target: workspace });
              listener({ type: "scroll", target: workspace });
            }
            if (frameRequests !== 2 || frames.size !== 1) {
              throw new Error("scroll tracking was not limited to one animation frame");
            }

            panel.clearGalleryTooltipPlacement({
              target: rating,
              relatedTarget: insideTooltip,
              type: "focusout",
            });
            if (!tooltipPresent || listeners.get("resize")?.size !== 1) {
              throw new Error("focus moving inside the tooltip stopped keyboard tracking");
            }

            panel.clearGalleryTooltipPlacement({ target: rating, relatedTarget: outside, type: "focusout" });
            if (tooltipPresent || cardClasses.has("is-tooltip-open")) {
              throw new Error("tooltip stayed open after focus left");
            }
            if (listeners.get("resize")?.size || listeners.get("scroll")?.size) {
              throw new Error("tooltip viewport listeners leaked after close");
            }
            if (frames.size || frameCancellations !== 1) {
              throw new Error("pending tooltip placement frame was not cancelled");
            }
            if (!observers[0].disconnected) throw new Error("tooltip observer leaked after focus left");

            tooltipPresent = true;
            panel.handleGalleryTooltipIntent({ target: rating, type: "pointerover" });
            activeView = "viewer";
            observers[1].notify();
            if (tooltipPresent || listeners.get("resize")?.size || listeners.get("scroll")?.size) {
              throw new Error("switching away from Gallery left tooltip tracking active");
            }
            if (!observers[1].disconnected) throw new Error("view switch left the tooltip observer active");

            activeView = "gallery";
            tooltipPresent = true;
            rating.isConnected = true;
            panel.handleGalleryTooltipIntent({ target: rating, type: "focusin" });
            rating.isConnected = false;
            observers[2].notify();
            if (tooltipPresent || listeners.get("resize")?.size || listeners.get("scroll")?.size) {
              throw new Error("removing the rating left tooltip tracking active");
            }
            if (!observers[2].disconnected) throw new Error("removed rating left the tooltip observer active");
            """
        )

        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
