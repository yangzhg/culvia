# 开发环境与运行手册

English: [../../en/developer/getting-started.md](../../en/developer/getting-started.md)

这份文档面向修改 Culvia 代码的开发者。

## 初始化

```bash
make init
```

`make init` 默认创建或更新 `~/.venvs/culvia` 开发环境，并安装 `.[desktop,release,dev]`。需要指定环境路径时：

```bash
CULVIA_VENV=$HOME/.venvs/culvia-dev make init
```

## 启动系统

启动带 supervisor 的 Web 工作台：

```bash
make server
```

直接启动 Web server：

```bash
make web PORT=8501
make web PORT=auto WEB_ARGS=--reload
bin/culvia-web --host 127.0.0.1 --port 8501
```

Windows：

```powershell
scripts/culvia-dev.ps1 web --host 127.0.0.1 --port 8501
bin/culvia-web.ps1 --host 127.0.0.1 --port 8501
```

Command Prompt：

```bat
bin\culvia-web.cmd --host 127.0.0.1 --port 8501
```

运行批量评分 CLI：

```bash
make cli CLI_ARGS="--help"
```

## 开发检查

```bash
make pre-commit-install
make pre-commit
make test
make js-check
make lint
make format
make gate
make desktop-ready
```

`make pre-commit` 是默认本地质量门禁，覆盖 Python 格式/lint、JS 语法、配置文件校验、Shell 语法、Makefile dry-run、Rust 格式以及密钥扫描。底层命令保留在 [发布检查清单](release-checklist.md)，用于 CI 和可复现打包流程。

## 桌面开发

```bash
make desktop-dev
make backend-plan
make backend-placeholder
make windows-release-plan
make linux-release-plan
```

完整桌面打包见 [桌面应用构建](desktop-build.md)。

## 运行时数据

运行时缓存、SQLite 文件、上传文件、导出结果、生成的桌面产物、凭据和本地日志都不是源码。清理常见生成文件：

```bash
make clean
make clean -- --apply
```
