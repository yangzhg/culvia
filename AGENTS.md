# AGENTS.md

This file applies to the entire repository.

## Project Shape

Culvia is a photo curation and review application for photographers. The same Python/Starlette backend serves the browser UI, the pip-installed Web app, and the desktop app shell. The current desktop implementation uses Tauri, but product and release names should stay framework-neutral. Keep business logic in `culvia/`; keep `culvia_app.py` thin.

## Environment

- Use Python 3.11+.
- Use `make init` for a local development environment, or set `CULVIA_VENV` to choose the environment path.
- Do not commit caches, SQLite files, uploads, exported photos, model downloads, desktop build outputs, generated binaries, credentials, or local logs.

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

## Coding Rules

- Prefer existing module boundaries over adding new framework layers.
- Use typed dataclasses or explicit payload builders for structured data.
- Keep API keys out of SQLite, fixtures, logs, docs, and Git.
- Add user-facing strings to `web/locales/`; keep `web/i18n_messages.js` as the locale aggregation entrypoint and do not hard-code bilingual text in JavaScript modules.
- Use stable UI semantics: icon-only controls need tooltips or accessible labels, and truncated file/path text must expose the full value through copy or title/tooltip.
- Do not add tests that only assert CSS selectors, static cache-bust versions, screenshot wrapper wiring, or historical implementation artifacts. Prefer unit tests for behavior, service boundaries, packaging contracts, and release verification tools.

## Desktop Boundary

The current desktop shell implementation uses Tauri. Python owns the application logic and backend server. Desktop startup supports a `full` bundled runtime and a `lite` app-managed virtualenv runtime. Desktop changes should keep `desktop/tauri/desktop-shell.contract.json`, `culvia.server`, `culvia.supervisor`, `culvia.runtime_manager`, and release tools in sync. Avoid naming product-level commands, docs, or backend modules after replaceable implementation details.

## Release Hygiene

Before committing release or packaging changes, run the relevant subset from `docs/en/developer/release-checklist.md`. If a change affects packaged static assets, make sure `web/index.html` references and `pyproject.toml` package data agree.
