# AGENTS.md

This file applies to the entire repository. It is both the project discipline file and the handoff guide for AI-assisted development.

## Product Brief

Culvia is a local-first photo curation, scoring, review, and delivery workbench for photographers. The same Python/Starlette backend serves:

- the browser UI,
- the pip-installed Web app,
- the desktop app shell.

The current desktop shell uses Tauri, but product names, backend names, docs, and release commands should stay framework-neutral. Treat Tauri, PyInstaller, and bundled runtimes as replaceable implementation details.

## First Files To Read

When taking over a fresh clone, read these first:

1. `README.md`
2. `docs/en/developer/architecture.md`
3. `docs/en/developer/database-schema.md`
4. `docs/en/developer/desktop-build.md`
5. `docs/en/developer/release-checklist.md`
6. `Makefile`
7. `pyproject.toml`

For Chinese user-facing docs, see `README.zh-CN.md` and `docs/zh-CN/`.

## Repository Map

- `culvia/`: application logic, domain services, scoring, source scanning, runtime management, payload construction.
- `culvia_app.py`: thin Starlette composition layer, API routes, dependency wiring. Keep business logic out of this file.
- `web/`: browser UI, static JavaScript/CSS, locale files, icons, and view modules.
- `desktop/`: desktop shell and release integration.
- `bin/`: user-facing command wrappers.
- `scripts/`: development and release helper entrypoints.
- `tools/`: release, packaging, validation, and maintenance utilities.
- `tests/`: behavior, service, packaging, and contract tests.
- `docs/en/`, `docs/zh-CN/`: user and developer documentation.

## Core Architecture Rules

- Keep business logic in `culvia/`; keep `culvia_app.py` as a composition and routing layer.
- Prefer existing module boundaries over adding new framework layers.
- Use typed dataclasses or explicit payload builders for structured data.
- Keep API response construction centralized where existing payload builders already exist.
- Do not name product-level concepts after implementation technology such as Tauri, sidecar, or PyInstaller.
- If a desktop change affects the backend launch contract, keep `desktop/tauri/desktop-shell.contract.json`, `culvia.server`, `culvia.supervisor`, `culvia.runtime_manager`, and release tools in sync.

## Runtime Model

- Python owns the backend server and application logic.
- The browser, pip Web app, and desktop shell all talk to the same Starlette API.
- Desktop has two runtime modes:
  - `full`: bundled Python runtime and dependencies.
  - `lite`: app-managed or user-selected Python/virtualenv runtime.
- Runtime-generated state must live in app/runtime data locations, not in the repository.
- Do not commit caches, SQLite files, uploads, exported photos, model downloads, desktop build outputs, generated binaries, credentials, or local logs.

## Source, Scoring, And Refresh Rules

- Photo source preview is a backend job. It scans folders recursively, deduplicates canonical paths, reuses existing SQLite score rows, and creates unscored preview rows for new photos.
- Gallery thumbnails are generated on demand; the UI should not load full-resolution images for thumbnail grids.
- Scoring is a backend job. Page refresh must not be treated as task cancellation while the backend process is still alive.
- The frontend restores running task state from `/api/state` and polls while `job.running` is true.
- `job.kind` distinguishes task behavior:
  - `scoring`: can be paused and resumed.
  - `source_preview`: cannot be paused; it only reports progress/completion.
- While any backend job is running, block conflicting write operations: source changes, uploads, model selection changes, manual marks, batch curation, accepting model results, export preflight/export, LLM config writes, and destructive maintenance.
- While a backend job is running, browsing, viewing, filtering, and non-mutating inspection may remain available when practical.

## Frontend Rules

- User-facing strings belong in `web/locales/en.js` and `web/locales/zh-CN.js`.
- Keep `web/i18n_messages.js` as the locale aggregation entrypoint.
- Do not hard-code bilingual user-visible text in JavaScript modules.
- Icon-only controls need accessible labels and tooltips.
- Truncated file/path text must expose the full value through copy, `title`, or the app tooltip system.
- Keep UI state derived from backend state where possible; avoid duplicated long-lived frontend state that can drift after refresh.
- If a static asset changes and the app is served as packaged static files, update relevant cache-bust references in `web/index.html`.
- If packaged static assets change, make sure `pyproject.toml` package data still includes them.

