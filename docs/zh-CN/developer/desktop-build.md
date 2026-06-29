# 桌面应用构建

English: [../../en/developer/desktop-build.md](../../en/developer/desktop-build.md)

Culvia 桌面应用是包裹 Python backend 的桌面壳。当前桌面壳实现使用 Tauri。桌面可执行文件启动内置 backend，等待 `/health`，读取 JSON ready event，然后打开本地 Web UI。桌面 App 不应该依赖仓库里的 `bin/` 启动脚本。

`make` 和 `scripts/culvia-dev` 目标默认输出适合人工阅读的计划、进度和摘要。只有 CI 或其他脚本需要机器可读结果时，才直接调用底层 Python 工具并加 `--json`。

耗时较长的桌面构建会在 stderr 输出嵌套进度。macOS release 线会先显示当前外层步骤，再实时透传 npm install、PyInstaller backend 构建、桌面打包和启动验证等耗时子命令的输出。JSON 模式仍保持 stdout 为机器可读结果，进度信息走 stderr。

## 开发外壳

```bash
make desktop-dev
```

该命令会在 `desktop/tauri/` 下安装桌面 npm 依赖，并运行本地桌面 dev shell。

## App 图标

```bash
make app-icons
```

品牌图标从 `assets/brand/culvia-icon.svg` 生成。该命令会同步 `web/favicon.svg`、`desktop/tauri/src-tauri/assets/splash.html` 中的 splash 标识，并更新 `desktop/tauri/src-tauri/icons/` 下的桌面图标集，包括 macOS `.icns`、Windows `.ico`，以及 Linux 和通用打包使用的 PNG。修改品牌 SVG 后、构建桌面发布包前应运行该命令。

## Backend 计划与构建

```bash
make backend-plan
make backend-placeholder
make backend-build
```

机器可读的底层命令：

```bash
python3 desktop/tauri/scripts/build-backend.py --check-plan --json
python3 desktop/tauri/scripts/build-backend.py --ensure-placeholder --json
python3 desktop/tauri/scripts/build-backend.py --build --json
```

Backend 构建使用 PyInstaller onedir 模式，把 `web/` 作为 `share/culvia/web` 打包，并把目标平台 runtime 目录写入 `desktop/tauri/src-tauri/runtime/backend/`。

`make backend-build` 会在 PyInstaller 开始前打印构建阶段，包括 target triple、输出二进制路径、适用时的签名 identity、临时 work/spec 路径，并保留 PyInstaller 实时日志。

## 运行时模式

桌面启动支持四种模式。桌面用户应依赖自动初始化或持久化的 `runtime.json`；环境变量只作为开发、CI 和故障排查 override。

- `full`：默认发布模式。桌面壳启动内置 `culvia-server` runtime，不要求用户安装 Python。
- `lite`：桌面壳使用用户指定或自动发现的 Python 3.11+，创建应用自己管理的 virtualenv，依赖缺失时把 Culvia 安装到该 virtualenv，然后启动 `python -m culvia.server`。
- `auto`：优先使用内置 backend；找不到内置 backend 时回落到 `lite`。
- `dev`：使用已有开发服务 `http://127.0.0.1:8501`。

Lite 模式不会把依赖安装到全局 Python。默认 virtualenv 位于用户数据目录：

```text
macOS:   ~/Library/Application Support/Culvia/runtime/venv
Windows: %LOCALAPPDATA%\Culvia\runtime\venv
Linux:   ${XDG_DATA_HOME:-~/.local/share}/culvia/runtime/venv
```

持久化配置文件位于同一 runtime 目录：

```text
macOS:   ~/Library/Application Support/Culvia/runtime/runtime.json
Windows: %LOCALAPPDATA%\Culvia\runtime\runtime.json
Linux:   ${XDG_DATA_HOME:-~/.local/share}/culvia/runtime/runtime.json
```

配置优先级为：环境变量 > `runtime.json` > 内置默认值。可以用以下命令写入持久化配置：

```bash
make runtime-configure CLI_ARGS="--mode lite --python /opt/homebrew/bin/python3.11 --venv '$HOME/Library/Application Support/Culvia/runtime/venv'"
make runtime-config CLI_ARGS="--json"
make runtime-reset-config
```

底层命令：

```bash
culvia runtime configure --mode lite --python /opt/homebrew/bin/python3.11
culvia runtime config --json
culvia runtime reset-config
```

开发 override：

```bash
export CULVIA_DESKTOP_RUNTIME_MODE=lite
export CULVIA_RUNTIME_PYTHON=/opt/homebrew/bin/python3.11
export CULVIA_RUNTIME_VENV="$HOME/Library/Application Support/Culvia/runtime/venv"
export CULVIA_RUNTIME_PACKAGE='culvia[desktop-runtime]==0.1.0'
```

源码开发时可以用同一套 runtime 命令检查或修复环境：

```bash
make runtime-doctor CLI_ARGS="--json"
make runtime-create
make runtime-install CLI_ARGS="--editable-source $PWD"
make runtime-ensure CLI_ARGS="--editable-source $PWD"
```

底层 CLI：

```bash
culvia runtime doctor --profile desktop-lite
culvia runtime create --profile desktop-lite
culvia runtime install --profile desktop-lite
culvia runtime ensure --profile desktop-lite
```

`doctor` 使用 `importlib.util.find_spec` 检查 Python、virtualenv 路径和依赖模块，不会真正导入较重的模型库。`ensure` 会在需要时创建 virtualenv，并在缺少依赖时安装；设置 `CULVIA_RUNTIME_SKIP_INSTALL=1` 时只检查不安装。

## macOS App 包

```bash
make macos-release-plan
make macos-release
```

