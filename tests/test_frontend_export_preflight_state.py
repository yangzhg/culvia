from __future__ import annotations

import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendExportPreflightStateTests(unittest.TestCase):
    def test_preflight_state_helpers_cover_refresh_and_request_lifecycle(self) -> None:
        script = textwrap.dedent(
            """
            const fs = require("fs");
            const vm = require("vm");
            const context = { console };
            context.window = context;
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/export_preflight_state.js", "utf8"), context);

            const state = context.window.CulviaExportPreflightState;
            if (!state) throw new Error("module was not registered");

            if (!state.shouldRefresh({
              destination: "/out",
              activeView: "export",
              loading: false,
              storedKey: "old",
              currentKey: "new",
            })) throw new Error("changed export key should refresh");
            if (state.shouldRefresh({ destination: "", activeView: "export", loading: false, storedKey: "a", currentKey: "b" })) {
              throw new Error("empty destination should not refresh");
            }
            if (state.shouldRefresh({ destination: "/out", activeView: "viewer", loading: false, storedKey: "a", currentKey: "b" })) {
              throw new Error("inactive export view should not refresh");
            }
            if (state.shouldRefresh({ destination: "/out", activeView: "export", loading: true, storedKey: "a", currentKey: "b" })) {
              throw new Error("loading state should not refresh again");
            }

            const empty = state.emptyState();
            if (empty.preflight !== null || empty.error !== "" || empty.loading !== false || empty.key !== "") {
              throw new Error("empty state is wrong");
            }

            const begin = state.beginRequest("request-key");
            if (begin.key !== "request-key" || begin.loading !== true || begin.error !== "") {
              throw new Error("begin request state is wrong");
            }
            if (!state.isCurrent("request-key", "request-key") || state.isCurrent("request-key", "other")) {
              throw new Error("current request check is wrong");
            }

            const payload = { ready: 2, destinationWritable: true };
            const success = state.successState(payload);
            if (success.preflight !== payload || success.error !== "") throw new Error("success state is wrong");

            const failure = state.failureState("");
            if (failure.preflight !== null || failure.error !== "导出预检不可用") {
              throw new Error("failure fallback is wrong");
            }
            if (state.finishRequest().loading !== false) throw new Error("finish request should clear loading");

            if (!state.exportBlocked({ loading: true })) throw new Error("loading should block export");
            if (!state.exportBlocked({ error: "bad" })) throw new Error("error should block export");
            if (!state.exportBlocked({ preflight: { destinationWritable: false } })) {
              throw new Error("unwritable destination should block export");
            }
            if (state.exportBlocked({ preflight: { destinationWritable: true } })) {
              throw new Error("ready destination should not block export");
            }
            """
        )
        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
