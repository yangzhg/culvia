# 数据库表结构

English: [../../en/developer/database-schema.md](../../en/developer/database-schema.md)

Culvia 使用 SQLite 保存评分结果、人工选片数据、大模型 insight 和非密钥应用配置。

## 缓存路径

默认缓存路径由 `culvia.settings.default_cache_path()` 决定，通常以 `culvia_scores.sqlite` 结尾。评分缓存只接受 SQLite；CSV 仅用于导出。

当评分缓存路径是 SQLite 时，人工选片数据使用同一个 SQLite 文件。非 SQLite 路径会写入相邻的 `*.curation.sqlite` 文件。

## `culvia_scores`

负责人：`culvia.cache_records.ScoreCacheStore`

用途：以 `file_id` 为主键保存评分记录。

核心字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `file_id` | `TEXT PRIMARY KEY` | 稳定照片标识/路径 |
| score columns | `REAL` | 由 `ScoreFieldGroup.cache_columns` 生成 |
| text columns | `TEXT` | `CSV_COLUMNS` 中的文件元数据和错误字段 |
| `recommendation_0_10` | `REAL` | 综合推荐分 |
| `llm_review_generation` | `REAL` | 与对应大模型 insight 共享的结果代次；过期或未完整发布的评审分数会被忽略 |
| `core_aesthetic_result_version` | `TEXT` | 核心审美字段的语义生产版本 |
| `clip_iqa_result_version` | `TEXT` | CLIP-IQA 字段的语义生产版本 |
| `clip_aesthetic_result_version` | `TEXT` | CLIP 审美字段的语义生产版本 |
| `updated_at` | `REAL` | Unix 时间戳 |

评分字段包含 `culvia.schema` 中定义的本地审美、技术、CLIP 参考、CLIP-IQA 和大模型评审维度。
新增缓存字段时，现有评分表会原地扩展。
评分 checkpoint 仅对传入的 `file_id` 执行完整记录 UPSERT，不会用旧的内存快照重写其它行。显式 `NULL` 仍有清除过期模型结果的语义。

三个本地模型结果版本会绑定 capability、固定的仓库 revision、已校验的权重摘要和影响评分语义的契约。
两个 CLIP capability 即使共享同一运行时，也各自拥有独立版本；契约直接包含实际 prompt pairs，因此只修改
其中一组提示词时，只会让对应 capability 失效。

旧行不会被自动标记为当前。升级 schema 只增加 nullable 字段：分数完整但没有结果版本的行属于
`legacy`，版本不匹配的行属于 `stale`。状态、筛选、推荐、模型采纳和 CSV 导出会屏蔽非当前的本地模型值，
但不会删除数据库中的历史原值。只有用户显式启动评分时，才会对当前来源内已选择的 capability 补算；
成功的分数字段与结果版本由同一个 checkpoint 提交。

CSV 会同时导出已存储的 `*_result_version` 字段和派生的 `*_result_state` 字段。状态值包括 `current`、
`legacy`、`stale`、`incomplete` 和 `missing`；派生状态不会写入 SQLite。

## `photo_analysis_insights`

负责人：`culvia.insight_store.AnalysisInsightStore`

用途：保存长文本 analyzer 输出，目前主要用于大模型评审。

联合主键：

```text
(file_id, analyzer_key, provider, model, model_version, prompt_version)
```

字段：

| 字段 | 类型 |
|---|---|
| `file_id` | `TEXT NOT NULL` |
| `analyzer_key` | `TEXT NOT NULL` |
| `provider` | `TEXT NOT NULL` |
| `model` | `TEXT NOT NULL` |
| `model_version` | `TEXT NOT NULL` |
| `prompt_version` | `TEXT NOT NULL` |
| `score` | `REAL` |
| `confidence` | `REAL` |
| `title` | `TEXT` |
| `summary` | `TEXT` |
| `explanation` | `TEXT` |
| `suggestions_json` | `TEXT` |
| `raw_json` | `TEXT` |
| `created_at` | `REAL` |

对大模型评审而言，`created_at` 同时也是写入 `culvia_scores.llm_review_generation` 的结果代次。
只有最新 insight 的身份与代次都和评分行一致时，界面与缓存才会复用这次评审。
旧数据库升级后，缺少代次的评分行会视为过期并重新评审，避免因为两次评审碰巧总分相同，
就把不属于同一代次的各维度分数错误绑定在一起。
纯文本评审的 `prompt_version` 还会包含实际发送给模型的当前评分上下文摘要。本地上游评分更新或补全后，
旧的纯文本评审会在同一次评分任务中失效并重算。图片模式不使用本地评分上下文，继续沿用普通 prompt 身份。

## `photo_app_config`

负责人：`culvia.insight_store.AppConfigStore`

用途：保存非密钥大模型配置。API key 不应写入该表。

字段：

| 字段 | 类型 |
|---|---|
| `key` | `TEXT PRIMARY KEY` |
| `value` | `TEXT NOT NULL` |
| `updated_at` | `REAL NOT NULL` |

存储 key 会映射到 `llm_base_url`、`llm_endpoint`、`llm_model`、`llm_provider`、`llm_input_mode`、`llm_prompt_preset`、`llm_custom_prompt` 等字段。

## `photo_curation_marks`

负责人：`culvia.curation`

用途：保存人工选片判断。

字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `file_id` | `TEXT PRIMARY KEY` | 照片标识 |
| `manual_rating` | `INTEGER NOT NULL DEFAULT 0` | 0-5 星 |
| `pick_status` | `TEXT NOT NULL DEFAULT ''` | `pick`、`hold`、`reject` 或空 |
| `color_label` | `TEXT NOT NULL DEFAULT ''` | `red`、`yellow`、`green`、`blue`、`purple` 或空 |
| `note` | `TEXT NOT NULL DEFAULT ''` | 人工备注 |
| `source` | `TEXT NOT NULL DEFAULT 'manual'` | `manual`、`model`、`llm`、`model_batch`、`llm_batch` |
| `accepted_score_0_10` | `REAL` | 被采纳的模型/大模型分数 |
| `updated_at` | `REAL NOT NULL` | Unix 时间戳 |

## `photo_curation_actions`

负责人：`culvia.curation_history`

用途：保存选片操作的撤销/审计历史。

字段：

| 字段 | 类型 |
|---|---|
| `id` | `TEXT PRIMARY KEY` |
| `kind` | `TEXT NOT NULL` |
| `scope` | `TEXT NOT NULL DEFAULT ''` |
| `summary` | `TEXT NOT NULL DEFAULT ''` |
| `payload_json` | `TEXT NOT NULL DEFAULT '{}'` |
| `created_at` | `REAL NOT NULL` |

Payload 使用 `schemaVersion` 做版本标记。
