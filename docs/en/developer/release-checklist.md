# Release Checklist

Simplified Chinese: [../../zh-CN/developer/release-checklist.md](../../zh-CN/developer/release-checklist.md)

Use this checklist before open-source release, desktop packaging, or large changes. It keeps only checks that are reproducible and valuable over time: unit tests, syntax checks, privacy scanning, pip distribution, desktop backend checks, final package structure, and release evidence.

## Baseline Checks

Preferred local entrypoints:

```bash
make lint
make test
```

`make lint` uses the same pre-commit configuration as the commit hook. Run the behavior suite separately. Individual checks are available for focused work:

```bash
python -m pre_commit run --all-files
python -m ruff format --check culvia culvia_app.py tests tools desktop/tauri/scripts
python -m ruff check culvia culvia_app.py tests tools desktop/tauri/scripts
python tools/pre_commit_checks.py js-syntax
python tools/pre_commit_checks.py shell-syntax
python tools/pre_commit_checks.py rust-format
python tools/pre_commit_checks.py secret-scan
git diff --check
```

For frontend changes, at least run:

```bash
make js-check
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

Before tagging, verify that every package manifest agrees with the canonical Python version and that the intended tag matches it exactly:

```bash
python tools/check_version_sync.py --tag v<version>
```

Never move or reuse a published version tag, and never replace release assets with a different build under the same version. Bump the version for every distinct published build.

Pushing a `v<version>` tag triggers `.github/workflows/desktop-release.yml`. Its `release` profile builds Full and Lite macOS packages for arm64 and x64, Full and Lite Windows packages for x64, and the Linux Lite x64 package. macOS Lite DMGs and their sidecars carry an explicit `-lite` basename, and the publish job rejects any duplicate asset basename before upload. Linux Full remains excluded because it exceeds the GitHub Release asset limit. The workflow also builds the Python wheel and source distribution, generates GitHub Artifact Attestations for published assets, uploads verified workflow artifacts, and creates the matching GitHub Release as a draft before publishing it. Runs targeting the same manual `release_tag` or ref are serialized. A failed upload leaves only a replaceable draft for a safe retry. The workflow rejects a tag that does not equal the synchronized package version, or a published Release that already exists for that tag.

A Lite release installs its exact same-version Culvia wheel from the official GitHub Release, while resolving third-party dependencies through pip. The publish job must therefore include the matching `culvia-<version>-py3-none-any.whl` in the same draft as every Lite desktop asset. The source job enforces this release blocker by installing that wheel's `desktop-runtime` extra and all resolved dependencies into a fresh virtualenv, then checking the service version, shell runtime contract, required modules, and extra dependency before any release can be published.

For manual validation, run the same workflow from GitHub Actions with `publish_release` disabled. Manual runs default to `platform=all` and `profile=release`; while publishing is disabled, they may narrow either input. Enabling `publish_release` requires the unchanged `platform=all` and `profile=release` selection, plus either a tag ref or an existing `release_tag`. The workflow rejects an incomplete publish matrix.

The default macOS CI lane uses the normal non-strict app/dmg release path, so it may produce ad-hoc signed or Apple Development signed artifacts. Developer ID signing, notarization, and strict Gatekeeper validation remain explicit release-operator concerns.

After downloading a release asset, provenance can be checked with:

```bash
gh attestation verify <downloaded-asset> --repo yangzhg/culvia
```

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
make backend-placeholder
cargo test --locked --manifest-path desktop/tauri/src-tauri/Cargo.toml
```

The desktop shell uses the local-http frontend contract declared in `desktop/tauri/desktop-shell.contract.json`; the health path is `/health`, and the main entrypoint is `culvia-supervisor`. The placeholder supports compile checks; release builds use the real backend.

For Desktop Lite validation, use a disposable `CULVIA_RUNTIME_VENV` and run `python -m culvia.runtime_manager ensure --json --editable-source <repo>`. Run this explicitly because it can install dependencies.

## Backend Runtime Checks

```bash
python3 desktop/tauri/scripts/build-backend.py --check-plan --json
python3 desktop/tauri/scripts/build-backend.py --ensure-placeholder --json
python3 desktop/tauri/scripts/build-backend.py --build --json
python tools/check_backend_smoke.py --binary <backend> --timeout 90 --json
python tools/check_backend_workflow_smoke.py --binary <backend> --timeout 120 --json
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
```

Artifact preflight checks already-built `.app` / `.dmg` packages. Local ad-hoc or Apple Development signing does not provide Developer ID signing or notarization.

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
python tools/check_portable_package_preflight.py --windows-zip dist/windows/culvia-0.2.0-windows-x86_64-pc-windows-msvc.zip --json
python tools/check_portable_package_preflight.py --windows-lite-zip dist/windows-lite/culvia-0.2.0-windows-lite-x86_64-pc-windows-msvc.zip --json
python tools/check_portable_package_runtime.py --windows-zip dist/windows/culvia-0.2.0-windows-x86_64-pc-windows-msvc.zip --exit-after-ms 20000 --json
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
python tools/check_portable_package_preflight.py --linux-tgz dist/linux/culvia-0.2.0-linux-x86_64-unknown-linux-gnu.tar.gz --json
python tools/check_portable_package_preflight.py --linux-lite-tgz dist/linux-lite/culvia-0.2.0-linux-lite-x86_64-unknown-linux-gnu.tar.gz --json
python tools/check_portable_package_runtime.py --linux-tgz dist/linux/culvia-0.2.0-linux-x86_64-unknown-linux-gnu.tar.gz --exit-after-ms 20000 --json
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

Checksum sidecars use UTF-8 with LF line endings on every build platform. Keep the downloaded package and its `.sha256` file together, then verify from that directory:

```bash
shasum -a 256 -c <artifact>.sha256  # macOS
sha256sum -c <artifact>.sha256      # Linux
```

## Keychain Smoke

```bash
python -m pip install -e '.[desktop]'
python tools/check_secret_store_keychain_smoke.py --allow-write --preserve-existing --json
python tools/release_status_report.py --json --keychain-smoke
```

Run this check explicitly in a real desktop user session. It temporarily writes a random sentinel, verifies read/delete behavior, and restores the previous key when `--preserve-existing` is used.
