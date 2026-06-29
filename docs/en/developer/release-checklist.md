# Release Checklist

Simplified Chinese: [../../zh-CN/developer/release-checklist.md](../../zh-CN/developer/release-checklist.md)

Use this checklist before open-source release, desktop packaging, or large changes. It keeps only checks that are reproducible and valuable over time: unit tests, syntax checks, privacy scanning, pip distribution, desktop backend checks, final package structure, and release evidence.

## Baseline Checks

Preferred local entrypoints:

```bash
make pre-commit
make test
make js-check
make lint
make gate
```

Equivalent underlying commands:

```bash
python -c "import sys; assert sys.version_info >= (3, 11), sys.version"
python -m unittest discover -s tests
PYTHONPYCACHEPREFIX=/private/tmp/culvia-pycache python -m compileall -q culvia_app.py culvia tests tools
python -m pre_commit run --all-files
python -m ruff format --check culvia culvia_app.py tests tools desktop/tauri/scripts
python -m ruff check culvia culvia_app.py tests tools desktop/tauri/scripts
python tools/pre_commit_checks.py js-syntax
python tools/pre_commit_checks.py shell-syntax
python tools/pre_commit_checks.py makefile
python tools/pre_commit_checks.py rust-format
python tools/pre_commit_checks.py secret-scan
git diff --check
rg -n "sk-[A-Za-z0-9]{12,}" --glob '!model_cache/**' --glob '!thumbnail_cache/**' --glob '!upload_cache/**' --glob '!culvia_uploads/**' --glob '!__pycache__/**' .
```

Aggregated gate:

```bash
python tools/formal_gate.py
python tools/formal_gate.py --skip-release-smoke
python tools/formal_gate.py --build-sdist
python tools/formal_gate.py --sdist-artifact dist/python/culvia-0.1.0.tar.gz
```

For frontend changes, at least run:

```bash
find web -name '*.js' -print0 | xargs -0 -n1 node --check
python -m unittest tests.test_frontend_i18n tests.test_frontend_api_client tests.test_frontend_viewer_keyboard tests.test_frontend_manual_status
```

When adding frontend modules, update the `web/index.html` references, the `share/culvia/web` package data in `pyproject.toml`, and the release smoke required-file list when the file must ship in pip/desktop packages. Keep `tests/test_entrypoints_and_packaging.py` passing.

## pip Release

```bash
make python-release-plan
make python-release
python -m pip install -e '.[release]'
python tools/release_smoke.py --build --wheelhouse dist/python --build-sdist --dist-dir dist/python --install --twine-check --strict
```

Expected output:

```text
dist/python/culvia-<version>-py3-none-any.whl
dist/python/culvia-<version>.tar.gz
```

Source distributions and wheels must not contain runtime caches, SQLite databases, CSV files, uploaded images, thumbnails, model caches, desktop shell target/gen/runtime outputs, or credential files.

The repository root must not contain runtime data. Run `tools/clean_runtime_artifacts.py` when cleanup is needed. Before release, confirm these boundaries are still covered by `.gitignore` and absent from sdist/wheel/desktop packages:

```text
model_cache/
analysis_cache/
thumbnail_cache/
upload_cache/
*.sqlite
*.sqlite-*
*.db
```

## GitHub Release Workflow

Pushing a `v<version>` tag triggers `.github/workflows/desktop-release.yml`. The tag workflow builds full macOS arm64, macOS x64, Windows x64, and Linux x64 desktop packages, builds the Python wheel and source distribution, uploads verified workflow artifacts, and creates or updates the matching GitHub Release.

For manual validation, run the same workflow from GitHub Actions with `publish_release` disabled. Manual runs can narrow `platform` and `profile`; enabling `publish_release` requires running on a tag ref or passing an existing `release_tag`.

The default macOS CI lane uses the normal non-strict app/dmg release path, so it may produce ad-hoc signed or Apple Development signed artifacts. Developer ID signing, notarization, and strict Gatekeeper validation remain explicit release-operator concerns.

## Desktop Readiness

Preferred local entrypoints:

```bash
make desktop-ready
make backend-plan
make release-status
```

```bash
python tools/check_desktop_readiness.py --json
python tools/check_desktop_readiness.py --strict-toolchain
python tools/formal_gate.py --strict-desktop
```

