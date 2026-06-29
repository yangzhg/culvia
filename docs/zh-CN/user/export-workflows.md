# 导出工作流

英文版：[../../en/user/export-workflows.md](../../en/user/export-workflows.md)

Culvia 的导出目标不是替代 Lightroom Classic、Capture One 或其他 DAM，而是把本地模型初筛、人工复核和大模型意见整理成可以继续交付的结构化结果。

## CSV 字段

导出的 CSV 会保留原始评分明细，同时增加人工选片字段：

| 字段 | 含义 |
|---|---|
| `manual_rating` | 人工星级，0-5 |
| `manual_status` | 内部状态：`pick`、`reject` 或空 |
| `manual_status_label` | 中文状态：入选、淘汰、待定、未判断 |
| `manual_color_label` | 内部色标：`red`、`yellow`、`green`、`blue`、`purple` 或空 |
| `manual_color_label_text` | 中文色标 |
| `manual_source` | 人工、综合模型、大模型或批量采纳来源 |
| `accepted_score_0_10` | 被采纳的模型分数 |

## Lightroom / Capture One 映射

为了方便继续加工，CSV 还会生成面向专业选片工具的辅助列：

| 字段 | 映射 |
|---|---|
| `lightroom_rating` | 等同 `manual_rating` |
| `lightroom_flag` | `Pick`、`Reject`、`Unflagged` |
| `lightroom_color_label` | `Red`、`Yellow`、`Green`、`Blue`、`Purple` |
| `capture_one_rating` | 等同 `manual_rating` |
| `capture_one_color_tag` | `Red`、`Yellow`、`Green`、`Blue`、`Purple` |

这些列目前作为 CSV 明细和后续导入/脚本映射基础。真正写入 Lightroom XMP、Capture One session/catalog 或 sidecar 文件，是后续照片管理能力的一部分。

## 导出预检结果

页面在选择导出目录和入选照片变化后，会调用 `/api/export/preflight` 检查目标目录、缺失原图和自动改名风险。导出 payload 的版本号来自 `culvia.export_service.EXPORT_PAYLOAD_VERSION`：

| 字段 | 含义 |
|---|---|
| `schemaVersion` | 导出预检 payload 版本，当前为 `1` |
| `destination` | 导出目标目录 |
| `total` | 本次待检查照片数量 |
| `ready` | 可复制数量 |
| `missing` | 缺失原图数量 |
| `renamed` | 复制时会自动改名的数量 |
| `destinationWritable` | 目标目录是否可写 |
| `destinationIssue` | 目标目录不可写时的说明 |
| `missingFiles` | 缺失原图路径，最多返回前 20 条 |
| `renamedFiles` | 自动改名明细，包含 `source` 和 `target`，最多返回前 20 条 |

## 复制入选照片结果

页面上的“导出入选”会调用 `/api/export/selected-files`，把当前人工标记为入选的照片复制到目标目录。返回 payload 使用结构化字段，方便 Web、本地 App 壳和自动化脚本共用；版本号同样来自 `culvia.export_service.EXPORT_PAYLOAD_VERSION`：

| 字段 | 含义 |
|---|---|
| `schemaVersion` | 复制入选照片结果 payload 版本，当前为 `1` |
| `destination` | 导出目标目录 |
| `copied` | 成功复制数量 |
| `skipped` | 未复制数量 |
| `copiedFiles` | 成功复制的目标文件路径，最多返回前 20 条 |
| `skippedDetails` | 未复制明细，包含 `path`、`reason`、`label`、`message` |
| `skippedReasonSummary` | 按原因聚合后的未复制数量，包含 `reason`、`label`、`count` |

当前原因类型：

| reason | label | 含义 |
|---|---|---|
| `missing` | `源文件缺失` | 源文件不存在，或路径不是普通文件 |
| `copy_failed` | `复制失败` | 源文件存在，但复制过程中出现系统错误 |

## 前端归一化层

Web 前端通过 `web/export_result_data.js` 统一归一化导出结果：

| 模块 | 职责 |
|---|---|
| `CulviaExportResultData` | 接收结构化导出 payload，归一化 `copiedFiles`、`skippedDetails` 和 `skippedReasonSummary` |
| `CulviaExportResult` | 只渲染已经归一化后的导出结果卡片、目录动作和明细折叠区 |

这样做是为了让 Web、本地 App 壳和自动化脚本都能使用同一套导出 payload，同时让渲染层只处理一个清晰的数据形状。

## 建议用法

- 用“采纳当前筛选”把模型推荐结果批量转成人工星级和入选状态。
- 用色标快捷键或导出页批量色标把照片分成后续动作队列。
- 导出“入选 CSV”做交付清单，导出“当前 CSV”保留筛选和评分分析证据。
