# 发布检查清单

英文版：[../../en/developer/release-checklist.md](../../en/developer/release-checklist.md)

这份清单用于开源发布、桌面打包或提交较大改动前的最后检查。它只保留可复现、长期有价值的检查：单元测试、语法检查、隐私扫描、pip 分发、桌面 backend、最终包结构和发布证据。

## 基础检查

推荐的本地统一入口：

```bash
make pre-commit
make test
make js-check
make lint
make gate
```

等价底层命令：

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

聚合 gate：

```bash
python tools/formal_gate.py
python tools/formal_gate.py --skip-release-smoke
python tools/formal_gate.py --build-sdist
python tools/formal_gate.py --sdist-artifact dist/python/culvia-0.1.0.tar.gz
```

前端改动至少运行：

```bash
find web -name '*.js' -print0 | xargs -0 -n1 node --check
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

推送 `v<version>` tag 会触发 `.github/workflows/desktop-release.yml`。Tag workflow 会构建 full macOS arm64、macOS x64、Windows x64、Linux x64 桌面包，构建 Python wheel 和源码包，为发布资产生成 GitHub Artifact Attestations，上传已验证的 workflow artifacts，并创建或更新同名 GitHub Release。

需要手动验证时，可以在 GitHub Actions 手动运行同一 workflow，并关闭 `publish_release`。手动运行可收窄 `platform` 和 `profile`；打开 `publish_release` 时必须从 tag ref 运行，或传入已存在的 `release_tag`。

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
python tools/formal_gate.py --strict-desktop
```

`--strict-desktop` 会运行 Desktop release preflight、backend placeholder、`cargo check`、`cargo test`、`tauri:info` 和 backend plan。桌面壳必须继续使用 `desktop/tauri/desktop-shell.contract.json` 中声明的 local-http frontend contract，健康检查路径是 `/health`，主入口是 `culvia-supervisor`。

验证 Desktop Lite 时，应使用一次性的 `CULVIA_RUNTIME_VENV`，运行 `python -m culvia.runtime_manager ensure --json --editable-source <repo>`。这不会放入默认 gate，因为它可能安装依赖。

## Backend 运行时检查

```bash
python3 desktop/tauri/scripts/build-backend.py --check-plan --json
python3 desktop/tauri/scripts/build-backend.py --ensure-placeholder --json
python3 desktop/tauri/scripts/build-backend.py --build --json
python tools/check_backend_smoke.py --binary <backend> --timeout 90 --json
python tools/check_backend_workflow_smoke.py --binary <backend> --timeout 120 --json
python tools/formal_gate.py --strict-desktop --backend-smoke --backend-binary <backend>
python tools/formal_gate.py --strict-desktop --backend-workflow-smoke --backend-binary <backend>
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
python tools/formal_gate.py --macos-artifacts --skip-release-smoke
python tools/formal_gate.py --macos-artifacts --strict-macos-artifacts --macos-app-launch-smoke --skip-release-smoke
```

`--macos-artifacts` 只检查已构建 `.app` / `.dmg`。不要把本机 ad-hoc 或 Apple Development 签名误认为 Developer ID/公证发布签名。

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
python tools/check_portable_package_preflight.py --windows-zip dist/windows/culvia-0.1.0-windows-x86_64-pc-windows-msvc.zip --json
python tools/check_portable_package_preflight.py --windows-lite-zip dist/windows-lite/culvia-0.1.0-windows-lite-x86_64-pc-windows-msvc.zip --json
python tools/check_portable_package_runtime.py --windows-zip dist/windows/culvia-0.1.0-windows-x86_64-pc-windows-msvc.zip --exit-after-ms 20000 --json
python tools/formal_gate.py --windows-zip-artifact dist/windows/culvia-0.1.0-windows-x86_64-pc-windows-msvc.zip --skip-release-smoke
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
python tools/check_portable_package_preflight.py --linux-tgz dist/linux/culvia-0.1.0-linux-x86_64-unknown-linux-gnu.tar.gz --json
python tools/check_portable_package_preflight.py --linux-lite-tgz dist/linux-lite/culvia-0.1.0-linux-lite-x86_64-unknown-linux-gnu.tar.gz --json
python tools/check_portable_package_runtime.py --linux-tgz dist/linux/culvia-0.1.0-linux-x86_64-unknown-linux-gnu.tar.gz --exit-after-ms 20000 --json
python tools/formal_gate.py --linux-tgz-artifact dist/linux/culvia-0.1.0-linux-x86_64-unknown-linux-gnu.tar.gz --skip-release-smoke
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

`.github/workflows/desktop-release.yml` 只上传已验证的最终包、`.sha256` 和 `.evidence.json`。不得上传 `dist/**`、`target/**`、backend binary 目录、运行时缓存、用户数据或凭据。

## Keychain 运行时检查

```bash
python -m pip install -e '.[desktop]'
python tools/check_secret_store_keychain_smoke.py --allow-write --preserve-existing --json
python tools/release_status_report.py --json --keychain-smoke
```

该检查必须在真实桌面用户会话中显式运行。它会临时写入随机哨兵、验证读取/删除，并在 `--preserve-existing` 下恢复原 key。
