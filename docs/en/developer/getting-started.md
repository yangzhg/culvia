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
make lint
make test
make format
make desktop-ready
```

`make lint` and `make pre-commit` run the same checks from `.pre-commit-config.yaml`: Python format/lint, JavaScript and shell syntax, configuration validation, Rust formatting, and secret scanning. `make js-check` runs just the JavaScript syntax check. Package and runtime verification commands are in the [Release Checklist](release-checklist.md).

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
