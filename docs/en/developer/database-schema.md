# Database Schema

Simplified Chinese: [../../zh-CN/developer/database-schema.md](../../zh-CN/developer/database-schema.md)

Culvia uses SQLite for scoring results, manual culling data, LLM insights, and non-secret app configuration.

## Cache Path

The default cache path is resolved by `culvia.settings.default_cache_path()` and usually ends with `culvia_scores.sqlite`. Non-SQLite scoring caches are rejected. CSV is export-only.

Manual curation uses the same SQLite file when the scoring cache path is SQLite. For non-SQLite paths, curation data is written to a sibling `*.curation.sqlite` file.

## `culvia_scores`

Owner: `culvia.cache_records.ScoreCacheStore`

Purpose: score records keyed by `file_id`.

Core columns:

| Column | Type | Notes |
|---|---|---|
| `file_id` | `TEXT PRIMARY KEY` | Stable photo identifier/path |
| score columns | `REAL` | Derived from `ScoreFieldGroup.cache_columns` |
| text columns | `TEXT` | File metadata and error fields from `CSV_COLUMNS` |
| `recommendation_0_10` | `REAL` | Combined recommendation score |
| `updated_at` | `REAL` | Unix timestamp |

Score columns include local aesthetic, technical, CLIP reference, CLIP-IQA, and LLM review dimensions defined in `culvia.schema`.

## `photo_analysis_insights`

Owner: `culvia.insight_store.AnalysisInsightStore`

Purpose: long-form analyzer output, currently used by LLM review.

Primary key:

```text
(file_id, analyzer_key, provider, model, model_version, prompt_version)
```

Columns:

| Column | Type |
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

Owner: `culvia.insight_store.AppConfigStore`

Purpose: persisted non-secret LLM configuration. API keys do not belong here.

Columns:

| Column | Type |
|---|---|
| `key` | `TEXT PRIMARY KEY` |
| `value` | `TEXT NOT NULL` |
| `updated_at` | `REAL NOT NULL` |

Stored keys map to fields such as `llm_base_url`, `llm_endpoint`, `llm_model`, `llm_provider`, `llm_input_mode`, `llm_prompt_preset`, and `llm_custom_prompt`.

## `photo_curation_marks`

Owner: `culvia.curation`

Purpose: manual culling decisions.

Columns:

| Column | Type | Notes |
|---|---|---|
| `file_id` | `TEXT PRIMARY KEY` | Photo identifier |
| `manual_rating` | `INTEGER NOT NULL DEFAULT 0` | 0-5 stars |
| `pick_status` | `TEXT NOT NULL DEFAULT ''` | `pick`, `hold`, `reject`, or empty |
| `color_label` | `TEXT NOT NULL DEFAULT ''` | `red`, `yellow`, `green`, `blue`, `purple`, or empty |
| `note` | `TEXT NOT NULL DEFAULT ''` | Manual note |
| `source` | `TEXT NOT NULL DEFAULT 'manual'` | `manual`, `model`, `llm`, `model_batch`, `llm_batch` |
| `accepted_score_0_10` | `REAL` | Accepted model/LLM score |
| `updated_at` | `REAL NOT NULL` | Unix timestamp |

## `photo_curation_actions`

Owner: `culvia.curation_history`

Purpose: undo/audit history for culling actions.

Columns:

| Column | Type |
|---|---|
| `id` | `TEXT PRIMARY KEY` |
| `kind` | `TEXT NOT NULL` |
| `scope` | `TEXT NOT NULL DEFAULT ''` |
| `summary` | `TEXT NOT NULL DEFAULT ''` |
| `payload_json` | `TEXT NOT NULL DEFAULT '{}'` |
| `created_at` | `REAL NOT NULL` |

Payloads are versioned with `schemaVersion`.
