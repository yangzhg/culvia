# 发布检查清单

英文版：[../../en/developer/release-checklist.md](../../en/developer/release-checklist.md)

这份清单用于开源发布、桌面打包或提交较大改动前的最后检查。它只保留可复现、长期有价值的检查：单元测试、语法检查、隐私扫描、pip 分发、桌面 backend、最终包结构和发布证据。

## 基础检查

推荐的本地统一入口：

```bash
make lint
make test
```

`make lint` 与提交钩子共用 pre-commit 配置，行为测试单独运行。排查局部问题时，也可以直接运行各项检查：

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

前端改动至少运行：

```bash
make js-check
python -m unittest tests.test_frontend_i18n tests.test_frontend_api_client tests.test_frontend_viewer_keyboard tests.test_frontend_manual_status
```

新增前端模块时，应同步更新 `web/index.html` 引用、`pyproject.toml` 的 `share/culvia/web` package data，以及必须随 pip/桌面包发布的 release smoke 文件清单，并让 `tests/test_entrypoints_and_packaging.py` 继续通过。

## pip 发布

```bash
make python-release-plan
make python-release
python -m pip install -e '.[release]'
python tools/release_smoke.py --build --wheelhouse dist/python --build-sdist --dist-dir dist/python --install --twine-check --strict
```

预期产物：

```text
dist/python/culvia-<version>-py3-none-any.whl
dist/python/culvia-<version>.tar.gz
```

源码包和 wheel 不得包含运行时缓存、SQLite、CSV、上传图片、缩略图、模型缓存、桌面壳 target/gen/runtime 输出或凭据文件。

仓库根目录不得包含运行时数据。需要清理时运行 `tools/clean_runtime_artifacts.py`。发布前检查以下边界仍被 `.gitignore` 覆盖，且没有进入 sdist/wheel/桌面包：

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

打 tag 前，先确认所有包清单的版本都与 Python canonical version 一致，并且预期 tag 与它完全匹配：

```bash
python tools/check_version_sync.py --tag v<version>
```

已发布的版本 tag 不得移动或复用，也不得用同一版本号覆盖成另一份构建。每一份不同的正式构建都必须提升版本号。

推送 `v<version>` tag 会触发 `.github/workflows/desktop-release.yml`。其中 `release` profile 会构建 arm64 和 x64 的 macOS Full/Lite 包、x64 的 Windows Full/Lite 包，以及 Linux Lite x64 包。macOS Lite DMG 及其 sidecar 的 basename 会显式包含 `-lite`，publish job 会在上传前拒绝任何重复 basename。Linux Full 因超过 GitHub Release 单资产大小限制，仍不纳入正式发布矩阵。workflow 同时构建 Python wheel 和源码包，为发布资产生成 GitHub Artifact Attestations，上传已验证的 workflow artifacts，并先以草稿创建同名 GitHub Release，全部上传成功后再发布；指向同一个手工 `release_tag` 或 ref 的运行会串行排队。上传失败只会留下可在重试时替换的草稿。若 tag 与已同步的包版本不一致，或该 tag 已存在正式 Release，workflow 会直接拒绝发布。

Lite 发布会从官方 GitHub Release 安装与桌面壳完全同版本的 Culvia wheel，第三方依赖仍由 pip 解析。因此 publish job 必须把对应的 `culvia-<version>-py3-none-any.whl` 与所有 Lite 桌面资产放进同一份 Release 草稿。source job 会把该 wheel 的 `desktop-runtime` extra 及全部解析依赖安装到全新 virtualenv，再检查服务版本、桌面壳 runtime contract、必需模块和 extra 依赖；这条自动门禁通过前不得发布 Release。

独立的 Lite runtime 矩阵会在 macOS arm64/x64、Windows x64、Linux x64 下载同次运行的桌面包及 wheel。每个包都必须由桌面程序自行创建全新 virtualenv、完成前端启动和合成照片工作流、核实已安装 wheel 的版本、位置及来源，再在禁止安装的条件下成功重启。检查使用隔离工作目录和运行时配置。全部 Lite 检查通过后才允许发布；发布时还会将各 `.lite-runtime.json` 中包和 wheel 的 SHA-256 与实际资产比对。构建成功或 source job 的 wheel 检查不能单独证明 Lite 桌面可启动；候选 wheel override 也不验证最终公开下载地址。

