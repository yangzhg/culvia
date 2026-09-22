from __future__ import annotations

import json
import subprocess
import textwrap
import unittest


class FrontendUpdatePanelTests(unittest.TestCase):
    def test_version_runtime_status_and_release_url_views(self) -> None:
        script = textwrap.dedent(
            """
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {}, URL };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/update_panel.js", "utf8"), context);
            const api = context.window.CulviaUpdatePanel;
            const t = (key, params = {}) => `${key}:${Object.values(params).join("|")}`;
            const web = api.viewState({
              version: "0.1.0",
              serviceVersion: "0.1.0",
              distribution: "python",
              runtimeProfile: "web",
              platform: "linux",
              architecture: "x86_64",
            }, {}, t);
            const desktop = api.viewState({
              version: "0.2.0",
              shellVersion: "0.2.0",
              serviceVersion: "0.1.0",
              distribution: "desktop",
              runtimeProfile: "lite",
              platform: "darwin",
              architecture: "x86_64",
              desktopTarget: "aarch64-apple-darwin",
              desktopPlatform: "darwin",
              desktopArchitecture: "arm64",
              versionMismatch: true,
            }, {
              result: {
                status: "updateAvailable",
                latestVersion: "0.3.0",
                releaseUrl: "https://github.com/yangzhg/culvia/releases/tag/v0.3.0",
              },
            }, t);
            console.log(JSON.stringify({
              web,
              desktop,
              trusted: api.trustedReleaseUrl("https://github.com/yangzhg/culvia/releases/tag/v0.3.0"),
              untrusted: api.trustedReleaseUrl("https://example.com/yangzhg/culvia/releases/tag/v0.3.0"),
              credentialed: api.trustedReleaseUrl("https://secret@github.com/yangzhg/culvia/releases/tag/v0.3.0"),
            }));
            """
        )

        result = subprocess.run(["node", "-e", script], text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        output = json.loads(result.stdout)
        self.assertEqual(output["web"]["currentVersion"], "v0.1.0")
        self.assertTrue(output["web"]["runtime"].startswith("about.runtime.web"))
        self.assertFalse(output["web"]["serviceVersionVisible"])
        self.assertTrue(output["desktop"]["runtime"].startswith("about.runtime.desktopLite"))
        self.assertTrue(output["desktop"]["serviceVersionVisible"])
        self.assertIn("0.2.0|0.1.0", output["desktop"]["mismatchText"])
        self.assertTrue(output["desktop"]["statusText"].startswith("update.available"))
        self.assertEqual(output["desktop"]["releaseUrl"], output["trusted"])
        self.assertEqual(output["untrusted"], "")
        self.assertEqual(output["credentialed"], "")

    def test_desktop_platform_uses_shell_identity_and_keeps_unknown_identity_explicit(self) -> None:
        script = textwrap.dedent(
            """
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {}, URL };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/update_panel.js", "utf8"), context);
            const view = context.window.CulviaUpdatePanel.viewState;
            const t = (key, params = {}) => `${key}:${Object.values(params).join("|")}`;
            const backend = { distribution: "desktop", platform: "darwin", architecture: "x86_64" };
            console.log(JSON.stringify({
              native: view({ ...backend, desktopPlatform: "darwin", desktopArchitecture: "arm64" }, {}, t),
              unknown: view({ ...backend, desktopPlatform: "", desktopArchitecture: "" }, {}, t),
              missing: view(backend, {}, t),
              web: view({ ...backend, distribution: "python" }, {}, t),
            }));
            """
        )

        result = subprocess.run(["node", "-e", script], text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        output = json.loads(result.stdout)
        self.assertIn("arm64", output["native"]["platform"])
        self.assertNotIn("x86_64", output["native"]["platform"])
        self.assertEqual(output["unknown"]["platform"], output["missing"]["platform"])
        self.assertNotIn("darwin", output["unknown"]["platform"])
        self.assertNotIn("x86_64", output["unknown"]["platform"])
        self.assertIn("about.versionUnknown", output["unknown"]["platform"])
        self.assertIn("x86_64", output["web"]["platform"])

    def test_package_match_controls_guidance_and_release_action(self) -> None:
        script = textwrap.dedent(
            """
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {}, URL };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/update_panel.js", "utf8"), context);
            const api = context.window.CulviaUpdatePanel;
            const t = (key) => key;
            const release = {
              status: "updateAvailable", latestVersion: "0.3.0",
              releaseUrl: "https://github.com/yangzhg/culvia/releases/tag/v0.3.0",
            };
            const view = (packageInfo, state = {}, result = {}) => api.viewState({}, {
              result: { ...release, package: packageInfo, ...result }, ...state,
            }, t);
            const desktopName = "culvia-0.3.0-linux-lite-x86_64-unknown-linux-gnu.tar.gz";
            const available = { status: "available", reason: "", name: desktopName };
            const reasons = ["packageMissing", "runtimeWheelMissing", "targetUnknown", "profileUnknown",
              "releaseAssetsUnknown", "distributionUnknown"];
            console.log(JSON.stringify({
              available: view(available),
              python: view({ ...available, name: "culvia-0.3.0-py3-none-any.whl" }),
              missingName: view({ ...available, name: "" }),
              reasons: Object.fromEntries(reasons.map((reason) => [reason, view({
                status: reason.endsWith("Missing") ? "unavailable" : "unknown", reason,
                name: reason.endsWith("Missing") ? desktopName : "",
              })])),
              missingMetadata: view(undefined),
              malformedMetadata: view({ status: "unexpected", name: desktopName }),
              checking: view(available, { checking: true }),
              error: view(available, { error: "offline" }),
              current: view(available, {}, { status: "current", currentVersion: "0.3.0" }),
              ahead: view(available, {}, { status: "ahead" }),
              unsafe: view(available, {}, { releaseUrl: "https://example.com/download" }),
            }));
            """
        )

        result = subprocess.run(["node", "-e", script], text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        output = json.loads(result.stdout)
        for key in ("available", "python"):
            self.assertEqual(output[key]["packageText"], "update.package.available")
            self.assertTrue(output[key]["packageName"])
            self.assertEqual(output[key]["releaseLabelKey"], "update.openRelease")
        for reason, view in output["reasons"].items():
            with self.subTest(reason=reason):
                self.assertEqual(view["packageText"], f"update.package.{reason}")
                self.assertEqual(view["releaseLabelKey"], "update.openReleaseNotes")
                self.assertTrue(view["releaseUrl"])
        self.assertEqual(output["missingMetadata"]["packageText"], "update.package.releaseAssetsUnknown")
        for key in ("missingMetadata", "malformedMetadata", "missingName"):
            self.assertEqual(output[key]["releaseLabelKey"], "update.openReleaseNotes")
        for key in ("checking", "error", "current", "ahead"):
            self.assertEqual(output[key]["packageText"], "")
            self.assertEqual(output[key]["packageName"], "")
            self.assertEqual(output[key]["releaseUrl"], "")
        self.assertEqual(output["unsafe"]["releaseUrl"], "")

    def test_package_result_retries_and_language_changes_update_rendered_guidance(self) -> None:
        script = textwrap.dedent(
            """
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {}, URL };
            vm.createContext(context);
            for (const path of ["web/locales/en.js", "web/locales/zh-CN.js", "web/update_panel.js"]) {
              vm.runInContext(fs.readFileSync(path, "utf8"), context);
            }
            let language = "en";
            const t = (key, params = {}) => {
              const template = context.window.CulviaLocaleMessages[language][key];
              if (!template) throw new Error(`Missing ${language} message: ${key}`);
              return template.replace(/\\{(\\w+)\\}/g, (_, name) => params[name] ?? "");
            };
            const node = () => {
              const value = { textContent: "", dataset: {}, title: "", href: "", hidden: false,
                disabled: false, attributes: {}, querySelector: () => null, addEventListener: () => {},
                setAttribute(name, text) { this.attributes[name] = text; },
                removeAttribute(name) { delete this.attributes[name]; if (name === "href") this.href = ""; },
              };
              value.classList = { toggle(name, enabled) { if (name === "is-hidden") value.hidden = enabled; } };
              Object.defineProperty(value, "innerHTML", { set() { throw new Error("Expected text rendering"); } });
              return value;
            };
            const nodes = Object.fromEntries(["#checkUpdateBtn", "#checkUpdateLabel", "#openReleaseLink",
              "#openReleaseLabel", "#updateCheckStatus", "#updatePackageInfo", "#updatePackageText",
              "#updatePackageName", "#updatePackageNameFact", "#updatePackageNameLabel"].map((key) => [key, node()]));
            const packageName = "culvia-0.3.0-windows-lite-x86_64-pc-windows-msvc.zip";
            const release = { status: "updateAvailable", latestVersion: "0.3.0",
              releaseUrl: "https://github.com/yangzhg/culvia/releases/tag/v0.3.0" };
            const responses = [
              { ...release, package: { status: "available", reason: "", name: packageName } },
              new Error("offline"),
              { ...release, package: { status: "unavailable", reason: "runtimeWheelMissing", name: packageName } },
              release,
              { ...release, status: "current", currentVersion: "0.3.0" },
            ];
            let requestCount = 0;
            const panel = context.window.CulviaUpdatePanel.create({
              $: (selector) => nodes[selector] || null, t,
              postJson: async () => {
                requestCount += 1;
                const response = responses.shift();
                if (response instanceof Error) throw response;
                return response;
              },
              errorMessage: () => t("apiError.updateCheckRequestFailed"),
              getAppState: () => ({ app: { version: "0.2.0", distribution: "desktop" } }),
            });
            const snapshot = () => ({
              text: nodes["#updatePackageText"].textContent,
              name: nodes["#updatePackageName"].textContent,
              title: nodes["#updatePackageName"].title,
              packageHidden: nodes["#updatePackageInfo"].hidden,
              nameHidden: nodes["#updatePackageNameFact"].hidden,
              link: nodes["#openReleaseLink"].href,
              linkHidden: nodes["#openReleaseLink"].hidden,
              label: nodes["#openReleaseLabel"].textContent,
              labelKey: nodes["#openReleaseLabel"].dataset.i18n,
              disabled: nodes["#checkUpdateBtn"].disabled,
            });
            (async () => {
              panel.render();
              panel.bindEvents();
              if (requestCount !== 0) throw new Error("Unexpected automatic update check");
              await panel.checkForUpdates();
              const available = snapshot();
              language = "zh-CN";
              panel.render();
              const translated = snapshot();
              const retry = panel.checkForUpdates();
              const checking = snapshot();
              await retry;
              const failed = snapshot();
              await panel.checkForUpdates();
              const missingWheel = snapshot();
              language = "en";
              panel.render();
              const missingWheelEn = snapshot();
              await panel.checkForUpdates();
              const unknown = snapshot();
              await panel.checkForUpdates();
              console.log(JSON.stringify({ packageName, available, translated, checking, failed,
                missingWheel, missingWheelEn, unknown, current: snapshot(), requestCount }));
            })();
            """
        )

        result = subprocess.run(["node", "-e", script], text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        output = json.loads(result.stdout)
        available = output["available"]
        self.assertFalse(available["packageHidden"])
        self.assertFalse(available["linkHidden"])
        self.assertEqual(available["name"], output["packageName"])
        self.assertEqual(available["title"], output["packageName"])
        self.assertEqual(available["labelKey"], "update.openRelease")
        self.assertEqual(available["label"], "View release & download")
        self.assertEqual(output["translated"]["label"], "查看发布与下载")
        self.assertRegex(output["translated"]["text"], r"[\u4e00-\u9fff]")
        for key in ("checking", "failed", "current"):
            self.assertTrue(output[key]["linkHidden"])
            self.assertTrue(output[key]["packageHidden"])
            self.assertEqual(output[key]["link"], "")
        self.assertTrue(output["checking"]["disabled"])
        self.assertFalse(output["failed"]["disabled"])
        self.assertEqual(output["missingWheel"]["label"], "查看发布说明")
        self.assertIn("同版本", output["missingWheel"]["text"])
        self.assertEqual(output["missingWheelEn"]["label"], "View release notes")
        self.assertNotRegex(output["missingWheelEn"]["text"], r"[\u4e00-\u9fff]")
        self.assertTrue(output["unknown"]["nameHidden"])
        self.assertEqual(output["unknown"]["name"], "")
        self.assertEqual(output["unknown"]["title"], "")
        self.assertEqual(output["unknown"]["labelKey"], "update.openReleaseNotes")
        self.assertEqual(output["requestCount"], 5)

    def test_update_request_only_runs_after_an_explicit_call_and_deduplicates_clicks(self) -> None:
        script = textwrap.dedent(
            """
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {}, URL };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/update_panel.js", "utf8"), context);
            let requestCount = 0;
            let resolveRequest;
            const request = new Promise((resolve) => { resolveRequest = resolve; });
            const panel = context.window.CulviaUpdatePanel.create({
              $: () => null,
              t: (key) => key,
              postJson: async (url, payload) => {
                requestCount += 1;
                if (url !== "/api/update/check") throw new Error("wrong url");
                if (JSON.stringify(payload) !== "{}") throw new Error("wrong payload");
                return request;
              },
              errorMessage: (error) => error.message,
              getAppState: () => ({ app: { version: "0.1.0", serviceVersion: "0.1.0" } }),
            });
            if (requestCount !== 0) throw new Error("update check ran automatically");
            const first = panel.checkForUpdates();
            const second = panel.checkForUpdates();
            resolveRequest({ status: "current", currentVersion: "0.1.0", latestVersion: "0.1.0" });
            Promise.all([first, second]).then(() => {
              console.log(JSON.stringify({ requestCount }));
            });
            """
        )

        result = subprocess.run(["node", "-e", script], text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(json.loads(result.stdout), {"requestCount": 1})

    def test_update_error_is_relocalized_when_the_interface_language_changes(self) -> None:
        script = textwrap.dedent(
            """
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {}, URL };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/update_panel.js", "utf8"), context);
            let language = "zh-CN";
            const status = { className: "", textContent: "" };
            const panel = context.window.CulviaUpdatePanel.create({
              $: (selector) => selector === "#updateCheckStatus" ? status : null,
              t: (key, params = {}) => {
                if (key === "update.failed") {
                  return language === "en"
                    ? `Updates could not be checked: ${params.reason}`
                    : `暂时无法检查更新：${params.reason}`;
                }
                return key;
              },
              postJson: async () => {
                throw new Error(JSON.stringify({
                  errorCode: "updateCheckRateLimited",
                  error: "GitHub 暂时限制了检查频率",
                }));
              },
              errorMessage: () => language === "en"
                ? "GitHub temporarily limited update checks"
                : "GitHub 暂时限制了检查频率",
              getAppState: () => ({ app: { version: "0.1.1", serviceVersion: "0.1.1" } }),
            });
            panel.checkForUpdates().then(() => {
              const zh = status.textContent;
              language = "en";
              panel.render();
              console.log(JSON.stringify({ zh, en: status.textContent }));
            });
            """
        )

        result = subprocess.run(["node", "-e", script], text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        output = json.loads(result.stdout)
        self.assertIn("GitHub 暂时限制", output["zh"])
        self.assertEqual(
            output["en"],
            "Updates could not be checked: GitHub temporarily limited update checks",
        )
        self.assertNotRegex(output["en"], r"[\u4e00-\u9fff]")


if __name__ == "__main__":
    unittest.main()
