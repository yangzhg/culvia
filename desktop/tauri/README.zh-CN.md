# 桌面壳实现

英文版：[README.md](README.md)

这个目录记录 Culvia 的桌面外壳契约。

当前桌面实现使用 Tauri 包装现有本地 Python Web 应用：

```text
桌面壳进程
  -> 启动 culvia-supervisor backend
  -> 等待 /health
  -> 从 --print-json 读取 JSON ready event
  -> 加载返回的 http://127.0.0.1:<port> URL
```

## 为什么使用本地 HTTP

当前前端刻意保持同源：

- API 请求使用 `/api/...`。
- 媒体和静态文件使用 `/api/image`、`/api/thumbnail` 和 `/static/...`。
- Python 后端负责本地文件授权、缩略图、缓存路径、导出、选片历史和大模型评审持久化。

因此第一阶段桌面壳必须加载本地 HTTP 后端。直接把 `web/index.html` 作为桌面静态资源嵌入暂不作为生产模式，因为在未抽象并测试 base URL 前，这会破坏当前 `/api` 和 `/static` 假设。

## 契约

`desktop-shell.contract.json` 是当前桌面边界的静态事实来源：

- `frontendMode`: `local-http`
- `backendEntrypoint`: `culvia-supervisor`
- `healthPath`: `/health`
- `productionBackendArgs`: 使用 `--port auto`、`--no-open` 和 `--print-json` 启动 supervisor
- `readyEvent`: 桌面外壳读取包含 `event`、`baseUrl` 和 `healthUrl` 的 JSON 行
- `runtimeProfiles`: `full` 使用内置 backend，`lite` 使用应用自己管理的 Python virtualenv，`auto` 在没有内置 backend 时回落到 `lite`

## 构建方向

开发阶段可以先在 `127.0.0.1:8501` 运行 Python 后端，并让桌面 `devUrl` 指向它。

在当前目录中，开发外壳通过 `beforeDevCommand` 运行现有 Python supervisor：

```bash
cd desktop/tauri
npm install
npm run tauri:dev
```

静态桌面检查：

```bash
npm run tauri:info
npm run backend:placeholder
cargo check --manifest-path src-tauri/Cargo.toml
cargo test --manifest-path src-tauri/Cargo.toml
npm run backend:plan
```

`npm run backend:dev` 调用 `python3 scripts/start-dev-backend.py`，从仓库根目录导入 `culvia.supervisor` 并启动：

```text
culvia-supervisor --host 127.0.0.1 --port 8501 --no-open --print-json
```

运行 npm 脚本前应先激活项目 Python 环境，确保 `python3` 指向已安装应用依赖的环境。

`full` 生产包把 `culvia.server:main` 打包为 backend 二进制。Rust 外壳解析内置 backend，用 `--port auto --no-open --print-json` 启动它，从 stdout 解析 ready JSON，等待 `/health`，使用返回的 `baseUrl` 创建主窗口，并在应用退出时终止 backend 进程。full backend 不应要求用户额外安装系统 Python。

`lite` 模式可以通过持久化 runtime 配置或 `CULVIA_DESKTOP_RUNTIME_MODE=lite` 启用。桌面壳会读取用户 runtime 目录下的 `runtime.json`，环境变量只作为开发 override。它会查找配置的 Python 或系统 Python 3.11+，在用户数据目录创建 Culvia 管理的 virtualenv，依赖缺失时安装配置的 package 或默认 `culvia[desktop-runtime]==<app version>`，再启动 `python -m culvia.server`。需要源码开发时可运行 `make runtime-configure CLI_ARGS="--mode lite --python <python>"` 和 `make runtime-ensure CLI_ARGS="--editable-source $PWD"`。

生产 backend 构建入口：

```bash
python -m pip install '.[desktop]'
python3 scripts/build-backend.py --check-plan --json
python3 scripts/build-backend.py --ensure-placeholder
python3 scripts/build-backend.py --build
python ../../tools/check_desktop_release_preflight.py --json --backend-binary src-tauri/runtime/backend/aarch64-apple-darwin/culvia-server/culvia-server
python ../../tools/check_backend_smoke.py --binary src-tauri/runtime/backend/aarch64-apple-darwin/culvia-server/culvia-server --json --timeout 90
```

构建脚本使用 PyInstaller onedir 模式创建 `src-tauri/runtime/backend/{target-triple}/culvia-server/`，并把 `web/` 作为 `share/culvia/web` 数据包含进去，让冻结后的 runtime 可以脱离源码树提供 UI。生成安装包前，应在每个目标系统运行真实构建和 smoke 测试。

`--ensure-placeholder` 会创建一个被忽略的编译检查 stub，用于桌面 cargo 检查；它不是打包产物。在 macOS 发布机器上运行 `python ../../tools/check_desktop_release_preflight.py --strict-signing --backend-binary <path> --json`，可以在缺少 `Developer ID Application` 签名输入、公证输入、图标配置或 backend 可执行权限时失败。