需要手动验证时，可以在 GitHub Actions 手动运行同一 workflow，并关闭 `publish_release`。手动运行默认选择 `platform=all` 和 `profile=release`；未发布时可收窄任一输入。打开 `publish_release` 时必须设置 `upload_artifacts=true`，保持 `platform=all` 和 `profile=release`，并且从 tag ref 运行或传入已存在的 `release_tag`；不完整的发布矩阵会被 workflow 拒绝。

默认 macOS CI 线使用普通非严格 app/dmg 发布路径，因此可能产出 ad-hoc 或 Apple Development 签名的包。Developer ID 签名、公证和严格 Gatekeeper 验证仍由发布负责人显式执行。

下载发布资产后，可以用下面命令验证来源：

```bash
gh attestation verify <downloaded-asset> --repo yangzhg/culvia
```

## Desktop readiness

推荐的本地统一入口：

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

桌面壳使用 `desktop/tauri/desktop-shell.contract.json` 中声明的 local-http frontend contract，健康检查路径是 `/health`，主入口是 `culvia-supervisor`。占位 backend 用于编译检查；发布构建使用真实 backend。

验证 Desktop Lite 时，使用一次性的 `CULVIA_RUNTIME_VENV`，运行 `python -m culvia.runtime_manager ensure --json --editable-source <repo>`。此命令可能安装依赖，需要显式运行。

## Backend 运行时检查

```bash
python3 desktop/tauri/scripts/build-backend.py --check-plan --json
python3 desktop/tauri/scripts/build-backend.py --ensure-placeholder --json
python3 desktop/tauri/scripts/build-backend.py --build --json
python tools/check_backend_smoke.py --binary <backend> --timeout 90 --json
python tools/check_backend_workflow_smoke.py --binary <backend> --timeout 120 --json
```

`tools/check_backend_smoke.py` 验证 ready event、`/health` 和进程退出清理。`tools/check_backend_workflow_smoke.py` 使用合成 fixture 验证选片、筛选、导出预检、导出入选、curation history 和非密钥 LLM 配置写入。

## macOS

推荐的本地 macOS app/dmg 入口：

```bash
make macos-release-plan
make macos-release
make macos-lite-release-plan
make macos-lite-release
```

默认本地 app/dmg 构建可以使用 ad-hoc 或 Apple Development 签名，不会因为缺少 Developer ID 或公证而阻塞。已配置 Developer ID 签名、公证和 Gatekeeper 验证后，再运行严格发布线：

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

产物预检检查已构建的 `.app` / `.dmg`。本机 ad-hoc 或 Apple Development 签名不等同于 Developer ID 签名或公证。

macOS 发布入口会把最终产物放到 `dist/macos/`；`desktop/tauri/src-tauri/target/` 只是中间构建目录。

## Windows/Linux 绿色包

Windows：

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

Linux：

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

Full 包必须自包含 Python runtime 和 web data，不要求用户安装系统 Python。Lite 包有意不内置 backend 和 web data，默认使用应用自己管理的 virtualenv runtime，并在首次启动时需要 Python 3.11+。`tools/check_portable_package_preflight.py` 验证压缩包结构、路径安全、manifest、可执行文件类型和 forbidden runtime artifacts。`tools/check_portable_package_runtime.py` 必须在目标 OS runner 上验证 full 包 launcher、bundled backend 和 fixture workflow。

## 发布证据

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

`.github/workflows/desktop-release.yml` 中的桌面构建任务只上传已验证的最终包、`.sha256` 和 `.evidence.json`。不得上传 `dist/**`、`target/**`、backend binary 目录、运行时缓存、用户数据或凭据。

Lite 启动检查另外为每个目标上传一份 `<package>.lite-runtime.json`，失败时也会尽可能保留诊断结果。失败或不完整的运行证据不得发布。Full 包的运行检查保持不变。

校验和文件在所有构建平台上均使用 UTF-8 编码和 LF 换行。将下载的发布包与对应的 `.sha256` 文件放在同一目录，然后在该目录运行：

```bash
shasum -a 256 -c <artifact>.sha256  # macOS
sha256sum -c <artifact>.sha256      # Linux
```

## Keychain 运行时检查

```bash
python -m pip install -e '.[desktop]'
python tools/check_secret_store_keychain_smoke.py --allow-write --preserve-existing --json
python tools/release_status_report.py --json --keychain-smoke
```

该检查必须在真实桌面用户会话中显式运行。它会临时写入随机哨兵、验证读取/删除，并在 `--preserve-existing` 下恢复原 key。
