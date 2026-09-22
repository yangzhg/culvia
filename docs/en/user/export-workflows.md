# Export Workflows

Simplified Chinese: [../../zh-CN/user/export-workflows.md](../../zh-CN/user/export-workflows.md)

Culvia does not try to replace Lightroom Classic, Capture One, or a full DAM. Its export goal is to turn local model-assisted triage, human review, and LLM notes into structured results that can continue through a professional delivery workflow.

## Filter Scope And Display Limit

The filter control **Show up to** (`filters.limit`) only limits how many matching photos the interface displays. It does not reduce the underlying filtered result.

- When the batch scope says **All filtered matches**, status changes, color labels, and model or LLM acceptance apply to every photo that matches the active filters, including photos beyond the display limit.
- Accepting model or LLM results maps scores of 7.0 or higher to **Pick**, scores below 5.5 to **Reject**, and the middle range to **Review**. Star ratings use conventional half-up rounding on the 0–10 score.
- **Select shown** creates an explicit selection from only the photos currently displayed. Once photos are selected, batch actions apply only to that selection.
- **Filtered results CSV** (`/api/export`) includes every matching photo, not only the displayed top results. **Picked results CSV** and selected-photo copying continue to use photos marked as picks.

The interface shows both counts as **Matched / shown** so the impact of a batch action is visible before it runs. For example, `620 / 80` means 620 photos match the filters while 80 are currently displayed.

## CSV Fields

The exported CSV keeps the original scoring details and adds manual culling fields:

| Field | Meaning |
|---|---|
| `manual_rating` | Manual star rating, 0-5 |
| `manual_status` | Internal status: `pick`, `hold`, `reject`, or empty |
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

The page tracks the complete picked set through `/api/state`'s `curation.exportSelectionKey`, including picks beyond the 80-photo preview. Changing the display limit, sort order, or filters does not change which picked photos are copied. Preflight is a snapshot; copying checks the current picks and filesystem again.

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

### Copy Safety And Progress

- Files are created exclusively. Existing files and symbolic links cause automatic renaming, including names taken by another process after preflight.
- If a copy fails, Culvia attempts to remove its incomplete output after checking that the destination still refers to the file it created. Files replaced by another process are left alone.
- During copying, the task bar identifies the export and shows how many files have been processed. The export button prevents duplicate clicks. Destination changes and conflicting writes remain blocked, while the backend can still answer state and browsing requests.
- Refreshing does not cancel an active copy while the backend remains alive. The export page restores the latest delivery receipt and its destination, including progress and confirmed per-file results. This also works on the first page load after restarting the backend when saved filters are restored. A destination chosen manually in the current page is not replaced by an older receipt.

This is not an all-or-nothing delivery transaction: successful files remain when other files fail. Forced termination or power loss can leave incomplete files; inspect the destination before retrying.

### Delivery Receipts And Complete Manifests

Each export saves a unique `operationId` and the complete picked-file list before copying. Per-file results record the original path, actual target after automatic renaming, and copy or failure status. The page shows up to 20 entries and offers a complete CSV manifest for that operation; this is a delivery record, not the picked-results scoring CSV.

- `/api/state.exportReceipt` restores the latest receipt. Its `sequence` and `revision` order updates without relying on network response arrival order.
- `GET /api/export/receipts/{operationId}` returns all `entries`.
- `GET /api/export/receipts/{operationId}/manifest.csv` downloads every file result, including entries beyond the page preview.

An operation is `running`, `completed`, `failed`, or `interrupted`. Completed means every file has a confirmed result, not that every file copied successfully. After an interrupted backend run, files whose results were not committed are `unconfirmed`; files not reached are `not_attempted`. Culvia neither infers success from a file's presence nor automatically retries these files. Inspect them before starting another export, which creates a separate set of uniquely named copies.

Receipts stay in `culvia_export_receipts.sqlite` in the application data directory; `CULVIA_EXPORT_RECEIPTS_PATH` can override that location. They survive source changes and score/model-cache clearing. **Reset local data** clears receipts but does not delete original photos or delivered files. Receipts are retained until reset; download a manifest to keep an independent record.

## Frontend Normalization

The Web frontend normalizes export results through `web/export_result_data.js`:

| Module | Responsibility |
|---|---|
| `CulviaExportResultData` | Accepts structured export payloads and normalizes `copiedFiles`, `skippedDetails`, and `skippedReasonSummary` |
| `CulviaExportResult` | Renders normalized export result cards, folder actions, and expandable details |

This keeps Web, local app shell, and automation scripts on the same export payload while keeping the rendering layer focused on one clear data shape.

## Recommended Usage

- Use "accept current filter" to turn model recommendations into manual ratings and pick status for all matching photos, including matches beyond the display limit.
- Use "select shown" first when a batch action should affect only the photos currently displayed.
- Use color-label shortcuts or export-page batch labels to split photos into downstream action queues.
- Export picked-results CSV files for delivery manifests, and export filtered-results CSV files to preserve complete filter and scoring evidence.