## Backend Rules

- API route handlers should validate input, call service functions, then return payloads.
- Prefer service modules for behavior:
  - source handling: `culvia.source_requests`, `culvia.source_service`, `culvia.source_preview`, `culvia.photo_scan`
  - scoring jobs: `culvia.scoring_service`, `culvia.scoring_runner`, `culvia.job_service`
  - payloads and display rows: `culvia.payloads`, `culvia.state_payload`, `culvia.gallery_display`
  - runtime/desktop: `culvia.server`, `culvia.supervisor`, `culvia.runtime_manager`, `culvia.desktop_files`
- Keep SQLite and cache path handling explicit. Never hide API keys or credentials in SQLite, fixtures, logs, docs, or Git.
- Keep errors stable with machine-readable `errorCode` values and localized frontend messages.

## Desktop And Packaging Rules

- The desktop shell is a client of the local backend server.
- Keep desktop code framework-neutral at the product boundary.
- Build outputs should be staged under release/dist locations, not committed.
- macOS can be developed with ad-hoc or local signing; Developer ID and notarization are release concerns, not a default development blocker.
- Release command and packaging behavior should be documented in `docs/en/developer/desktop-build.md` and checked against `docs/en/developer/release-checklist.md`.

## Environment

- Use Python 3.11+.
- Use `make init` for a local development environment, or set `CULVIA_VENV` to choose the environment path.
- Do not place virtual environments inside the repository.
- If a command needs the project environment, prefer:

```bash
CULVIA_VENV=/path/to/venv make <target>
```

Useful commands:

```bash
make init
make web PORT=8501
make test
make js-check
make lint
make pre-commit
make gate
make desktop-ready
make runtime-doctor
make lite-release-plan
make windows-release-plan
make windows-lite-release-plan
make linux-release-plan
make linux-lite-release-plan
```

## Change Playbooks

For frontend UI changes:

- Update `web/` modules and locale files together.
- Run `make js-check`.
- Verify important flows in the browser when behavior or layout changes.
- Check truncation, tooltips, disabled states, keyboard behavior, and refresh behavior.

For backend/API changes:

- Keep route handlers thin.
- Add or update service-level tests.
- Add route smoke tests only when API behavior or dependency wiring changes.
- Run the relevant unit tests, then `make test`.

For source scanning, gallery, or thumbnail changes:

- Verify recursive scanning, deduplication, SQLite reuse, missing/unsupported files, refresh behavior, and thumbnail failure fallback.
- Avoid loading full-resolution images in grid contexts.

For scoring or job-control changes:

- Verify `job.kind`, pause/resume behavior, task conflict guards, `/api/state` refresh recovery, and frontend polling.
- Keep source preview and scoring semantics distinct.

For desktop/release changes:

- Keep the desktop launch contract and release tools synchronized.
- Run the relevant release-plan target before building full artifacts.
- See `docs/en/developer/release-checklist.md`.

## Testing Policy

- Prefer tests for behavior, service boundaries, API contracts, packaging contracts, and release verification tools.
- Do not add tests that only assert CSS selectors, static cache-bust strings, screenshot wrapper wiring, or historical implementation artifacts.
- For narrow changes, run the focused test first, then the appropriate broader target.
- Before committing normal code changes, run `make pre-commit`.
- Before release or packaging changes, run the relevant subset from `docs/en/developer/release-checklist.md`.

## Security And Privacy

- Never commit real API keys, tokens, user photo paths, SQLite databases, generated thumbnails, uploads, exports, model files, build artifacts, or logs.
- Keep examples generic. Do not use local personal paths in source, tests, docs, defaults, or fixtures.
- Do not print secrets in errors, logs, splash screens, UI messages, or test output.
- Secret handling should use environment variables, session config, secure storage, or documented user-provided config paths.

## Documentation Rules

- English docs are the default open-source docs.
- Chinese docs live separately under `docs/zh-CN/` and `README.zh-CN.md`.
- Do not mix full bilingual content in the same document unless the file is intentionally a short language selector.
- When behavior changes, update the matching user or developer doc instead of relying only on code comments.
