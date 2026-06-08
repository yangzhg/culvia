# Development Setup and Runbook

Simplified Chinese: [../../zh-CN/developer/getting-started.md](../../zh-CN/developer/getting-started.md)

This guide is for contributors changing Culvia code.

## Initialize

```bash
make init
```

`make init` creates or updates the development environment at `~/.venvs/culvia` by default and installs `.[desktop,release,dev]`. Override the environment path when needed:

```bash
CULVIA_VENV=$HOME/.venvs/culvia-dev make init
```

## Start the System

Use the supervisor-backed Web workspace:

```bash
make server
```

Start the direct Web server:

```bash
make web PORT=8501
make web PORT=auto WEB_ARGS=--reload
bin/culvia-web --host 127.0.0.1 --port 8501
```

On Windows:

```powershell
scripts/culvia-dev.ps1 web --host 127.0.0.1 --port 8501
bin/culvia-web.ps1 --host 127.0.0.1 --port 8501
```

For Command Prompt, use:

```bat
bin\culvia-web.cmd --host 127.0.0.1 --port 8501
```

Run the batch CLI:

```bash
make cli CLI_ARGS="--help"
```

## Developer Checks

```bash
make pre-commit-install
make pre-commit
make test
make js-check
make lint
make format
make gate
make desktop-ready
```

`make pre-commit` is the default local quality gate for Python format/lint, JS syntax, config validation, shell syntax, Makefile dry-run checks, Rust formatting, and secret scanning. Underlying commands are preserved in [Release Checklist](release-checklist.md) for reproducibility and CI.

## Desktop Development

```bash
make desktop-dev
make backend-plan
make backend-placeholder
make windows-release-plan
make linux-release-plan
```

For full desktop packaging, see [Desktop Build](desktop-build.md).

## Runtime Data

Runtime caches, SQLite files, uploads, exports, generated desktop artifacts, credentials, and local logs are not source files. Clean common generated files with:

```bash
make clean
make clean -- --apply
```
