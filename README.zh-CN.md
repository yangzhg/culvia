# Culvia

英文版：[README.md](README.md)

Culvia 面向摄影师，帮助一组照片走向清晰、可交付的作品选择。它把本地审美/技术评分、可选的大模型视觉评审、人工判断、SQLite 持久化和导出工具组织在同一套 Web/Desktop 代码库中。

## 功能

- 本地评分：审美参考、技术质检、构图/光线/色彩等维度，结果写入 SQLite。
- 选片流程：大图审片、照片墙、多选、鼠标划选、星级、颜色标签、入选/待复核/淘汰和批量采纳。
- 大模型评审：OpenAI-compatible 接口，输出审美画像、技术质检、细维度分数、图片评价、修图建议和拍摄建议。
- 本地媒体：缩略图、预览图、上传缓存和导出都默认保留在本机。
- 多语言：简体中文和英文放在 `web/locales/`，`web/i18n_messages.js` 只作为运行时聚合入口；页面代码不直接写死双语文案。
- 分发形态：pip 安装后可作为 Web 应用运行，也可以作为桌面 App 分发；当前桌面壳使用 Tauri，Electron 不是默认桌面路线。桌面启动支持自包含的 `full` runtime 和应用自己管理 virtualenv 的 `lite` runtime。

## 安装

初始化开发环境：

```bash
make init
```

`make init` 会创建或更新 `~/.venvs/culvia`，并安装开发 extras。需要使用其他环境路径时可以覆盖：

```bash
CULVIA_VENV=$HOME/.venvs/culvia-dev make init
```

## 启动

源码开发时优先使用统一命令入口：

```bash
make server
make web PORT=8501
make web PORT=auto WEB_ARGS=--reload
bin/culvia-web --host 127.0.0.1 --port 8501
```

Windows 使用 PowerShell 包装脚本：

```powershell
scripts/culvia-dev.ps1 init
scripts/culvia-dev.ps1 web --host 127.0.0.1 --port 8501
bin/culvia-web.ps1 --host 127.0.0.1 --port 8501
```

如果使用 Command Prompt，可以运行 `bin\culvia-web.cmd --host 127.0.0.1 --port 8501`。

pip 安装后也会暴露标准 console commands：

```bash
culvia-supervisor
culvia-web --host 127.0.0.1 --port 8501
culvia --help
```

- `make server` / `culvia-supervisor`：推荐本地 Web 入口，带 supervisor、端口选择、健康检查和浏览器打开。
- `make web` / `culvia-web`：直接启动 Starlette/Uvicorn 服务，适合开发和部署。
- `make cli` / `culvia`：命令行批量评分入口。

## 大模型与隐私

大模型配置支持环境变量、当前会话和 SQLite 持久化的非密钥配置，优先级为：当前会话 > SQLite > 环境变量。API key 不应写入 README、测试、日志、SQLite 明文字段或 Git；桌面安全存储由 `tools/check_secret_store_keychain_smoke.py` 验证。

大模型图片评审只在用户显式启用时调用。本地模型默认不上传图片；启用大模型评审后，图片会按对应 OpenAI-compatible 接口要求转为可接受的输入格式。

## 桌面与打包

桌面应用复用同一套 Starlette API 和静态前端。当前桌面壳使用 Tauri，负责窗口、backend 生命周期、原生文件能力、系统凭据能力和应用打包；Python 负责评分、筛选、大模型评审、选片、缓存、导出和持久化。

常用桌面和发布检查：

```bash
make desktop-ready
make app-icons
make runtime-doctor
make runtime-configure
make gate
make release-status
make python-release-plan
make macos-release-plan
make windows-release-plan
make linux-release-plan
```

macOS 本地 App 与构建产物工具：

- `tools/check_macos_app_preflight.py`
- `tools/clean_macos_app_artifacts.py`
- `tools/build_macos_app.py`
- `tools/check_macos_artifact_preflight.py`
- `tools/check_macos_app_launch_smoke.py`

Windows/Linux 便携包和发布证据工具：

- `tools/build_windows_zip.py`
- `tools/build_linux_tgz.py`
- `tools/check_portable_package_preflight.py`
- `tools/check_portable_package_runtime.py`
- `tools/write_release_checksum.py`
- `tools/write_release_evidence_manifest.py`
- `tools/desktop_release_contract.py`
- `.github/workflows/desktop-release.yml`
- `tools/check_desktop_release_workflow.py`

