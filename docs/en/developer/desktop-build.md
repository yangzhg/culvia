# Desktop Build

Simplified Chinese: [../../zh-CN/developer/desktop-build.md](../../zh-CN/developer/desktop-build.md)

Culvia's desktop app is a Desktop shell around the Python backend. The desktop executable starts the bundled backend, waits for `/health`, reads the JSON ready event, then opens the local Web UI. The desktop app should not depend on repository `bin/` launchers.

`make` and `scripts/culvia-dev` targets print human-readable plans, progress lines, and summaries by default. Use the underlying Python tools with `--json` only when CI or another script needs machine-readable output.

Long-running desktop builds emit nested progress on stderr. The macOS release lane prints the current outer step, then streams output from expensive child commands such as npm install, PyInstaller backend creation, desktop bundling, and launch smoke verification. JSON mode keeps stdout machine-readable and still sends progress to stderr.

## Development Shell

```bash
make desktop-dev
```

This installs desktop npm dependencies under `desktop/tauri/` and runs the local desktop dev shell.

## App Icons

```bash
make app-icons
```

The brand icon is generated from `assets/brand/culvia-icon.svg`. The command syncs `web/favicon.svg`, the splash mark in `desktop/tauri/src-tauri/assets/splash.html`, and the desktop icon set under `desktop/tauri/src-tauri/icons/`, including macOS `.icns`, Windows `.ico`, and PNG outputs used by Linux and generic bundling. Run it after changing the brand SVG and before building desktop releases.

## Backend Plan and Build

```bash
make backend-plan
make backend-placeholder
make backend-build
```

Machine-readable underlying commands:

```bash
python3 desktop/tauri/scripts/build-backend.py --check-plan --json
python3 desktop/tauri/scripts/build-backend.py --ensure-placeholder --json
python3 desktop/tauri/scripts/build-backend.py --build --json
```

The backend build uses PyInstaller in onedir mode, bundles `web/` as `share/culvia/web`, and writes target-specific runtime directories under `desktop/tauri/src-tauri/runtime/backend/`.

`make backend-build` prints its build phases before PyInstaller starts, including target triple, output binary path, signing identity when applicable, temporary work/spec paths, and the live PyInstaller log.

## Runtime Profiles

Desktop startup supports four runtime modes. Desktop users should rely on automatic setup or the persisted `runtime.json`; environment variables are developer and CI overrides.

- `full`: default release mode. The desktop shell starts the bundled `culvia-server` runtime and does not require a user Python installation.
- `lite`: the desktop shell uses a user-selected or discovered Python 3.11+ executable to create an app-managed virtualenv, installs Culvia into that virtualenv when dependencies are missing, then starts `python -m culvia.server`.
- `auto`: use the bundled backend when it exists; otherwise fall back to `lite`.
- `dev`: use the existing development server at `http://127.0.0.1:8501`.

In `full`, `lite`, and `auto`, the desktop shell starts the local backend on a random available localhost port and reads the final URL from the backend ready event. Only `dev` mode assumes port `8501`.

Lite mode never installs dependencies into a global Python environment. It creates or repairs a virtualenv under the user data directory by default:

```text
macOS:   ~/Library/Application Support/Culvia/runtime/venv
Windows: %LOCALAPPDATA%\Culvia\runtime\venv
Linux:   ${XDG_DATA_HOME:-~/.local/share}/culvia/runtime/venv
```

The persisted config lives next to that runtime:

```text
macOS:   ~/Library/Application Support/Culvia/runtime/runtime.json
Windows: %LOCALAPPDATA%\Culvia\runtime\runtime.json
Linux:   ${XDG_DATA_HOME:-~/.local/share}/culvia/runtime/runtime.json
```

Config priority is: environment variables > `runtime.json` > built-in defaults. The persisted config can be updated with:

```bash
make runtime-configure CLI_ARGS="--mode lite --python /opt/homebrew/bin/python3.11 --venv '$HOME/Library/Application Support/Culvia/runtime/venv'"
make runtime-config CLI_ARGS="--json"
make runtime-reset-config
```

