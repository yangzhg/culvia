# Culvia

Simplified Chinese: [README.zh-CN.md](README.zh-CN.md)

Culvia is a local-first photo curation, scoring, review, and delivery workbench for photographers. It helps you move from a full shoot to a smaller, more intentional set of images by combining local scoring, optional vision-model critique, manual decisions, and export tools.

It is designed for reviewing a folder of photos, finding the stronger frames, marking final decisions, and handing selected images into the next stage of editing or delivery.

> Culvia is currently an early-stage open-source project. Expect rapid changes while the workflow, desktop packaging, and model integrations mature.

## Install

```bash
pip install culvia
```

Then start the local Web app:

```bash
culvia-supervisor
```

Open the local address shown in the terminal. You can also run the direct server entrypoint:

```bash
culvia-web --host 127.0.0.1 --port 8501
```

## What You Can Do

- Import a folder of photos or temporary uploaded images.
- Scan subfolders and deduplicate repeated paths automatically.
- Generate thumbnails for fast gallery browsing without loading full-resolution files in the photo wall.
- Run local aesthetic and technical scoring models.
- Optionally run an OpenAI-compatible vision review for image critique, aesthetic/technical sub-scores, retouching advice, and shooting advice.
- Review images in a large viewer or gallery wall.
- Add manual decisions: pick, hold, reject, star rating, and color label.
- Accept model or vision-model suggestions when they are useful.
- Filter and sort by recommendation, technical quality, LLM review, manual status, color label, and other review dimensions.
- Export picked photos or CSV results for downstream editing and delivery workflows.

## Typical Workflow

1. Start Culvia and open the Web interface.
2. Choose one or more photo folders.
3. Let Culvia scan the source and build the gallery.
4. Select the scoring dimensions you want to run.
5. Start scoring and watch progress in the command panel.
6. Review photos in the viewer or gallery.
7. Mark each photo as pick, hold, or reject.
8. Use filters to narrow the final set.
9. Export selected photos or a CSV review table.

Manual decisions remain the final culling layer. Model scores are guidance for sorting, comparison, and explanation; they should not replace your own edit.

## Development Setup

### From A Source Checkout

```bash
make init
make server
```

Then open the local address shown in the terminal. By default this is usually:

```text
http://127.0.0.1:8501/
```

To start only the Web server:

```bash
make web PORT=8501
bin/culvia-web --host 127.0.0.1 --port 8501
```

### Installed Console Commands

When installed as a Python package, Culvia exposes console commands:

```bash
culvia-supervisor
culvia-web --host 127.0.0.1 --port 8501
culvia --help
```

- `culvia-supervisor`: recommended local Web entrypoint with health checks and browser opening.
- `culvia-web`: direct Web server entrypoint.
- `culvia`: command-line batch scoring entrypoint.

### Windows

From a source checkout, use the PowerShell wrappers:

```powershell
scripts/culvia-dev.ps1 init
scripts/culvia-dev.ps1 web --host 127.0.0.1 --port 8501
bin/culvia-web.ps1 --host 127.0.0.1 --port 8501
```

For Command Prompt:

```cmd
bin\culvia-web.cmd --host 127.0.0.1 --port 8501
```

## Desktop App

Culvia is built so the same backend and interface can run as a browser app or inside a desktop shell. The desktop app is intended to provide native windowing, local file access, secure credential storage, and packaged runtime options.

### Unsigned Early Desktop Builds

This note applies to users who download desktop binaries from GitHub Releases: macOS `.dmg` packages for Apple Silicon or Intel Macs, Windows portable `.zip` packages, and Linux `.tar.gz` packages. It does not apply to `pip install culvia` or source-checkout users running the local Web app.

Current desktop binaries are not Developer ID signed, notarized, or Windows code signed. macOS Gatekeeper and Windows SmartScreen may warn that the app is from an unidentified developer or block first launch.

Download desktop packages only from the project GitHub Releases page and compare the published `.sha256` file before running them. If the checksum does not match, do not run the package.

If you trust the build and hit an OS warning:

- macOS says the app is from an unidentified developer: open the app with Control-click or right-click, choose **Open**, then confirm **Open** again.
- macOS still blocks the app after extraction: open **System Settings > Privacy & Security**, find the Culvia warning, and choose **Open Anyway**.
- macOS says the app is damaged or quarantined: run `xattr -dr com.apple.quarantine /path/to/Culvia.app`, then open the app again.
- Windows SmartScreen blocks first launch: extract the portable zip, run `culvia-desktop.exe`, choose **More info**, then **Run anyway**.
- Windows marks the downloaded zip as blocked: right-click the zip or extracted `culvia-desktop.exe`, open **Properties**, check **Unblock** if it appears, then apply the change.
- Linux reports permission denied: from the extracted package directory, run `chmod +x bin/culvia bin/culvia-desktop`, then start `bin/culvia`.

These workarounds are for early public builds. A future release lane can add Developer ID signing, notarization, and Windows Authenticode signing when project certificates are configured.

Desktop packaging is still evolving. For build instructions, see [docs/en/developer/desktop-build.md](docs/en/developer/desktop-build.md).

## Privacy

Culvia is local-first:

- Local models, thumbnails, previews, SQLite data, uploads, and exports stay on your machine by default.
- Photos are sent to an external service only when you explicitly enable an OpenAI-compatible vision review.
- API keys should be entered through the app configuration flow or environment variables, not written into docs, tests, logs, SQLite plaintext fields, or Git.

LLM configuration can come from the current session, persisted non-secret settings, or environment variables. The application should never require committing credentials.

## User Documentation

- [Getting Started](docs/en/user/getting-started.md)
- [Export Workflows](docs/en/user/export-workflows.md)
- [Chinese user docs](docs/zh-CN/user/getting-started.md)

## For Developers

Developer documentation starts here:

- [Developer Getting Started](docs/en/developer/getting-started.md)
- [Architecture](docs/en/developer/architecture.md)
- [Database Schema](docs/en/developer/database-schema.md)
- [Desktop Build](docs/en/developer/desktop-build.md)
- [Release Checklist](docs/en/developer/release-checklist.md)

Common checks:

```bash
make pre-commit
make test
make js-check
make lint
```

Project rules for AI-assisted development and contributor handoff are in [AGENTS.md](AGENTS.md).

## Repository Hygiene

Do not commit model caches, thumbnail caches, upload caches, SQLite runtime databases, exported results, desktop build outputs, generated installers, API keys, or local logs.

Useful cleanup helper:

```bash
python tools/clean_runtime_artifacts.py
```
