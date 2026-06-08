# 快速开始

English: [../../en/user/getting-started.md](../../en/user/getting-started.md)

这份文档面向使用 Culvia 的摄影师，不是面向修改代码的开发者。

## 启动应用

从源码仓库启动：

```bash
make init
make server
```

只启动 Web server：

```bash
make web PORT=8501
bin/culvia-web --host 127.0.0.1 --port 8501
```

通过 pip 安装后，使用安装出的 console commands：

```bash
culvia-supervisor
culvia-web --host 127.0.0.1 --port 8501
```

## 基本流程

1. 选择本地照片目录，或上传临时照片。
2. 选择要运行的本地模型，按需启用大模型评审。
3. 开始评分，并查看当前照片和进度。
4. 在选片台或照片墙复核照片。
5. 标记人工判断：入选、待定、淘汰、星级和色标。
6. 导出入选照片或 CSV 结果。

## 人工判断

人工判断是最终选片层。模型和大模型分数用于排序和解释，但不会覆盖你的入选/待定/淘汰判断。

- `入选`：进入交付或后续精修。
- `待定`：需要再复核一轮。
- `淘汰`：排除出最终集合。
- 星级和色标可用于后续 Lightroom/Capture One 风格工作流。

## 大模型评审

大模型评审是可选功能。只有需要图片评价、细维度审美/技术分数、修图建议和拍摄建议时，才需要配置 OpenAI-compatible endpoint 和模型。API key 应通过应用配置/keychain 流程保存，不应写入 Git 或文档。

## 导出

交付候选照片时使用入选照片导出；需要评分证据、人工状态、色标和下游映射时使用 CSV 导出。详见 [导出工作流](export-workflows.md)。
