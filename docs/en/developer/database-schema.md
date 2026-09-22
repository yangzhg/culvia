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
| `llm_review_generation` | `REAL` | Generation shared with the matching LLM insight; stale or partially published review scores are ignored |
| `core_aesthetic_result_version` | `TEXT` | Semantic producer version for the core aesthetic fields |
| `clip_iqa_result_version` | `TEXT` | Semantic producer version for the CLIP-IQA fields |
| `clip_aesthetic_result_version` | `TEXT` | Semantic producer version for the CLIP aesthetic field |
| `updated_at` | `REAL` | Unix timestamp |

Score columns include local aesthetic, technical, CLIP reference, CLIP-IQA, and LLM review dimensions defined in `culvia.schema`.
Existing score tables are extended in place when new cache columns are introduced.
Scoring checkpoints use full-record UPSERTs for only the supplied `file_id`; rows outside the checkpoint are never rewritten from an older in-memory snapshot. Explicit `NULL` values remain meaningful and clear stale model output.

The three local-model result versions bind the capability, pinned repository revision, verified weight digest,
and score-affecting contract. The two CLIP capabilities have independent versions even though they share one runtime.
Their contracts include their actual prompt pairs, so changing only one prompt family invalidates only that capability.

Older rows are not automatically stamped as current. A schema upgrade only adds nullable columns: rows with complete
scores and no result version are `legacy`, while a nonmatching version is `stale`. State, filtering, recommendation,
model acceptance, and CSV exports mask non-current local-model values without deleting the stored historical values.
An explicit scoring run refreshes only selected capabilities for photos in the active source, and successful score
fields and their result version are committed by the same checkpoint.

CSV exports include stored `*_result_version` columns plus derived `*_result_state` columns. Result states are
`current`, `legacy`, `stale`, `incomplete`, or `missing`; derived state columns are not persisted in SQLite.

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

For LLM review, `created_at` is also the result generation stored in `culvia_scores.llm_review_generation`.
The UI and cache reuse a review only when the latest insight identity and generation both match the score row.
After upgrading an older database, rows without a generation are treated as stale and reviewed again. This avoids
binding unrelated per-dimension scores merely because two review generations happened to share the same overall score.
For text-only review, `prompt_version` also includes a digest of the exact current score-context lines sent to the
model. Updating or completing an upstream local score therefore invalidates the old text review in the same scoring
run. Image-mode review does not include local score context and keeps the normal prompt identity.

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

## Delivery receipts

Owner: `culvia.export_receipts.ExportReceiptStore`

Delivery receipts use a separate application-data database, `culvia_export_receipts.sqlite`, configurable through
`CULVIA_EXPORT_RECEIPTS_PATH`. They do not move when the active source score database changes. Keep this path separate
from scoring databases and cache/model directories: conflicting exports or cleanup requests are rejected.

- `export_receipts`: monotonically increasing `sequence`, unique `operation_id`, per-operation `revision`, status,
  destination, `source_json`, timestamps, total count, and structured operation error.
- `export_receipt_files`: one row per selected photo, keyed by `(operation_id, ordinal)`, with `file_id`, source and
  actual target paths, status, reason, message, and timestamps. Deleting an operation cascades to its file rows.

The complete selection is committed before copying. Per-file transitions are committed independently. An OS lock
shared by canonical database identity covers execution, interrupted-operation recovery, and explicit reset; the lock
file is retained. Readers use a single SQLite snapshot. On recovery, unfinished copies become `unconfirmed` and
untouched entries become `not_attempted`; recovery does not retry or modify delivered photos.

`/api/state` includes the latest receipt with up to 20 preview entries. The receipt JSON and CSV endpoints expose the
complete file list by operation ID. Receipts persist until **Reset local data**; clearing scores or model files does
not clear them. Reset deletes receipt rows with SQLite `secure_delete` enabled, but is not a guarantee of erasure from
filesystem snapshots or backups. Photo copying itself is not a power-loss-atomic transaction.
