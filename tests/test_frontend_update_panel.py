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
              architecture: "arm64",
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


if __name__ == "__main__":
    unittest.main()
