# Desktop Shell Implementation

Simplified Chinese: [README.zh-CN.md](README.zh-CN.md)

This directory records the desktop shell contract for Culvia.

The current desktop implementation uses Tauri as a shell around the existing local Python Web app:

```text
desktop shell process
  -> starts culvia-supervisor as a backend
  -> waits for /health
  -> reads the JSON ready event from --print-json
  -> loads the reported http://127.0.0.1:<port> URL
```

## Why Local HTTP

The current frontend is intentionally same-origin:

- API requests use `/api/...`.
- Media and static files use `/api/image`, `/api/thumbnail`, and `/static/...`.
- The Python backend owns local file authorization, thumbnails, cache paths, export, curation history, and LLM review persistence.

For that reason, the first desktop shell must load the local HTTP backend. Directly embedding `web/index.html` as a static desktop asset is not a supported production mode yet, because it would break the current `/api` and `/static` assumptions unless those base URLs are abstracted and tested first.

## Contract

`desktop-shell.contract.json` is the static source of truth for the current desktop boundary:

- `frontendMode`: `local-http`
- `backendEntrypoint`: `culvia-supervisor`
- `healthPath`: `/health`
- `productionBackendArgs`: starts the supervisor with `--port auto`, `--no-open`, and `--print-json`
- `readyEvent`: the desktop shell reads a JSON line with `event`, `baseUrl`, and `healthUrl`
- `runtimeProfiles`: `full` uses the bundled backend, `lite` uses an app-managed Python virtualenv, and `auto` falls back to `lite` when no bundled backend exists

## Build Direction

Development can start by running the Python backend on `127.0.0.1:8501` and pointing the desktop `devUrl` to it.

From this directory, the development shell uses `beforeDevCommand` to run the existing Python supervisor:

```bash
cd desktop/tauri
npm install
npm run tauri:dev
```

Static desktop checks:

```bash
npm run tauri:info
npm run backend:placeholder
cargo check --manifest-path src-tauri/Cargo.toml
cargo test --manifest-path src-tauri/Cargo.toml
npm run backend:plan
```

`npm run backend:dev` calls `python3 scripts/start-dev-backend.py`, which imports `culvia.supervisor` from the repository root and starts:

```text
culvia-supervisor --host 127.0.0.1 --port 8501 --no-open --print-json
```

Activate the project's Python environment before running npm scripts so `python3` resolves to the environment that has the app dependencies installed.

`full` production packages `culvia.server:main` as a backend binary. The Rust shell resolves the bundled backend, starts it with `--port auto --no-open --print-json`, parses ready JSON from stdout, waits for `/health`, creates the main window with the returned `baseUrl`, and terminates the backend process on app exit. The full backend must not require the user to install Python separately.

`lite` mode can be selected through the persisted runtime config or `CULVIA_DESKTOP_RUNTIME_MODE=lite`. The desktop shell reads `runtime.json` from the user runtime directory, then applies environment variables only as developer overrides. It finds the configured Python or a system Python 3.11+, creates a Culvia-managed virtualenv under the user data directory, installs the configured package or the default `culvia[desktop-runtime]==<app version>` when dependencies are missing, then starts `python -m culvia.server`. For source-checkout development, use `make runtime-configure CLI_ARGS="--mode lite --python <python>"` and `make runtime-ensure CLI_ARGS="--editable-source $PWD"`.

The production backend build entry is:

```bash
python -m pip install '.[desktop]'
python3 scripts/build-backend.py --check-plan --json
python3 scripts/build-backend.py --ensure-placeholder
python3 scripts/build-backend.py --build
python ../../tools/check_desktop_release_preflight.py --json --backend-binary src-tauri/runtime/backend/aarch64-apple-darwin/culvia-server/culvia-server
python ../../tools/check_backend_smoke.py --binary src-tauri/runtime/backend/aarch64-apple-darwin/culvia-server/culvia-server --json --timeout 90
```

The build script uses PyInstaller onedir mode to create `src-tauri/runtime/backend/{target-triple}/culvia-server/` and includes `web/` as `share/culvia/web` data so the frozen runtime can serve the UI without the source tree. Run the real build and smoke test on each target OS before producing installers.

`--ensure-placeholder` creates an ignored compile-check stub for desktop cargo checks; it is not a packaging artifact. Run `python ../../tools/check_desktop_release_preflight.py --strict-signing --backend-binary <path> --json` on the macOS release machine to fail on missing `Developer ID Application` signing inputs, notarization inputs, icon configuration, or backend executability.

