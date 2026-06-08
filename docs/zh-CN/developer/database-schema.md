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
| `updated_at` | `REAL` | Unix 时间戳 |

评分字段包含 `culvia.schema` 中定义的本地审美、技术、CLIP 参考、CLIP-IQA 和大模型评审维度。

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