第一阶段发布包是绿色/自包含形态，不要求系统 Python：Windows zip 提供可运行 `.exe`，macOS `.app` 通过 `.dmg` 分发，Linux 使用 `.tar.gz`。Linux 包工具需要在目标平台构建真实 Linux ELF backend：

```bash
npm run linux:tgz:plan -- --target x86_64-unknown-linux-gnu --desktop-binary src-tauri/target/release/culvia-desktop --backend-binary src-tauri/runtime/backend/x86_64-unknown-linux-gnu/culvia-server/culvia-server
npm run linux:tgz:build -- --target x86_64-unknown-linux-gnu --desktop-binary src-tauri/target/release/culvia-desktop --backend-binary src-tauri/runtime/backend/x86_64-unknown-linux-gnu/culvia-server/culvia-server
```

Windows 包工具需要在目标平台构建真实 Windows PE 可执行文件：

```bash
npm run windows:zip:plan -- --target x86_64-pc-windows-msvc --desktop-binary src-tauri/target/release/culvia-desktop.exe --backend-binary src-tauri/runtime/backend/x86_64-pc-windows-msvc/culvia-server/culvia-server.exe
npm run windows:zip:build -- --target x86_64-pc-windows-msvc --desktop-binary src-tauri/target/release/culvia-desktop.exe --backend-binary src-tauri/runtime/backend/x86_64-pc-windows-msvc/culvia-server/culvia-server.exe
```

构建 Windows/Linux 压缩包后，应对最终压缩包运行便携包预检，而不是检查 staging 目录：

```bash
npm run windows:zip:preflight -- ../../dist/windows/culvia-0.1.0-windows-x86_64-pc-windows-msvc.zip
npm run linux:tgz:preflight -- ../../dist/linux/culvia-0.1.0-linux-x86_64-unknown-linux-gnu.tar.gz
```

Windows/Linux runner 的权威流程位于 `../../tools/desktop_release_contract.py`，手动 GitHub Actions 入口是 `../../.github/workflows/desktop-release.yml`。工作流检查器是 `../../tools/check_desktop_release_workflow.py`；它限制上传路径只能是最终 `.zip` / `.tar.gz` 包，并拒绝 release bypass 或 secret 使用。

`src-tauri/tauri.conf.json` 默认使用 `bundle.macOS.signingIdentity = "-"`，让本地开发构建得到完整 ad-hoc bundle 签名，同时保持 hardened runtime。`src-tauri/entitlements.mac.plist` 设置 `com.apple.security.cs.disable-library-validation`；PyInstaller backend 需要它，因为 hardened executable 启动时会加载解包后的 Python runtime。正式 macOS 发布必须改用 `Developer ID Application: ...` identity 或 CI certificate 输入，也可以把 identity 传给 `scripts/build-backend.py --codesign-identity ...` 或 `CULVIA_MACOS_CODESIGN_IDENTITY`，随后通过公证、artifact preflight 和 app launch smoke。App launch smoke 期待 `backendReady`、`windowCreated` 和 `frontendReady`；最后一个事件确认 webview 已加载工作台 DOM，而不只是原生窗口存在。Smoke auto-exit 只在 `frontendReady` 或 `frontendReadyTimeout` 后开始计时。

如果环境没有稳定 Finder 会话，默认 DMG AppleScript 可能因为 Finder AppleEvent 超时失败。可以使用 headless 脚本强制 `CI=true` 并跳过 Finder DMG 美化：

```bash
npm install
npm run tauri:build:headless
```

`scripts/build-headless.py` 会优先解析 `node_modules/.bin/tauri`，只有项目本地 CLI 不可用时才回退到全局 `tauri` 可执行文件。这样本地和 CI 构建不需要全局安装 Tauri。

从仓库根目录运行 `python tools/build_macos_app.py --clean-first --json` 会执行完整本地 macOS app/dmg 构建流程：定向清理 app 构建产物、app 预检、npm 依赖安装、backend 构建、headless app/dmg 构建、artifact preflight、app launch smoke，并把最终产物集中到 `dist/macos/`。定向清理只删除 `desktop/tauri/src-tauri` 下的桌面构建输出；仓库级运行时清理仍然是显式的 `tools/clean_runtime_artifacts.py` 操作。

桌面壳层只应负责桌面事项：窗口生命周期、原生文件/文件夹选择、系统 keychain 集成、backend 生命周期和应用打包。文件夹选择和 reveal 操作目前通过 Python backend API 流转，让同一套 Web UI 可以降级：macOS 使用 Finder 命令，Windows 使用 PowerShell/Explorer，Linux 在 zenity/kdialog 加 xdg-open/gio 可用时启用。LLM API key 通过 Python backend 的 keyring-backed secret store 持久化；SQLite 只保存非密钥 LLM 设置。评分、筛选、大模型评审、选片、缓存、导出和 UI 行为都保留在现有 Python 与 Web 层。