`--strict-desktop` runs Desktop release preflight, backend placeholder checks, `cargo check`, `cargo test`, `tauri:info`, and backend plan checks. The desktop shell must keep using the local-http frontend contract declared in `desktop/tauri/desktop-shell.contract.json`; the health path is `/health`, and the main entrypoint is `culvia-supervisor`.

For Desktop Lite validation, use a disposable `CULVIA_RUNTIME_VENV` and run `python -m culvia.runtime_manager ensure --json --editable-source <repo>`. This is intentionally not part of the default gate because it can install dependencies.

## Backend Runtime Checks

```bash
python3 desktop/tauri/scripts/build-backend.py --check-plan --json
python3 desktop/tauri/scripts/build-backend.py --ensure-placeholder --json
python3 desktop/tauri/scripts/build-backend.py --build --json
python tools/check_backend_smoke.py --binary <backend> --timeout 90 --json
python tools/check_backend_workflow_smoke.py --binary <backend> --timeout 120 --json
python tools/formal_gate.py --strict-desktop --backend-smoke --backend-binary <backend>
python tools/formal_gate.py --strict-desktop --backend-workflow-smoke --backend-binary <backend>
```

`tools/check_backend_smoke.py` verifies ready events, `/health`, and process cleanup. `tools/check_backend_workflow_smoke.py` uses a synthetic fixture to verify curation, filters, export preflight, selected-photo export, curation history, and non-secret LLM configuration writes.

## macOS

Preferred local macOS app/dmg entrypoint:

```bash
make macos-release-plan
make macos-release
make macos-lite-release-plan
make macos-lite-release
```

The default local app/dmg lane can use ad-hoc or Apple Development signing and does not block on Developer ID signing or notarization. Use the strict lane when Developer ID signing, notarization, and Gatekeeper validation are configured:

```bash
make macos-notarized-release-plan
make macos-notarized-release
```

```bash
python tools/check_macos_app_preflight.py --json
python tools/clean_macos_app_artifacts.py --json
python tools/build_macos_app.py --check-plan --json
python tools/build_macos_app.py --clean-first --json
python tools/build_macos_app.py --runtime-profile lite --check-plan --json
python tools/build_macos_app.py --runtime-profile lite --clean-first --json
python tools/check_desktop_release_preflight.py --json
python tools/check_desktop_release_preflight.py --strict-signing --backend-binary <backend> --json
npm --prefix desktop/tauri run tauri:build:headless
python tools/check_macos_artifact_preflight.py --json
python tools/check_macos_artifact_preflight.py --strict --json
python tools/check_macos_app_launch_smoke.py --json
python tools/formal_gate.py --macos-artifacts --skip-release-smoke
python tools/formal_gate.py --macos-artifacts --strict-macos-artifacts --macos-app-launch-smoke --skip-release-smoke
```

`--macos-artifacts` checks already-built `.app` / `.dmg` artifacts. Do not treat local ad-hoc or Apple Development signing as Developer ID/notarized release signing.

The macOS release runner stages final artifacts under `dist/macos/`; `desktop/tauri/src-tauri/target/` is an intermediate build directory.

## Windows/Linux Portable Packages

Windows:

```powershell
scripts/culvia-dev.ps1 windows-release-plan
scripts/culvia-dev.ps1 windows-release
scripts/culvia-dev.ps1 windows-lite-release-plan
scripts/culvia-dev.ps1 windows-lite-release
```

```bash
python tools/desktop_release_contract.py --platform windows --check-plan --json
python tools/desktop_release_contract.py --platform windows --run --json
python tools/desktop_release_contract.py --platform windows --profile lite --check-plan --json
python tools/desktop_release_contract.py --platform windows --profile lite --run --json
python tools/build_windows_zip.py --check-plan --target x86_64-pc-windows-msvc --desktop-binary <culvia-desktop.exe> --backend-binary <culvia-server.exe> --json
python tools/build_windows_zip.py --build --target x86_64-pc-windows-msvc --desktop-binary <culvia-desktop.exe> --backend-binary <culvia-server.exe> --json
python tools/build_windows_zip.py --runtime-profile lite --check-plan --target x86_64-pc-windows-msvc --desktop-binary <culvia-desktop.exe> --json
python tools/build_windows_zip.py --runtime-profile lite --build --target x86_64-pc-windows-msvc --desktop-binary <culvia-desktop.exe> --json
python tools/check_portable_package_preflight.py --windows-zip dist/windows/culvia-0.1.0-windows-x86_64-pc-windows-msvc.zip --json
python tools/check_portable_package_preflight.py --windows-lite-zip dist/windows-lite/culvia-0.1.0-windows-lite-x86_64-pc-windows-msvc.zip --json
python tools/check_portable_package_runtime.py --windows-zip dist/windows/culvia-0.1.0-windows-x86_64-pc-windows-msvc.zip --exit-after-ms 20000 --json
python tools/formal_gate.py --windows-zip-artifact dist/windows/culvia-0.1.0-windows-x86_64-pc-windows-msvc.zip --skip-release-smoke
```

