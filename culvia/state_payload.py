from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from culvia.app_state import AppStateStore
from culvia.cache_schema import SQLITE_CACHE_EXTENSIONS


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
    load_analysis_insights: Callable[..., Iterable[Any]]
    serialize_photo: Callable[[pd.Series, Mapping[str, Any], Mapping[str, Any]], dict[str, Any]]
    curation_summary: Callable[[Mapping[str, Any], Sequence[str]], dict[str, Any]]
    local_capabilities: Callable[[], Mapping[str, Any]]
    device_label: Callable[[], str]
    network_payload: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    llm_config_payload: Callable[[], Mapping[str, Any]]
    normalize_selected_models: Callable[[Any], Sequence[str]]
    model_payload: Callable[[Mapping[str, Any], Sequence[str]], Mapping[str, Any]]
    summarize_scores: Callable[[pd.DataFrame, pd.DataFrame, pd.DataFrame, Mapping[str, Any]], Mapping[str, Any]]


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def build_state_payload(state_store: AppStateStore, deps: StatePayloadDependencies) -> dict[str, Any]:
    with state_store.lock:
        state = state_store.data
        source_df = deps.normalize_score_dataframe(state["scores_df"]).copy()
        filters = dict(state["filters"])
        source = _json_clone(state["source"])
        network = dict(state["network"])
        models = _json_clone(state["models"])
        job = _json_clone(state["job"])

    deps.refresh_persisted_llm_config(str(source.get("cachePath") or deps.default_cache_path))
    cache_path = str(source.get("cachePath") or "")
    source_file_ids_for_marks = deps.frame_file_ids(source_df)
    mark_by_file_id = deps.load_photo_marks(cache_path, source_file_ids_for_marks) if cache_path else {}
    working, filtered, errors = deps.dataframe_for_display(source_df, filters, mark_by_file_id)
    insight_by_file_id: dict[str, Any] = {}
    source_file_ids = deps.frame_file_ids(working)
    filtered_file_ids = deps.frame_file_ids(filtered)
    selected_preview = deps.selected_preview_for_display(working, mark_by_file_id, limit=80)
    selected_preview_file_ids = deps.frame_file_ids(selected_preview)
    insight_file_ids = list(dict.fromkeys([*filtered_file_ids, *selected_preview_file_ids]))
    if cache_path and Path(cache_path).expanduser().suffix.lower() in SQLITE_CACHE_EXTENSIONS:
        for insight in deps.load_analysis_insights(cache_path, file_ids=insight_file_ids):
            if insight.analyzer_key != deps.model_llm_review:
                continue
            previous = insight_by_file_id.get(insight.file_id)
            if previous is None or insight.created_at >= previous.created_at:
                insight_by_file_id[insight.file_id] = insight
    photos = [deps.serialize_photo(row, insight_by_file_id, mark_by_file_id) for _, row in filtered.iterrows()]
    selected_photos = [
        deps.serialize_photo(row, insight_by_file_id, mark_by_file_id) for _, row in selected_preview.iterrows()
    ]
    all_curation = deps.curation_summary(mark_by_file_id, source_file_ids)
    visible_curation = deps.curation_summary(mark_by_file_id, filtered_file_ids)
    return {
        "app": {
            "name": deps.app_name,
            "subtitle": deps.app_subtitle,
            "device": deps.device_label(),
            "heifAvailable": deps.heif_available,
        },
        "capabilities": deps.local_capabilities(),
        "source": source,
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
        "model": deps.model_payload(network, deps.normalize_selected_models(models.get("selected"))),
        "job": job,
        "summary": deps.summarize_scores(source_df, filtered, errors, filters),
        "curation": {
            "all": all_curation,
            "visible": visible_curation,
            "selectedPreviewCount": int(len(selected_photos)),
        },
        "photos": photos,
        "selectedPhotos": selected_photos,
        "errors": int(len(errors)),
    }
