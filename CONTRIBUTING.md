# Contributing To Culvia

Thanks for helping improve Culvia. The project is early-stage, so the most useful contributions are focused workflow reports, small fixes, tests around behavior, and documentation that makes the app easier to try.

## Before You Start

Read these files first:

1. `README.md`
2. `docs/en/developer/architecture.md`
3. `docs/en/developer/database-schema.md`
4. `docs/en/developer/desktop-build.md`
5. `docs/en/developer/release-checklist.md`
6. `AGENTS.md`

## Useful Contribution Areas

- Photographer workflow feedback from real culling sessions.
- Install, launch, and release packaging fixes.
- Local source scanning, thumbnail, curation, scoring, export, and refresh behavior.
- Frontend accessibility, keyboard behavior, disabled states, truncation, and i18n coverage.
- Tests for service behavior, API contracts, packaging contracts, and release verification tools.
- Documentation that helps new users try the app safely.

## Development Setup

```bash
make init
make server
```

Then open the local address printed by the server.

For a focused Web server:

```bash
make web PORT=8501
```

## Checks

For normal changes, run:

```bash
make pre-commit
```

Useful focused checks:

```bash
make test
make js-check
make lint
make desktop-ready
```

For release or packaging changes, follow `docs/en/developer/release-checklist.md`.

## Pull Request Expectations

- Keep route handlers thin and put business behavior in `culvia/` service modules.
- Keep user-facing strings in `web/locales/en.js` and `web/locales/zh-CN.js`.
- Keep local paths stable for display; do not use `Path.resolve()` as user-facing normalization.
- Add or update tests when behavior, API contracts, persistence, packaging, or release tooling changes.
- Update matching user or developer docs when behavior changes.
- Do not include local photo paths, raw shoots, generated thumbnails, uploads, exports, SQLite databases, model caches, logs, credentials, or API keys.

## Reporting Issues

Use the GitHub issue templates. Include enough detail to reproduce the problem, but remove private paths, API keys, and personal image metadata from logs or screenshots.
