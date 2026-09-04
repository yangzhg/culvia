from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from culvia.app_state import AppStateStore
from culvia.cache_schema import SQLITE_CACHE_EXTENSIONS
from culvia.insight_store import AnalysisInsightMatch
from culvia.llm_provenance import resolve_llm_score_dataframe


@dataclass(frozen=True)
class StatePayloadDependencies:
    app_name: str
    app_subtitle: str
    default_cache_path: str | Path
    heif_available: bool
    model_llm_review: str
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
    normalize_score_dataframe: Callable[[Any], pd.DataFrame]
    refresh_persisted_llm_config: Callable[[str], None]
    frame_file_ids: Callable[[pd.DataFrame], list[str]]
    load_photo_marks: Callable[[str, Sequence[str]], Mapping[str, Any]]
    dataframe_for_display: Callable[
        [pd.DataFrame, Mapping[str, Any], Mapping[str, Any]], tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]
    ]
    selected_preview_for_display: Callable[..., pd.DataFrame]
    load_latest_matching_analysis_insight_results: Callable[..., Mapping[str, AnalysisInsightMatch]]
    load_analysis_insights: Callable[..., Iterable[Any]]
    llm_review_score_columns: Sequence[str]
    llm_review_generation_column: str
    llm_review_provider: Callable[[], str]
    llm_review_model_name: Callable[[], str]
    llm_review_prompt_version: Callable[[], str]
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


def build_state_payload(state_store: AppStateStore, deps: StatePayloadDependencies) -> dict[str, Any]:
    with state_store.lock:
        state = state_store.data
        source_df = deps.normalize_score_dataframe(state["scores_df"]).copy()
        filters = dict(state["filters"])
        source = _json_clone(state["source"])
        source_preview = _json_clone(state.get("sourcePreview") or {})
        network = dict(state["network"])
        models = _json_clone(state["models"])
        job = _json_clone(state["job"])

    maintenance_running = bool(job.get("running")) and str(job.get("kind") or "") == "maintenance"
    if not maintenance_running:
        deps.refresh_persisted_llm_config(str(source.get("cachePath") or deps.default_cache_path))
    cache_path = str(source.get("cachePath") or "")
    source_file_ids = deps.frame_file_ids(source_df)
    current_llm_provider = deps.llm_review_provider()
    current_llm_model = deps.llm_review_model_name()
    current_llm_prompt_version = deps.llm_review_prompt_version()
    is_sqlite_cache = bool(
        not maintenance_running
        and cache_path
        and Path(cache_path).expanduser().suffix.lower() in SQLITE_CACHE_EXTENSIONS
    )
    current_llm_results: dict[str, AnalysisInsightMatch] = {}
    if is_sqlite_cache:
        current_llm_results = dict(
            deps.load_latest_matching_analysis_insight_results(
                cache_path,
                file_ids=source_file_ids,
                analyzer_key=deps.model_llm_review,
                provider=current_llm_provider,
                model=current_llm_model,
                model_version=current_llm_model,
                prompt_version=current_llm_prompt_version,
            )
        )
    resolution = resolve_llm_score_dataframe(
        source_df,
        generation_column=deps.llm_review_generation_column,
        matches=current_llm_results,
        score_columns=deps.llm_review_score_columns,
    )
    current_llm_file_ids = resolution.current_file_ids
    display_source_df = resolution.dataframe
    mark_by_file_id: Mapping[str, Any] = (
        deps.load_photo_marks(cache_path, source_file_ids) if cache_path and not maintenance_running else {}
    )
    working, filtered, errors = deps.dataframe_for_display(display_source_df, filters, mark_by_file_id)
    display_limit = max(int(filters.get("limit", 80) or 80), 1)
    displayed = filtered.head(display_limit)
    filtered_file_ids = deps.frame_file_ids(filtered)
    displayed_file_ids = deps.frame_file_ids(displayed)
    selected_preview = deps.selected_preview_for_display(working, mark_by_file_id, limit=80)
    selected_preview_file_ids = deps.frame_file_ids(selected_preview)
    visible_file_ids = [
        file_id
        for file_id in dict.fromkeys([*displayed_file_ids, *selected_preview_file_ids])
        if file_id in current_llm_file_ids
    ]
    insight_by_file_id: dict[str, Any] = {}
    if is_sqlite_cache and visible_file_ids:
        for insight in deps.load_analysis_insights(cache_path, file_ids=visible_file_ids):
            if not _is_current_llm_insight(
                insight,
                analyzer_key=deps.model_llm_review,
                provider=current_llm_provider,
                model=current_llm_model,
                prompt_version=current_llm_prompt_version,
            ):
                continue
            match = current_llm_results.get(insight.file_id)
            if match is None or float(insight.created_at) != match.generation:
                continue
            previous = insight_by_file_id.get(insight.file_id)
            if previous is None or insight.created_at >= previous.created_at:
                insight_by_file_id[insight.file_id] = insight
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
    summary = dict(deps.summarize_scores(display_source_df, filtered, errors, filters))
    summary["matched"] = int(len(filtered))
    summary["showing"] = int(len(displayed))
    app_payload = {
        "name": deps.app_name,
        "subtitle": deps.app_subtitle,
        "deviceText": dict(deps.device_text()),
        "heifAvailable": deps.heif_available,
    }
    app_payload.update(deps.application_info())
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
        "model": (deps.maintenance_model_payload if maintenance_running else deps.model_payload)(
            network,
            deps.normalize_selected_models(models.get("selected")),
        ),
        "job": job,
        "summary": summary,
        "curation": {
            "all": all_curation,
            "filtered": filtered_curation,
            "visible": displayed_curation,
            "filteredLlmReviewedCount": filtered_llm_reviewed_count,
            "selectedPreviewCount": int(len(selected_photos)),
        },
        "photos": photos,
        "selectedPhotos": selected_photos,
        "errors": int(len(errors)),
    }


def _is_current_llm_insight(
    insight: Any,
    *,
    analyzer_key: str,
    provider: str,
    model: str,
    prompt_version: str,
) -> bool:
    return (
        insight.analyzer_key == analyzer_key
        and insight.provider == provider
        and insight.model == model
        and insight.model_version == model
        and insight.prompt_version == prompt_version
    )