Backend 验证工具：

- `tools/check_backend_smoke.py`
- `tools/check_backend_workflow_smoke.py`

原生桌面发布入口：

- Web favicon 和桌面 App 图标：`make app-icons`
- pip wheel/sdist：先运行 `make python-release-plan`，再运行 `make python-release`
- macOS 本地 app/dmg：先运行 `make macos-release-plan`，再运行 `make macos-release`
- 当前系统的 Lite 桌面包：先运行 `make lite-release-plan`，再运行 `make lite-release`
- macOS 严格公证发布：先运行 `make macos-notarized-release-plan`，再运行 `make macos-notarized-release`
- Windows：先运行 `scripts/culvia-dev.ps1 windows-release-plan`，再在 Windows runner 上运行 `scripts/culvia-dev.ps1 windows-release`
- Windows Lite：先运行 `scripts/culvia-dev.ps1 windows-lite-release-plan`，再运行 `scripts/culvia-dev.ps1 windows-lite-release`
- Linux：先运行 `scripts/culvia-dev linux-release-plan`，再在 Linux runner 上运行 `scripts/culvia-dev linux-release`
- Linux Lite：先运行 `scripts/culvia-dev linux-lite-release-plan`，再运行 `scripts/culvia-dev linux-lite-release`

最终发布产物统一放在仓库根目录：

```text
dist/python/    pip wheel 和源码包
dist/macos/     macOS .app、.dmg、checksum 和 evidence manifest
dist/macos-lite/ macOS Lite .app、.dmg、checksum 和 evidence manifest
dist/windows/   Windows 便携 zip、checksum 和 evidence manifest
dist/windows-lite/ Windows Lite 便携 zip、checksum 和 evidence manifest
dist/linux/     Linux 便携 tar.gz、checksum 和 evidence manifest
dist/linux-lite/ Linux Lite 便携 tar.gz、checksum 和 evidence manifest
```

Desktop Lite runtime 可通过 `culvia runtime ...` 或 `runtime-config`、`runtime-configure`、`runtime-reset-config`、`runtime-doctor`、`runtime-create`、`runtime-install`、`runtime-ensure` 这些 make 目标管理。Lite 模式会创建 Culvia 自己管理的 virtualenv，不会把依赖安装到全局 Python。

## 开发检查

```bash
make pre-commit-install
make pre-commit
make test
make js-check
make lint
make format
make gate
```

`make pre-commit` 会运行 Python 格式/lint、JS 语法、配置文件校验、Shell 语法、Makefile dry-run、Rust 格式以及密钥扫描。发布清单会保留底层 Python 命令，便于 CI 和打包流程可复现。

用户文档从 [docs/zh-CN/user/getting-started.md](docs/zh-CN/user/getting-started.md) 开始。开发文档从 [docs/zh-CN/developer/getting-started.md](docs/zh-CN/developer/getting-started.md) 开始。发布和打包检查见 [docs/zh-CN/developer/release-checklist.md](docs/zh-CN/developer/release-checklist.md)。

## 仓库卫生

不要提交模型缓存、缩略图缓存、上传缓存、SQLite 运行库、导出结果、桌面壳 target/gen/runtime 输出、生成的安装包、API key 或本地日志。

清理工具和常见禁止提交边界：

```text
tools/clean_runtime_artifacts.py
model_cache/
analysis_cache/
thumbnail_cache/
upload_cache/
*.sqlite
*.sqlite-*
*.db
```

`bin/culvia-web` 是受版本管理的源码 Web 启动入口。`tools/clean_runtime_artifacts.py` 用于清理常见运行时产物，例如缓存、构建输出、生成的桌面文件、SQLite 文件和导出 CSV。

## 目录结构

```text
culvia/                  核心服务、评分编排、选片、导出、桌面辅助
culvia_app.py            Starlette app factory、API handler、静态前端挂载
culvia/scoring.py        本地评分与模型集成层
bin/                        Web 源码启动入口
web/                        浏览器 UI 和多语言文案
desktop/tauri/              桌面壳实现和 backend 构建脚本
tools/                      发布、打包、backend 和维护工具
scripts/                    macOS/Linux 和 Windows 的源码开发命令入口
tests/                      单元、服务、打包、多语言和发布契约测试
docs/en/user/               英文用户文档
docs/en/developer/          英文开发文档
docs/zh-CN/user/            简体中文用户文档
docs/zh-CN/developer/       简体中文开发文档
```
