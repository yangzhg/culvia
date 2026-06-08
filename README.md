# Culvia

Simplified Chinese: [README.zh-CN.md](README.zh-CN.md)

Culvia is a photo curation and review application for photographers. It helps turn a shoot into a considered selection with local aesthetic and technical scoring, optional OpenAI-compatible vision review, manual culling decisions, SQLite persistence, and export tools in one Web/Desktop codebase.

## Features

- Local scoring: aesthetic reference, technical QC, composition/light/color dimensions, persisted to SQLite.
- Curation flow: large-image review, gallery grid, multi-select, drag selection, star ratings, color labels, pick/review/reject decisions, and batch acceptance.
- LLM review: OpenAI-compatible vision review with art profile, technical QC, detailed sub-scores, image critique, retouching advice, and shooting advice.
- Local media handling: thumbnails, previews, upload cache, and exports stay on the machine by default.
- Internationalization: Simplified Chinese and English live under `web/locales/`; `web/i18n_messages.js` only aggregates locale files for the runtime. UI modules must not hard-code bilingual user-facing copy.
- Distribution: pip-installed Web app plus desktop app. The desktop shell currently uses Tauri; Electron is not the default desktop route. Desktop startup supports a self-contained `full` runtime and a `lite` app-managed virtualenv runtime.

## Install

Initialize the development environment:

```bash
make init
```

`make init` creates or updates the environment at `~/.venvs/culvia` and installs the development extras. Override the location when needed:

```bash
CULVIA_VENV=$HOME/.venvs/culvia-dev make init
```

## Run

Use the project command runner while working from a source checkout:

```bash
make server
make web PORT=8501
make web PORT=auto WEB_ARGS=--reload
bin/culvia-web --host 127.0.0.1 --port 8501
```

On Windows, use the PowerShell wrapper:

```powershell
scripts/culvia-dev.ps1 init
scripts/culvia-dev.ps1 web --host 127.0.0.1 --port 8501
bin/culvia-web.ps1 --host 127.0.0.1 --port 8501
```

For Command Prompt, use `bin\culvia-web.cmd --host 127.0.0.1 --port 8501`.

After pip installation, the package also exposes normal console commands:

```bash
culvia-supervisor
culvia-web --host 127.0.0.1 --port 8501
culvia --help
```

- `make server` / `culvia-supervisor`: recommended local Web entrypoint with supervisor, port selection, health checks, and browser opening.
- `make web` / `culvia-web`: direct Starlette/Uvicorn server for development and deployment.
- `make cli` / `culvia`: command-line batch scoring entrypoint.

## LLM Review and Privacy

LLM configuration can come from environment variables, the current session, or persisted non-secret SQLite settings. Precedence is: current session > SQLite > environment variables. API keys must not be written to README files, tests, logs, SQLite plaintext fields, or Git. Desktop secure storage is verified by `tools/check_secret_store_keychain_smoke.py`.

Vision review is opt-in. Local models do not upload photos; an OpenAI-compatible vision provider is contacted only when the user enables LLM review, and images are converted to the input format required by that provider.

## Desktop and Packaging

The desktop app reuses the same Starlette API and static frontend. The desktop shell currently uses Tauri and owns the window, backend lifecycle, native file capabilities, system credential integration, and packaging. Python owns scoring, filtering, LLM review, curation, caching, exports, and persistence.

Common desktop and release checks:

```bash
make desktop-ready
make app-icons
make runtime-doctor
make runtime-configure
make gate
make release-status
make python-release-plan
make macos-release-plan
make windows-release-plan
make linux-release-plan
```

macOS app and artifact tools:

- `tools/check_macos_app_preflight.py`
- `tools/clean_macos_app_artifacts.py`
- `tools/build_macos_app.py`
- `tools/check_macos_artifact_preflight.py`
- `tools/check_macos_app_launch_smoke.py`

Windows/Linux portable package and release evidence tools:

- `tools/build_windows_zip.py`
- `tools/build_linux_tgz.py`
- `tools/check_portable_package_preflight.py`
- `tools/check_portable_package_runtime.py`
- `tools/write_release_checksum.py`
- `tools/write_release_evidence_manifest.py`
- `tools/desktop_release_contract.py`
- `.github/workflows/desktop-release.yml`
- `tools/check_desktop_release_workflow.py`

