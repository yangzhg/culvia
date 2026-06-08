from __future__ import annotations

import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendClipboardTests(unittest.TestCase):
    def test_clipboard_module_uses_native_api_and_dom_fallback(self) -> None:
        script = textwrap.dedent(
            """
            const fs = require("fs");
            const vm = require("vm");

            (async () => {
              const context = { console };
              context.window = context;
              vm.createContext(context);
              vm.runInContext(fs.readFileSync("web/clipboard.js", "utf8"), context);

              const clipboard = context.window.CulviaClipboard;
              if (!clipboard) throw new Error("module was not registered");
              if (await clipboard.writeText("") !== false) {
                throw new Error("empty text should not be copied");
              }

              let nativeWritten = "";
              const nativeResult = await clipboard.writeText("/exports/final", {
                navigator: {
                  clipboard: {
                    async writeText(value) {
                      nativeWritten = value;
                    },
                  },
                },
              });
              if (!nativeResult || nativeWritten !== "/exports/final") {
                throw new Error("native clipboard path was not used");
              }

              let appended = null;
              let copiedCommand = "";
              let removed = false;
              let selected = false;
              const fakeDocument = {
                body: {
                  appendChild(element) {
                    appended = element;
                  },
                },
                createElement(tag) {
                  return {
                    attrs: {},
                    style: {},
                    tag,
                    setAttribute(name, value) {
                      this.attrs[name] = value;
                    },
                    select() {
                      selected = true;
                    },
                    remove() {
                      removed = true;
                    },
                  };
                },
                execCommand(command) {
                  copiedCommand = command;
                  return true;
                },
              };
              const fallbackResult = await clipboard.writeText("fallback-path", {
                document: fakeDocument,
                navigator: {},
              });
              if (!fallbackResult || copiedCommand !== "copy" || !selected || !removed) {
                throw new Error("DOM fallback did not complete");
              }
              if (!appended || appended.value !== "fallback-path" || appended.attrs.readonly !== "") {
                throw new Error("fallback textarea was not prepared");
              }

              const unavailable = await clipboard.writeText("fallback-path", {
                document: {},
                navigator: {},
              });
              if (unavailable !== false) {
                throw new Error("unavailable clipboard environment should fail softly");
              }
            })().catch((error) => {
              console.error(error);
              process.exit(1);
            });
            """
        )
        result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