Underlying commands:

```bash
culvia runtime configure --mode lite --python /opt/homebrew/bin/python3.11
culvia runtime config --json
culvia runtime reset-config
```

Useful developer overrides:

```bash
export CULVIA_DESKTOP_RUNTIME_MODE=lite
export CULVIA_RUNTIME_PYTHON=/opt/homebrew/bin/python3.11
export CULVIA_RUNTIME_VENV="$HOME/Library/Application Support/Culvia/runtime/venv"
export CULVIA_RUNTIME_PACKAGE='culvia[desktop-runtime]==0.1.0'
```

For source-checkout development, inspect or repair the same runtime with:

```bash
make runtime-doctor CLI_ARGS="--json"
make runtime-create
make runtime-install CLI_ARGS="--editable-source $PWD"
make runtime-ensure CLI_ARGS="--editable-source $PWD"
```

The underlying CLI is:

```bash
culvia runtime doctor --profile desktop-lite
culvia runtime create --profile desktop-lite
culvia runtime install --profile desktop-lite
culvia runtime ensure --profile desktop-lite
```

`doctor` checks Python, the virtualenv path, and required modules with `importlib.util.find_spec`; it does not import heavy model libraries. `ensure` creates the virtualenv if needed and installs missing dependencies unless `CULVIA_RUNTIME_SKIP_INSTALL=1` is set.

## macOS App Package

```bash
make macos-release-plan
make macos-release
```

This runs the local macOS app/dmg build sequence: scoped cleanup, app preflight, npm dependency install, backend build, headless desktop app/dmg build, artifact preflight, and launch verification. This lane may use ad-hoc or Apple Development signing and does not block on Developer ID signing or notarization.

Expected output:

```text
dist/macos/Culvia.app
dist/macos/Culvia_<version>_<arch>.dmg
dist/macos/Culvia_<version>_<arch>.dmg.sha256
dist/macos/Culvia_<version>_<arch>.dmg.evidence.json
```

Desktop shell and PyInstaller intermediates remain under `desktop/tauri/src-tauri/target/` and `desktop/tauri/src-tauri/runtime/backend/`; only the staged files under `dist/macos/` are release artifacts.

## Desktop Lite Packages

Lite packages ship only the desktop shell. They do not bundle the PyInstaller backend or copied Web assets. On first launch, the desktop shell uses Python 3.11+ to create or repair an app-managed virtualenv, installs the configured Culvia runtime package when dependencies are missing, and then starts `python -m culvia.server`.

Use the generic entrypoint for the current OS:

```bash
make lite-release-plan
make lite-release
```

Platform-specific entries are also available:

```bash
make macos-lite-release-plan
make macos-lite-release
scripts/culvia-dev.ps1 windows-lite-release-plan
scripts/culvia-dev.ps1 windows-lite-release
scripts/culvia-dev linux-lite-release-plan
scripts/culvia-dev linux-lite-release
```

Expected Lite output:

```text
dist/macos-lite/Culvia.app
dist/macos-lite/Culvia_<version>_<arch>.dmg
dist/windows-lite/culvia-<version>-windows-lite-x86_64-pc-windows-msvc.zip
dist/linux-lite/culvia-<version>-linux-lite-x86_64-unknown-linux-gnu.tar.gz
```

The `runtime.json` priority remains: environment variables > persisted runtime config > package default. Lite release packages default to `lite` without requiring users to set an environment variable.

Use the strict lane only when Developer ID signing and notarization inputs are configured:

```bash
make macos-notarized-release-plan
make macos-notarized-release
```

## Windows Package

Build Windows packages on Windows. Cross-building from macOS/Linux is not the supported release path because both the desktop executable and the PyInstaller backend must be real Windows PE executables.

Required runner dependencies:

- Python 3.11+
- Node.js 20+
- Rust stable MSVC toolchain
- Microsoft Visual Studio Build Tools / Windows SDK required by the desktop shell implementation and Rust