Backend verification tools:

- `tools/check_backend_smoke.py`
- `tools/check_backend_workflow_smoke.py`

Native desktop release wrappers:

- web favicon and desktop app icons: `make app-icons`
- pip wheel/sdist: `make python-release-plan`, then `make python-release`
- macOS local app/dmg: `make macos-release-plan`, then `make macos-release`
- Lite desktop package for the current OS: `make lite-release-plan`, then `make lite-release`
- macOS strict notarized release: `make macos-notarized-release-plan`, then `make macos-notarized-release`
- Windows: `scripts/culvia-dev.ps1 windows-release-plan`, then `scripts/culvia-dev.ps1 windows-release` on a Windows runner
- Windows Lite: `scripts/culvia-dev.ps1 windows-lite-release-plan`, then `scripts/culvia-dev.ps1 windows-lite-release`
- Linux: `scripts/culvia-dev linux-release-plan`, then `scripts/culvia-dev linux-release` on a Linux runner
- Linux Lite: `scripts/culvia-dev linux-lite-release-plan`, then `scripts/culvia-dev linux-lite-release`

Final release artifacts are staged under the repository root:

```text
dist/python/    pip wheel and source distribution
dist/macos/     macOS .app, .dmg, checksum, and evidence manifest
dist/macos-lite/ macOS Lite .app, .dmg, checksum, and evidence manifest
dist/windows/   Windows portable zip, checksum, and evidence manifest
dist/windows-lite/ Windows Lite portable zip, checksum, and evidence manifest
dist/linux/     Linux portable tar.gz, checksum, and evidence manifest
dist/linux-lite/ Linux Lite portable tar.gz, checksum, and evidence manifest
```

Desktop Lite runtime helpers are available through `culvia runtime ...` or the make targets `runtime-config`, `runtime-configure`, `runtime-reset-config`, `runtime-doctor`, `runtime-create`, `runtime-install`, and `runtime-ensure`. Lite mode creates a Culvia-managed virtualenv and never installs dependencies into global Python.

## Development Checks

```bash
make pre-commit-install
make pre-commit
make test
make js-check
make lint
make format
make gate
```

`make pre-commit` runs Python formatting/lint checks, JS syntax checks, config-file validation, shell syntax, Makefile dry-run checks, Rust formatting, and secret scanning. The release checklist keeps the underlying Python commands for reproducible CI and packaging runs.

User documentation starts at [docs/en/user/getting-started.md](docs/en/user/getting-started.md). Developer documentation starts at [docs/en/developer/getting-started.md](docs/en/developer/getting-started.md). Release and packaging checks live in [docs/en/developer/release-checklist.md](docs/en/developer/release-checklist.md).

## Repository Hygiene

Do not commit model caches, thumbnail caches, upload caches, SQLite runtime databases, exported results, desktop shell target/gen/runtime outputs, generated installers, API keys, or local logs.

Cleanup helper and common forbidden runtime boundaries:

```text
tools/clean_runtime_artifacts.py
model_cache/
analysis_cache/
thumbnail_cache/
upload_cache/
*.sqlite
*.sqlite-*
*.db
```

`bin/culvia-web` is the tracked source-checkout Web launcher. `tools/clean_runtime_artifacts.py` removes common local runtime artifacts such as caches, build outputs, generated desktop files, SQLite files, and export CSV files.

## Project Layout

```text
culvia/                  Core services, scoring orchestration, curation, export, desktop helpers
culvia_app.py            Starlette app factory, API handlers, static web mounting
culvia/scoring.py        Local scoring and model integration layer
bin/                        Source-checkout Web launcher
web/                        Browser UI and i18n messages
desktop/tauri/              Desktop shell and backend build scripts
tools/                      Release, packaging, backend, and maintenance tools
scripts/                    Source-checkout command runners for macOS/Linux and Windows
tests/                      Unit, service, packaging, i18n, and release verification tests
docs/en/user/               English user documentation
docs/en/developer/          English developer documentation
docs/zh-CN/user/            Simplified Chinese user documentation
docs/zh-CN/developer/       Simplified Chinese developer documentation
```