该命令执行本地 macOS app/dmg 构建流程：定向清理、app 预检、npm 依赖安装、backend 构建、headless 桌面 app/dmg 构建、artifact preflight 和启动验证。这条线可以使用 ad-hoc 或 Apple Development 签名，不会因为缺少 Developer ID 签名或公证而阻塞。

预期产物：

```text
dist/macos/Culvia.app
dist/macos/Culvia_<version>_<arch>.dmg
dist/macos/Culvia_<version>_<arch>.dmg.sha256
dist/macos/Culvia_<version>_<arch>.dmg.evidence.json
```

桌面壳和 PyInstaller 的中间产物仍保留在 `desktop/tauri/src-tauri/target/` 与 `desktop/tauri/src-tauri/runtime/backend/`；只有 `dist/macos/` 下的文件作为发布产物。

## 桌面 Lite 包

Lite 包只分发桌面壳，不内置 PyInstaller backend，也不复制 Web assets。首次启动时，桌面壳会使用 Python 3.11+ 创建或修复应用自己管理的 virtualenv，在缺少依赖时安装已配置的 Culvia runtime package，然后启动 `python -m culvia.server`。

当前系统的通用入口：

```bash
make lite-release-plan
make lite-release
```

也可以使用平台专用入口：

```bash
make macos-lite-release-plan
make macos-lite-release
scripts/culvia-dev.ps1 windows-lite-release-plan
scripts/culvia-dev.ps1 windows-lite-release
scripts/culvia-dev linux-lite-release-plan
scripts/culvia-dev linux-lite-release
```

Lite 预期产物：

```text
dist/macos-lite/Culvia.app
dist/macos-lite/Culvia_<version>_<arch>.dmg
dist/windows-lite/culvia-<version>-windows-lite-x86_64-pc-windows-msvc.zip
dist/linux-lite/culvia-<version>-linux-lite-x86_64-unknown-linux-gnu.tar.gz
```

`runtime.json` 的优先级仍是：环境变量 > 持久化 runtime 配置 > 包默认值。Lite release 包默认以 `lite` 模式启动，不要求用户手动设置环境变量。

只有在已配置 Developer ID 签名和公证输入时，才运行严格发布线：

```bash
make macos-notarized-release-plan
make macos-notarized-release
```

## Windows 包

Windows 包应在 Windows 上构建。不支持从 macOS/Linux 作为正式发布路径交叉构建，因为桌面可执行文件和 PyInstaller backend 都必须是真实 Windows PE 可执行文件。

Runner 前置依赖：

- Python 3.11+
- Node.js 20+
- Rust stable MSVC toolchain
- 当前桌面壳实现和 Rust 需要的 Microsoft Visual Studio Build Tools / Windows SDK

PowerShell：

```powershell
scripts/culvia-dev.ps1 init
scripts/culvia-dev.ps1 windows-release-plan
scripts/culvia-dev.ps1 windows-release
```

机器可读的底层命令：

```powershell
python tools/desktop_release_contract.py --platform windows --check-plan --json
python tools/desktop_release_contract.py --platform windows --run --json
```

原生 release contract 会安装 desktop extras、安装桌面 npm 依赖、构建 PyInstaller backend、验证 backend 运行时、构建桌面壳、生成便携 Windows zip、运行 artifact/runtime 验证、运行发布包 gate，并写入 checksum/evidence 文件。

预期产物：

```text
dist/windows/culvia-<version>-windows-x86_64-pc-windows-msvc.zip
dist/windows/culvia-<version>-windows-x86_64-pc-windows-msvc.zip.sha256
dist/windows/culvia-<version>-windows-x86_64-pc-windows-msvc.zip.evidence.json
```

该 zip 是便携包：用户解压后运行 `culvia-desktop.exe`。内置的 `culvia-server.exe` 已包含 Python runtime，用户不应再安装系统 Python。

## Linux 包

Linux 包应在 Linux 上构建。不支持从 macOS/Windows 作为正式发布路径交叉构建，因为桌面可执行文件和 PyInstaller backend 都必须是真实 Linux ELF 可执行文件。

Runner 前置依赖：

- Python 3.11+
- Node.js 20+
- Rust stable GNU toolchain
- Linux 桌面壳系统依赖，例如 `libwebkit2gtk-4.1-dev`、`libgtk-3-dev`、`libayatana-appindicator3-dev`、`librsvg2-dev`、`patchelf` 和 `xvfb`

仓库根目录：

```bash
scripts/culvia-dev init
scripts/culvia-dev linux-release-plan
scripts/culvia-dev linux-release
```

如果环境有 `make`：

```bash
make linux-release-plan
make linux-release
```

机器可读的底层命令：

```bash
python tools/desktop_release_contract.py --platform linux --check-plan --json
python tools/desktop_release_contract.py --platform linux --run --json
```

原生 release contract 会安装 desktop extras、安装桌面 npm 依赖、构建 PyInstaller backend、验证 backend 运行时、构建桌面壳、生成 Linux `.tar.gz`、运行 artifact/runtime 验证、运行发布包 gate，并写入 checksum/evidence 文件。

预期产物：

```text
dist/linux/culvia-<version>-linux-x86_64-unknown-linux-gnu.tar.gz
dist/linux/culvia-<version>-linux-x86_64-unknown-linux-gnu.tar.gz.sha256
dist/linux/culvia-<version>-linux-x86_64-unknown-linux-gnu.tar.gz.evidence.json
```

该归档是自包含包。用户解压后运行 `bin/culvia`；内置 backend 已包含 Python runtime。

## 手动包工具

Windows 和 Linux 最终便携包需要在目标 OS runner 上构建。使用 release contract 和包工具：

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

包工具是更底层的辅助入口。除非正在调试某个打包阶段，否则优先使用原生 release contract。

完整发布 gate 见 [发布检查清单](release-checklist.md)。