Linux:

```bash
scripts/culvia-dev linux-release-plan
scripts/culvia-dev linux-release
scripts/culvia-dev linux-lite-release-plan
scripts/culvia-dev linux-lite-release
python tools/desktop_release_contract.py --platform linux --check-plan --json
python tools/desktop_release_contract.py --platform linux --run --json
python tools/desktop_release_contract.py --platform linux --profile lite --check-plan --json
python tools/desktop_release_contract.py --platform linux --profile lite --run --json
python tools/build_linux_tgz.py --check-plan --target x86_64-unknown-linux-gnu --desktop-binary <culvia-desktop> --backend-binary <culvia-server> --json
python tools/build_linux_tgz.py --build --target x86_64-unknown-linux-gnu --desktop-binary <culvia-desktop> --backend-binary <culvia-server> --json
python tools/build_linux_tgz.py --runtime-profile lite --check-plan --target x86_64-unknown-linux-gnu --desktop-binary <culvia-desktop> --json
python tools/build_linux_tgz.py --runtime-profile lite --build --target x86_64-unknown-linux-gnu --desktop-binary <culvia-desktop> --json
python tools/check_portable_package_preflight.py --linux-tgz dist/linux/culvia-0.1.0-linux-x86_64-unknown-linux-gnu.tar.gz --json
python tools/check_portable_package_preflight.py --linux-lite-tgz dist/linux-lite/culvia-0.1.0-linux-lite-x86_64-unknown-linux-gnu.tar.gz --json
python tools/check_portable_package_runtime.py --linux-tgz dist/linux/culvia-0.1.0-linux-x86_64-unknown-linux-gnu.tar.gz --exit-after-ms 20000 --json
python tools/formal_gate.py --linux-tgz-artifact dist/linux/culvia-0.1.0-linux-x86_64-unknown-linux-gnu.tar.gz --skip-release-smoke
```

Full packages must contain their own Python runtime and web data; users should not need to install system Python. Lite packages intentionally do not bundle the backend or web data; they default to the app-managed virtualenv runtime and require Python 3.11+ on first launch. `tools/check_portable_package_preflight.py` verifies archive structure, path safety, manifest data, executable file types, and forbidden runtime artifacts. `tools/check_portable_package_runtime.py` must run on the target OS runner to verify full package launcher, bundled backend, and fixture workflow.

## Release Evidence

```bash
python tools/desktop_release_contract.py --platform windows --check-plan --json
python tools/desktop_release_contract.py --platform linux --check-plan --json
python tools/desktop_release_contract.py --platform linux --run --json
python tools/write_release_checksum.py <artifact.zip-or-tar.gz> --json
python tools/write_release_evidence_manifest.py --contract-json <contract-output.json> --json
python tools/check_desktop_release_workflow.py --json
python tools/release_status_report.py --json
python tools/release_status_report.py --json --release-smoke --build-sdist --wheelhouse dist/python --dist-dir dist/python
python tools/release_status_report.py --json --launch-runtime
python tools/release_status_report.py --strict --json
```

`.github/workflows/desktop-release.yml` uploads only verified final packages, `.sha256` files, and `.evidence.json` files. It must not upload `dist/**`, `target/**`, backend binary directories, runtime caches, user data, or credentials.

## Keychain Smoke

```bash
python -m pip install -e '.[desktop]'
python tools/check_secret_store_keychain_smoke.py --allow-write --preserve-existing --json
python tools/release_status_report.py --json --keychain-smoke
```

Run this check explicitly in a real desktop user session. It temporarily writes a random sentinel, verifies read/delete behavior, and restores the previous key when `--preserve-existing` is used.
