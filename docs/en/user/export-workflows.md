# Export Workflows

Simplified Chinese: [../../zh-CN/user/export-workflows.md](../../zh-CN/user/export-workflows.md)

Culvia does not try to replace Lightroom Classic, Capture One, or a full DAM. Its export goal is to turn local model-assisted triage, human review, and LLM notes into structured results that can continue through a professional delivery workflow.

## CSV Fields

The exported CSV keeps the original scoring details and adds manual culling fields:

| Field | Meaning |
|---|---|
| `manual_rating` | Manual star rating, 0-5 |
| `manual_status` | Internal status: `pick`, `reject`, or empty |
| `manual_status_label` | Localized status label |
| `manual_color_label` | Internal color label: `red`, `yellow`, `green`, `blue`, `purple`, or empty |
| `manual_color_label_text` | Localized color label |
| `manual_source` | Manual, combined model, LLM, or batch acceptance source |
| `accepted_score_0_10` | Accepted model score |

## Lightroom / Capture One Mapping

For downstream processing, the CSV also includes helper columns that map to professional culling tools:

| Field | Mapping |
|---|---|
| `lightroom_rating` | Same as `manual_rating` |
| `lightroom_flag` | `Pick`, `Reject`, `Unflagged` |
| `lightroom_color_label` | `Red`, `Yellow`, `Green`, `Blue`, `Purple` |
| `capture_one_rating` | Same as `manual_rating` |
| `capture_one_color_tag` | `Red`, `Yellow`, `Green`, `Blue`, `Purple` |

These columns are currently CSV details and a foundation for later import/script workflows. Writing Lightroom XMP, Capture One sessions/catalogs, or sidecar files belongs to future photo management work.

## Export Preflight Payload

After the export destination or selected photos change, the page calls `/api/export/preflight` to check destination permissions, missing source files, and automatic rename risks. The payload schema version comes from `culvia.export_service.EXPORT_PAYLOAD_VERSION`:

| Field | Meaning |
|---|---|
| `schemaVersion` | Export preflight payload version, currently `1` |
| `destination` | Export destination directory |
| `total` | Number of photos checked |
| `ready` | Number of photos ready to copy |
| `missing` | Number of missing source files |
| `renamed` | Number of files that will be renamed during copy |
| `destinationWritable` | Whether the destination is writable |
| `destinationIssue` | Explanation when the destination is not writable |
| `missingFiles` | Missing source paths, capped to the first 20 items |
| `renamedFiles` | Rename details with `source` and `target`, capped to the first 20 items |

## Selected Photo Copy Result

The "export selected" action calls `/api/export/selected-files` and copies photos currently marked as picked into the destination directory. The response uses structured fields so the Web UI, desktop shell, and automation scripts can share one payload shape. The version also comes from `culvia.export_service.EXPORT_PAYLOAD_VERSION`:

| Field | Meaning |
|---|---|
| `schemaVersion` | Selected-photo copy result payload version, currently `1` |
| `destination` | Export destination directory |
| `copied` | Number of successfully copied files |
| `skipped` | Number of skipped files |
| `copiedFiles` | Copied target paths, capped to the first 20 items |
| `skippedDetails` | Skipped details with `path`, `reason`, `label`, and `message` |
| `skippedReasonSummary` | Skipped counts grouped by reason, with `reason`, `label`, and `count` |

Current reason types:

| reason | label | Meaning |
|---|---|---|
| `missing` | `Source missing` | Source file does not exist or is not a regular file |
| `copy_failed` | `Copy failed` | Source file exists, but the system copy operation failed |

## Frontend Normalization

The Web frontend normalizes export results through `web/export_result_data.js`:

| Module | Responsibility |
|---|---|
| `CulviaExportResultData` | Accepts structured export payloads and normalizes `copiedFiles`, `skippedDetails`, and `skippedReasonSummary` |
| `CulviaExportResult` | Renders normalized export result cards, folder actions, and expandable details |

This keeps Web, local app shell, and automation scripts on the same export payload while keeping the rendering layer focused on one clear data shape.

## Recommended Usage

- Use "accept current filter" to turn model recommendations into manual ratings and pick status in batch.
- Use color-label shortcuts or export-page batch labels to split photos into downstream action queues.
- Export selected CSV files for delivery manifests, and export current CSV files to preserve filter and scoring evidence.
