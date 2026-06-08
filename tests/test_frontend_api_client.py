from __future__ import annotations

import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendApiClientTests(unittest.TestCase):
    def test_api_client_wraps_json_upload_and_errors(self) -> None:
        script = textwrap.dedent(
            """
            const fs = require("fs");
            const vm = require("vm");
            const calls = [];
            function response({ ok = true, json = {}, text = "", statusText = "Bad request" } = {}) {
              return {
                ok,
                statusText,
                async json() { return json; },
                async text() { return text; },
              };
            }
            const context = {
              console,
              fetch: async (url, options = undefined) => {
                calls.push({ url, options });
                if (url === "/api/error") {
                  return response({
                    ok: false,
                    text: JSON.stringify({
                      errorCode: "NO_ACCESS",
                      error: "cannot read folder",
                      errorParams: { path: "/photos" },
                    }),
                  });
                }
                return response({ json: { ok: true, url } });
              },
            };
            context.window = context;
            context.window.CulviaI18n = {
              t(key, params = {}) {
                if (key === "common.operationFailed") return "Operation failed";
                if (key === "apiError.NO_ACCESS") return `No access: ${params.path}`;
                return key;
              },
            };
            vm.createContext(context);
            vm.runInContext(fs.readFileSync("web/api_client.js", "utf8"), context);

            (async () => {
              const api = context.window.CulviaApi;
              if (!api) throw new Error("api client was not registered");

              const getResult = await api.getJson("/api/state");
              if (!getResult.ok || getResult.url !== "/api/state") throw new Error("getJson result is wrong");
              if (calls[0].url !== "/api/state" || calls[0].options !== undefined) {
                throw new Error("getJson should call fetch without request options");
              }

              const postResult = await api.postJson("/api/filter", { minScore: 7 });
              if (!postResult.ok || calls[1].options.method !== "POST") {
                throw new Error("postJson should send a POST request");
              }
              if (calls[1].options.headers["Content-Type"] !== "application/json") {
                throw new Error("postJson should send JSON content type");
              }
              if (calls[1].options.body !== JSON.stringify({ minScore: 7 })) {
                throw new Error("postJson body is wrong");
              }

              const form = { kind: "form" };
              const uploadResult = await api.uploadForm("/api/upload", form);
              if (!uploadResult.ok || calls[2].options.method !== "POST" || calls[2].options.body !== form) {
                throw new Error("uploadForm should post the provided form body");
              }
              if (calls[2].options.headers) throw new Error("uploadForm should not force JSON headers");

              try {
                await api.getJson("/api/error");
                throw new Error("getJson should throw API failures");
              } catch (error) {
                const message = api.errorMessage(error);
                if (message !== "No access: /photos") {
                  throw new Error(`translated API error was ${message}`);
                }
              }
            })().catch((error) => {
              console.error(error);
              process.exitCode = 1;
            });
            """
        )

        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
