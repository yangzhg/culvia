from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

from culvia.app_state import AppStateStore
from culvia.score_view import CurrentScoreView


@dataclass(frozen=True)
class StatePayloadDependencies:
    app_name: str
    app_subtitle: str
    heif_available: bool
    sort_fields: Sequence[str]
    sort_field_labels: Mapping[str, str]
    model_agreement_options: Sequence[Mapping[str, Any]]
    manual_status_options: Sequence[Mapping[str, Any]]
    color_label_options: Sequence[Mapping[str, Any]]
    weight_presets: Mapping[str, Mapping[str, Any]]
    score_labels: Mapping[str, str]
    technical_labels: Mapping[str, str]
    model_quality_labels: Mapping[str, str]
    aesthetic_reference_labels: Mapping[str, str]
    llm_review_labels: Mapping[str, str]
    current_score_view: Callable[..., CurrentScoreView]
    frame_file_ids: Callable[[pd.DataFrame], list[str]]
    load_photo_marks: Callable[[str, Sequence[str]], Mapping[str, Any]]
    dataframe_for_display: Callable[
        [pd.DataFrame, Mapping[str, Any], Mapping[str, Any]], tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]
    ]
    selected_preview_for_display: Callable[..., pd.DataFrame]
    load_analysis_insights: Callable[..., Iterable[Any]]
    llm_review_score_columns: Sequence[str]
    serialize_photo: Callable[[pd.Series, Mapping[str, Any], Mapping[str, Any]], dict[str, Any]]
    curation_summary: Callable[[Mapping[str, Any], Sequence[str]], dict[str, Any]]
    application_info: Callable[[], Mapping[str, Any]]
    local_capabilities: Callable[[], Mapping[str, Any]]
    device_text: Callable[[], Mapping[str, Any]]
    network_payload: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    llm_config_payload: Callable[[], Mapping[str, Any]]
    normalize_selected_models: Callable[[Any], Sequence[str]]
    model_payload: Callable[[Mapping[str, Any], Sequence[str]], Mapping[str, Any]]
    maintenance_model_payload: Callable[[Mapping[str, Any], Sequence[str]], Mapping[str, Any]]
    summarize_scores: Callable[[pd.DataFrame, pd.DataFrame, pd.DataFrame, Mapping[str, Any]], Mapping[str, Any]]


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _export_selection_key(source_df: pd.DataFrame, marks: Mapping[str, Any]) -> str:
    selected_ids = {str(file_id) for file_id, mark in marks.items() if mark.status == "pick"}
    paths = source_df.reindex(columns=["file_id", "path"]).fillna("").astype(str)
    selected = sorted(
        (file_id, path) for file_id, path in paths.itertuples(index=False, name=None) if file_id in selected_ids
    )
    return hashlib.sha256(json.dumps(selected, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def build_state_payload(state_store: AppStateStore, deps: StatePayloadDependencies) -> dict[str, Any]:
    with state_store.lock:
        state = state_store.data
        source_df = state["scores_df"].copy()
        filters = dict(state["filters"])
        source = _json_clone(state["source"])
        source_preview = _json_clone(state.get("sourcePreview") or {})
        network = dict(state["network"])
        models = _json_clone(state["models"])
        job = _json_clone(state["job"])

    maintenance_running = bool(job.get("running")) and str(job.get("kind") or "") == "maintenance"
    cache_path = str(source.get("cachePath") or "")
    score_view = deps.current_score_view(
        source_df,
        cache_path,
        allow_persistent_cache=not maintenance_running,
    )
    source_df = score_view.dataframe
    source_file_ids = deps.frame_file_ids(source_df)
    mark_by_file_id: Mapping[str, Any] = (
        deps.load_photo_marks(cache_path, source_file_ids) if cache_path and not maintenance_running else {}
    )
    working, filtered, errors = deps.dataframe_for_display(source_df, filters, mark_by_file_id)
    display_limit = max(int(filters.get("limit", 80) or 80), 1)
    displayed = filtered.head(display_limit)
    filtered_file_ids = deps.frame_file_ids(filtered)
    displayed_file_ids = deps.frame_file_ids(displayed)
    selected_preview = deps.selected_preview_for_display(working, mark_by_file_id, limit=80)
    selected_preview_file_ids = deps.frame_file_ids(selected_preview)
    visible_file_ids = list(dict.fromkeys([*displayed_file_ids, *selected_preview_file_ids]))
    insight_by_file_id = score_view.load_current_insights(visible_file_ids, deps.load_analysis_insights)
    photos = [deps.serialize_photo(row, insight_by_file_id, mark_by_file_id) for _, row in displayed.iterrows()]
    selected_photos = [
        deps.serialize_photo(row, insight_by_file_id, mark_by_file_id) for _, row in selected_preview.iterrows()
    ]
    all_curation = deps.curation_summary(mark_by_file_id, source_file_ids)
    filtered_curation = deps.curation_summary(mark_by_file_id, filtered_file_ids)
    displayed_curation = deps.curation_summary(mark_by_file_id, displayed_file_ids)
    filtered_llm_reviewed_count = 0
    if deps.llm_review_score_columns:
        overall_llm_column = deps.llm_review_score_columns[0]
        if overall_llm_column in filtered:
            filtered_llm_reviewed_count = int(
                pd.to_numeric(filtered[overall_llm_column], errors="coerce").notna().sum()
            )
    summary = dict(deps.summarize_scores(source_df, filtered, errors, filters))
    summary["total"] = int(len(source_file_ids))
    summary["matched"] = int(len(filtered))
    summary["showing"] = int(len(displayed))
    app_payload = {
        "name": deps.app_name,
        "subtitle": deps.app_subtitle,
        "deviceText": dict(deps.device_text()),
        "heifAvailable": deps.heif_available,
    }
    app_payload.update(deps.application_info())
    model_payload = dict(
        (deps.maintenance_model_payload if maintenance_running else deps.model_payload)(
            network,
            deps.normalize_selected_models(models.get("selected")),
        )
    )
    model_options = []
    for raw_option in model_payload.get("options") or []:
        option = dict(raw_option)
        cache_summary = score_view.local_summary.get(str(option.get("key") or ""))
        if cache_summary is not None:
            option["scoreCache"] = {
                **cache_summary,
                "needsRescore": sum(cache_summary[state] for state in ("legacy", "stale", "incomplete")),
            }
        model_options.append(option)
    if "options" in model_payload:
        model_payload["options"] = model_options
    return {
        "app": app_payload,
        "capabilities": deps.local_capabilities(),
        "source": source,
        "sourcePreview": source_preview,
        "filters": filters,
        "sortOptions": [{"value": key, "label": deps.sort_field_labels[key]} for key in deps.sort_fields],
        "modelAgreementOptions": list(deps.model_agreement_options),
        "manualStatusOptions": list(deps.manual_status_options),
        "colorLabelOptions": list(deps.color_label_options),
        "weightPresets": [{"value": key, "label": str(config["label"])} for key, config in deps.weight_presets.items()],
        "scoreLabels": deps.score_labels,
        "technicalLabels": deps.technical_labels,
        "modelQualityLabels": deps.model_quality_labels,
        "aestheticReferenceLabels": deps.aesthetic_reference_labels,
        "llmReviewLabels": deps.llm_review_labels,
        "network": deps.network_payload(network),
        "llm": deps.llm_config_payload(),
        "models": models,
        "model": model_payload,
        "scoreProvenance": {"summary": score_view.local_summary},
        "job": job,
        "summary": summary,
        "curation": {
            "all": all_curation,
            "filtered": filtered_curation,
            "visible": displayed_curation,
            "filteredLlmReviewedCount": filtered_llm_reviewed_count,
            "selectedPreviewCount": int(len(selected_photos)),
            "exportSelectionKey": _export_selection_key(source_df, mark_by_file_id),
        },
        "photos": photos,
        "selectedPhotos": selected_photos,
        "errors": int(len(errors)),
    }
