# Getting Started

Simplified Chinese: [../../zh-CN/user/getting-started.md](../../zh-CN/user/getting-started.md)

This guide is for photographers using Culvia, not for contributors changing the code.

## Start the App

From a source checkout:

```bash
make init
make server
```

To start only the Web server:

```bash
make web PORT=8501
bin/culvia-web --host 127.0.0.1 --port 8501
```

After pip installation, use the installed console commands:

```bash
culvia-supervisor
culvia-web --host 127.0.0.1 --port 8501
```

## Basic Workflow

1. Choose a folder or upload temporary photos.
2. Select the local models or optional LLM review you want to run.
3. Start scoring and watch the current photo/progress state.
4. Review photos in the viewer or gallery.
5. Apply manual decisions: pick, hold, reject, star rating, and color label.
6. Export selected photos or CSV results.

## Photo Sources

In folder mode, the source editor is a list of folder rows. You can add paths one at a time, paste multiple paths into the add field, edit an existing row, copy a full path, or remove a row without rewriting the whole source list. Culvia expands `~`, normalizes folder paths, removes duplicate child folders when a parent folder is already present, then scans subfolders and deduplicates photos by canonical path.

In drop mode, dropping a folder recursively imports supported images from that folder as temporary uploads. Folder source choices are restored on the next app start when the current score library is a SQLite file.

## Manual Decisions

Manual decisions are the final culling layer. Model and LLM scores help sort and explain, but they do not override your pick/hold/reject decisions.

- `Pick`: selected for delivery or later editing.
- `Hold`: worth another pass.
- `Reject`: excluded from the final set.
- Star ratings and color labels can be used for later Lightroom/Capture One style workflows.

## LLM Review

LLM review is optional. Configure an OpenAI-compatible endpoint and model only when you want image critique, detailed aesthetic/technical scores, retouching advice, and shooting advice. API keys should be stored through the app configuration/keychain flow, not in Git or documentation.

## Exports

Use selected-photo export for delivery candidates. Use CSV export when you need scoring evidence, manual status, color labels, and downstream mappings. See [Export Workflows](export-workflows.md).

## Version and Updates

Open **Settings → About Culvia** to see the version of the service currently serving the page, its runtime form, platform, and architecture. Desktop Full and Desktop Lite also show the desktop shell and Python service versions separately when they differ.

Choose **Check for updates** to query the latest stable release from the official Culvia GitHub repository. Culvia does not check in the background and does not download or install an update automatically. When a newer version is available, follow the release link, choose the package that exactly matches your platform and runtime form, and verify its checksum or GitHub attestation before installing it. If that Release does not provide an exact match, do not substitute another platform or runtime form; keep the current installation and check the release notes for availability. Desktop Lite users should resolve any shell/service version mismatch and restart the app before relying on new-version behavior.