First-stage release packages are self-contained and do not require a system Python installation: Windows zip with a runnable `.exe`, macOS `.app` distributed by `.dmg`, and Linux `.tar.gz`. The Linux package tool expects a real Linux ELF backend built on the target platform:

```bash
npm run linux:tgz:plan -- --target x86_64-unknown-linux-gnu --desktop-binary src-tauri/target/release/culvia-desktop --backend-binary src-tauri/runtime/backend/x86_64-unknown-linux-gnu/culvia-server/culvia-server
npm run linux:tgz:build -- --target x86_64-unknown-linux-gnu --desktop-binary src-tauri/target/release/culvia-desktop --backend-binary src-tauri/runtime/backend/x86_64-unknown-linux-gnu/culvia-server/culvia-server
```

The Windows package tool expects real Windows PE executables built on the target platform:

```bash
npm run windows:zip:plan -- --target x86_64-pc-windows-msvc --desktop-binary src-tauri/target/release/culvia-desktop.exe --backend-binary src-tauri/runtime/backend/x86_64-pc-windows-msvc/culvia-server/culvia-server.exe
npm run windows:zip:build -- --target x86_64-pc-windows-msvc --desktop-binary src-tauri/target/release/culvia-desktop.exe --backend-binary src-tauri/runtime/backend/x86_64-pc-windows-msvc/culvia-server/culvia-server.exe
```

After building Windows/Linux archives, run portable package artifact preflight against the final archive, not the staging directory:

```bash
npm run windows:zip:preflight -- ../../dist/windows/culvia-0.1.0-windows-x86_64-pc-windows-msvc.zip
npm run linux:tgz:preflight -- ../../dist/linux/culvia-0.1.0-linux-x86_64-unknown-linux-gnu.tar.gz
```

The authoritative Windows/Linux runner sequence lives in `../../tools/desktop_release_contract.py`, and the manual GitHub Actions entrypoint is `../../.github/workflows/desktop-release.yml`. The workflow checker is `../../tools/check_desktop_release_workflow.py`; it keeps upload paths limited to final `.zip` / `.tar.gz` archives and rejects release bypass or secret usage in those jobs.

`src-tauri/tauri.conf.json` uses `bundle.macOS.signingIdentity = "-"` by default so local development builds get a complete ad-hoc bundle signature while keeping hardened runtime enabled. `src-tauri/entitlements.mac.plist` sets `com.apple.security.cs.disable-library-validation`; the PyInstaller backend needs it because the hardened executable loads its unpacked Python runtime at startup. Formal macOS releases must override signing with a `Developer ID Application: ...` identity or CI certificate inputs, optionally pass that identity to `scripts/build-backend.py --codesign-identity ...` or `CULVIA_MACOS_CODESIGN_IDENTITY`, and then pass notarization plus artifact and app-launch smoke preflight. The app-launch smoke expects `backendReady`, `windowCreated`, and `frontendReady`; the last event confirms the webview loaded the workbench DOM, not just that a native window exists. Smoke auto-exit starts only after `frontendReady` or `frontendReadyTimeout`.

If the environment has no stable Finder session, the default DMG AppleScript can fail with a Finder AppleEvent timeout. Use the headless script to force `CI=true` and skip Finder DMG prettifying:

```bash
npm install
npm run tauri:build:headless
```

`scripts/build-headless.py` resolves `node_modules/.bin/tauri` first and only falls back to a global `tauri` executable if the project-local CLI is unavailable. This keeps local and CI builds reproducible without requiring a global Tauri install.

From the repository root, `python tools/build_macos_app.py --clean-first --json` runs the full local macOS app/dmg sequence: scoped app artifact cleanup, app preflight, npm dependency install, backend build, headless app/dmg build, artifact preflight, app launch smoke, and final staging under `dist/macos/`. The scoped cleanup only removes desktop build outputs under `desktop/tauri/src-tauri`; repository-wide runtime cleanup remains an explicit `tools/clean_runtime_artifacts.py` action.

The desktop shell layer should own only desktop concerns: window lifecycle, native file/folder picking, system keychain integration, backend lifecycle, and app packaging. Folder picking and reveal actions currently flow through the Python backend API so the same web UI can degrade cleanly: macOS uses Finder commands, Windows uses PowerShell/Explorer, and Linux enables actions when zenity/kdialog plus xdg-open/gio are available. LLM API keys are persisted through the Python backend's keyring-backed secret store; SQLite keeps only non-secret LLM settings. Scoring, filtering, LLM review, curation, caching, exports, and UI behavior stay in the existing Python and Web layers.
