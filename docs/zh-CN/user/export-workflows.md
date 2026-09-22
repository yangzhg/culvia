# 导出工作流

英文版：[../../en/user/export-workflows.md](../../en/user/export-workflows.md)

Culvia 的导出目标不是替代 Lightroom Classic、Capture One 或其他 DAM，而是把本地模型初筛、人工复核和大模型意见整理成可以继续交付的结构化结果。

## 筛选范围与展示上限

筛选面板中的“最多显示”（`filters.limit`）只限制界面展示多少张匹配照片，不会缩小真实的筛选结果范围。

- 批量作用域显示“全部筛选结果”时，状态、色标、综合模型采纳和大模型采纳都会作用于符合当前筛选条件的全部照片，包括展示上限之外的照片。
- 采纳综合模型或大模型结果时，7.0 分及以上标为“入选”，低于 5.5 分标为“淘汰”，中间区间标为“待复核”；0–10 分到星级采用常规四舍五入。
- “选择已展示”只会把当前界面中展示的照片加入显式选择。存在显式选择后，批量操作只作用于这些已选照片。
- “筛选结果 CSV”（`/api/export`）包含全部匹配照片，不只包含当前展示的前若干张；“入选结果 CSV”和复制入选照片仍以入选标记为准。

界面会用“匹配 / 展示”同时呈现两个数量，让用户在执行批量操作前看清实际影响范围。例如 `620 / 80` 表示筛选条件匹配 620 张，当前界面展示 80 张。

## CSV 字段

导出的 CSV 会保留原始评分明细，同时增加人工选片字段：

| 字段 | 含义 |
|---|---|
| `manual_rating` | 人工星级，0-5 |
| `manual_status` | 内部状态：`pick`、`hold`、`reject` 或空 |
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

页面通过 `/api/state` 中的 `curation.exportSelectionKey` 跟踪完整入选集合，包括 80 张预览之外的入选照片。修改展示上限、排序或筛选条件，不会改变实际复制的入选集合。预检只反映检查时的状态；开始复制时会重新读取入选标记并检查文件。

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

### 复制安全与进度

- 以独占方式创建文件。已有文件和符号链接都会触发自动改名，包括预检后被其他进程占用的文件名。
- 复制失败时，Culvia 会先确认目标仍是本次创建的文件，再尝试清理不完整的输出；不会清理已被其他进程替换的文件。
- 复制期间，任务栏明确显示正在导出及已处理的文件数，导出按钮阻止重复点击。修改目标目录及其他冲突写入仍被拦截，后端可以继续响应状态查询和浏览请求。
- 后端仍运行时，刷新页面不会取消正在进行的复制。导出页会恢复最近一次交付的回执和目标目录，包括进度与已确认的逐文件结果；重启后端后首次打开页面、恢复已保存的筛选条件时也会保留回执。本页手动选择的新目录不会被旧回执覆盖。

导出并非全部成功或全部回滚的事务：部分照片失败时，已成功复制的文件会保留。强制终止程序或掉电可能留下不完整文件，重试前请检查目标目录。

### 交付回执与完整清单

每次导出会在复制前保存唯一的 `operationId` 和完整入选名单。逐文件结果记录原图路径、自动改名后的实际目标，以及复制或失败状态。页面预览最多 20 条，并可下载该批次的完整 CSV 清单；这是实际交付记录，不是“入选结果 CSV”的评分表。

- `/api/state.exportReceipt` 恢复最近一次回执。`sequence` 和 `revision` 用于区分批次及版本，避免迟到的网络响应覆盖较新结果。
- `GET /api/export/receipts/{operationId}` 返回含全部 `entries` 的回执。
- `GET /api/export/receipts/{operationId}/manifest.csv` 下载所有逐文件结果，不受页面预览条数限制。

批次状态为 `running`、`completed`、`failed` 或 `interrupted`。完成表示每张照片都有已确认的处理结果，不代表全部复制成功。后端异常退出后，结果未提交的文件标为 `unconfirmed`，尚未处理的文件标为 `not_attempted`。Culvia 不会根据目标文件存在就推断复制成功，也不会自动重试这些文件。再次导出前请先核查；新的导出会另起一批，使用唯一文件名再复制一份。

回执保存在应用数据目录中的 `culvia_export_receipts.sqlite`，可用 `CULVIA_EXPORT_RECEIPTS_PATH` 指定其他位置。切换来源、清理评分或清理模型不会删除回执。“重置本机数据”会清除回执，但不删除原始照片或已交付文件。回执会保留到重置；需要独立保存时，请下载清单。

## 前端归一化层

Web 前端通过 `web/export_result_data.js` 统一归一化导出结果：

| 模块 | 职责 |
|---|---|
| `CulviaExportResultData` | 接收结构化导出 payload，归一化 `copiedFiles`、`skippedDetails` 和 `skippedReasonSummary` |
| `CulviaExportResult` | 只渲染已经归一化后的导出结果卡片、目录动作和明细折叠区 |

这样做是为了让 Web、本地 App 壳和自动化脚本都能使用同一套导出 payload，同时让渲染层只处理一个清晰的数据形状。

## 建议用法

- 用“采纳当前筛选”把全部匹配照片的模型推荐结果批量转成人工星级和入选状态，包括展示上限之外的照片。
- 只想处理当前展示照片时，先使用“选择已展示”建立显式选择。
- 用色标快捷键或导出页批量色标把照片分成后续动作队列。
- 导出“入选结果 CSV”做交付清单，导出“筛选结果 CSV”保留完整的筛选和评分分析证据。
