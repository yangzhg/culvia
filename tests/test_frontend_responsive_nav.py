from __future__ import annotations

import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendResponsiveNavTests(unittest.TestCase):
    def test_mobile_tools_are_modal_and_removed_from_focus_order_when_closed(self) -> None:
        script = textwrap.dedent(
            """
            const fs = require("fs");
            const vm = require("vm");
            const source = fs.readFileSync("web/app.js", "utf8");
            const start = source.indexOf("function isMobileToolsLayout()");
            const end = source.indexOf("\\nfunction applySettingsDrawerState()", start);
            if (start < 0 || end < 0) throw new Error("responsive navigation functions not found");

            class FakeClassList {
              constructor(...names) { this.names = new Set(names); }
              toggle(name, force) {
                if (force === undefined) force = !this.names.has(name);
                if (force) this.names.add(name); else this.names.delete(name);
                return force;
              }
              contains(name) { return this.names.has(name); }
            }
            class FakeElement {
              constructor(...classes) {
                this.attributes = {};
                this.classList = new FakeClassList(...classes);
                this.dataset = {};
                this.inertAncestor = false;
                this.rect = { width: 44, height: 44, right: 88, bottom: 88, left: 44, top: 44 };
              }
              setAttribute(name, value) { this.attributes[name] = String(value); }
              removeAttribute(name) { delete this.attributes[name]; }
              getAttribute(name) { return this.attributes[name] ?? null; }
              closest() { return this.inertAncestor ? {} : null; }
              getBoundingClientRect() { return this.rect; }
              focus() { focused = this; }
            }

            const shell = new FakeElement();
            const sidebar = new FakeElement();
            const sidebarToggle = new FakeElement();
            const mobileTrigger = new FakeElement();
            const desktopSettings = new FakeElement();
            const mobileSettings = new FakeElement();
            const scrim = new FakeElement("is-hidden");
            const body = new FakeElement();
            let focused = null;
            let mobile = true;
            sidebar.contains = (node) => node === desktopSettings;
            const elements = {
              ".app-shell": shell,
              "#workbenchSidebar": sidebar,
              "#sidebarToggleBtn": sidebarToggle,
              "#openMobileToolsBtn": mobileTrigger,
              "#openSettingsDrawerBtn": desktopSettings,
              "#openMobileSettingsBtn": mobileSettings,
              "#mobileSidebarScrim": scrim,
            };
            const context = {
              console,
              MOBILE_TOOLS_QUERY: "(max-width: 860px)",
              sidebarCollapsed: false,
              mobileToolsOpen: false,
              mobileToolsReturnSelector: "#openMobileToolsBtn",
              window: {
                innerHeight: 800,
                innerWidth: 600,
                matchMedia: () => ({ matches: mobile }),
                setTimeout: (callback) => callback(),
              },
              document: { body, get activeElement() { return focused; } },
              localStorage: { setItem() {} },
              t: (key) => key,
              $: (selector) => elements[selector] || null,
            };
            vm.createContext(context);
            vm.runInContext(source.slice(start, end), context);

            focused = desktopSettings;
            vm.runInContext("applySidebarMode()", context);
            if (focused !== mobileTrigger) throw new Error("focus stayed in a sidebar that became inert");

            vm.runInContext("openMobileTools()", context);
            if (!shell.classList.contains("is-mobile-tools-open")) throw new Error("mobile drawer did not open");
            if (sidebar.getAttribute("aria-hidden") !== "false" || sidebar.getAttribute("inert") !== null) {
              throw new Error("open mobile drawer should be exposed and interactive");
            }
            if (sidebar.getAttribute("role") !== "dialog" || sidebar.getAttribute("aria-modal") !== "true") {
              throw new Error("open mobile drawer should expose modal semantics");
            }
            if (mobileTrigger.getAttribute("aria-expanded") !== "true") throw new Error("trigger state is stale");
            if (scrim.classList.contains("is-hidden")) throw new Error("mobile scrim stayed hidden");
            if (focused !== sidebarToggle) throw new Error("focus did not move to the drawer close control");

            vm.runInContext("closeMobileTools()", context);
            if (sidebar.getAttribute("aria-hidden") !== "true" || sidebar.getAttribute("inert") === null) {
              throw new Error("closed mobile drawer remained in the accessibility tree");
            }
            if (!scrim.classList.contains("is-hidden")) throw new Error("mobile scrim stayed visible");
            if (focused !== mobileTrigger) throw new Error("focus did not return to the mobile trigger");

            desktopSettings.inertAncestor = true;
            focused = null;
            vm.runInContext('focusVisibleReturnTarget("#openSettingsDrawerBtn", "#openSettingsDrawerBtn")', context);
            if (focused !== mobileSettings) throw new Error("settings focus returned to the hidden desktop trigger");

            mobile = false;
            context.sidebarCollapsed = true;
            vm.runInContext("applySidebarMode()", context);
            if (!shell.classList.contains("is-focus-mode")) throw new Error("desktop focus mode was not restored");
            if (sidebar.getAttribute("inert") !== null || sidebar.getAttribute("role") !== null) {
              throw new Error("desktop sidebar kept mobile-only modal state");
            }
            """
        )

        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