From PowerShell:

```powershell
scripts/culvia-dev.ps1 init
scripts/culvia-dev.ps1 windows-release-plan
scripts/culvia-dev.ps1 windows-release
```

Machine-readable underlying commands:

```powershell
python tools/desktop_release_contract.py --platform windows --check-plan --json
python tools/desktop_release_contract.py --platform windows --run --json
```

The native release contract installs desktop extras, installs desktop npm dependencies, builds the PyInstaller backend, verifies the backend runtime, builds the desktop shell, creates the portable Windows zip, runs artifact/runtime verification, runs the package gate, and writes checksum/evidence files.

Expected output:

```text
dist/windows/culvia-<version>-windows-x86_64-pc-windows-msvc.zip
dist/windows/culvia-<version>-windows-x86_64-pc-windows-msvc.zip.sha256
dist/windows/culvia-<version>-windows-x86_64-pc-windows-msvc.zip.evidence.json
```

The zip is portable: users extract it and run `culvia-desktop.exe`. The bundled `culvia-server.exe` contains the Python runtime; users should not need to install system Python.

## Linux Package

Build Linux packages on Linux. Cross-building from macOS/Windows is not the supported release path because both the desktop executable and the PyInstaller backend must be real Linux ELF executables.

Required runner dependencies:

- Python 3.11+
- Node.js 20+
- Rust stable GNU toolchain
- Linux desktop shell system packages such as `libwebkit2gtk-4.1-dev`, `libgtk-3-dev`, `libayatana-appindicator3-dev`, `librsvg2-dev`, `patchelf`, and `xvfb`

From the repository root:

```bash
scripts/culvia-dev init
scripts/culvia-dev linux-release-plan
scripts/culvia-dev linux-release
```

If `make` is available:

```bash
make linux-release-plan
make linux-release
```

Machine-readable underlying commands:

```bash
python tools/desktop_release_contract.py --platform linux --check-plan --json
python tools/desktop_release_contract.py --platform linux --run --json
```

The native release contract installs desktop extras, installs desktop npm dependencies, builds the PyInstaller backend, verifies the backend runtime, builds the desktop shell, creates the Linux `.tar.gz`, runs artifact/runtime verification, runs the package gate, and writes checksum/evidence files.

Expected output:

```text
dist/linux/culvia-<version>-linux-x86_64-unknown-linux-gnu.tar.gz
dist/linux/culvia-<version>-linux-x86_64-unknown-linux-gnu.tar.gz.sha256
dist/linux/culvia-<version>-linux-x86_64-unknown-linux-gnu.tar.gz.evidence.json
```

The archive is self-contained. Users extract it and run `bin/culvia`; the bundled backend contains the Python runtime.

## Manual Package Tools

Windows and Linux final portable packages are built on target OS runners. Use the release contract and package tools:

```bash
python tools/desktop_release_contract.py --platform windows --check-plan --json
python tools/desktop_release_contract.py --platform linux --check-plan --json
python tools/desktop_release_contract.py --platform windows --profile lite --check-plan --json
python tools/desktop_release_contract.py --platform linux --profile lite --check-plan --json
python tools/build_windows_zip.py --check-plan --target x86_64-pc-windows-msvc --desktop-binary <culvia-desktop.exe> --backend-binary <culvia-server.exe> --json
python tools/build_linux_tgz.py --check-plan --target x86_64-unknown-linux-gnu --desktop-binary <culvia-desktop> --backend-binary <culvia-server> --json
python tools/build_windows_zip.py --runtime-profile lite --check-plan --target x86_64-pc-windows-msvc --desktop-binary <culvia-desktop.exe> --json
python tools/build_linux_tgz.py --runtime-profile lite --check-plan --target x86_64-unknown-linux-gnu --desktop-binary <culvia-desktop> --json
```

The package tools are lower-level helpers. Prefer the native release contract unless you are debugging one packaging stage.

See [Release Checklist](release-checklist.md) for the full release gate.
