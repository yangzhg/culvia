from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import requests
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from culvia.api_errors import api_error_response
from culvia.app_state import AppStateStore, create_initial_state, empty_job
from culvia.cache_schema import SQLITE_CACHE_EXTENSIONS
from culvia.capabilities import local_capabilities
from culvia.config_payloads import (
    available_selected_models,
    device_label as _device_label,
    llm_config_payload as _llm_config_payload,
    model_option_payloads as _model_option_payloads,
    model_payload as _model_payload,
    model_runtime_keys,
    network_payload as _network_payload,
    normalize_network_mode,
)
from culvia.desktop_files import (
    DesktopActionCancelled,
    DesktopActionError,
    DesktopActionUnsupported,
    choose_folder_path,
    choose_folder_paths,
    reveal_path_in_file_manager,
)
from culvia.export_service import (
    ExportServiceError,
    export_preflight_action,
    export_selected_files_action,
    filtered_export_csv_action,
    selected_export_csv_action,
    unique_destination_path as _unique_destination_path,
)
from culvia.gallery_display import (
    apply_color_label_filter as _apply_color_label_filter,
    apply_manual_status_filter as _apply_manual_status_filter,
    color_label_matches as _color_label_matches,
    dataframe_for_display as _dataframe_for_display,
    manual_status_matches as _manual_status_matches,
    selected_preview_for_display,
)
from culvia.image_io import HEIF_AVAILABLE
from culvia.job_service import ScoringJobService
from culvia.llm_model_catalog import (
    fetch_llm_model_catalog,
    llm_models_url as _llm_models_url,
    parse_llm_model_list as _parse_llm_model_list,
)
from culvia.llm_config_requests import llm_config_from_payload as _llm_config_from_payload
from culvia.llm_config_service import (
    LLMConfigServiceDependencies,
    apply_llm_config_action,
    refresh_persisted_llm_config_action,
)
from culvia.maintenance import clear_history_cache, clear_local_data, clear_model_caches, resolve_history_cache_path
from culvia.media_service import (
    ensure_thumbnail_file as _ensure_thumbnail_file,
    image_url as _image_url,
    is_allowed_media_path as _is_allowed_media_path,
    is_inside_path as _is_inside_path,
    path_is_inside as _path_is_inside,
    safe_uploaded_relative_path as _safe_uploaded_relative_path,
    sanitize_uploaded_paths as _sanitize_uploaded_paths,
    save_uploaded_bytes,
    thumbnail_cache_path as _thumbnail_cache_path,
    thumbnail_url as _thumbnail_url,
)
from culvia.media_responses import accepts_json, image_media_response, thumbnail_media_response
from culvia.model_files import APP_MODEL_CACHE_DIR, MODEL_ID
from culvia.model_runtime import ModelRuntimeCache, system_proxy_configured
from culvia.payloads import (
    PhotoPayloadFields,
    compact_text_list as _compact_text_list,
    manual_rating_stars,
    photo_id as _photo_id,
    score_level,
    score_text,
    serialize_insight as _serialize_insight,
    serialize_mark,
    serialize_photo as _serialize_photo,
    star_rating,
    summarize_scores as _summarize_scores,
    technical_tags,
)
from culvia.photo_scan import SUPPORTED_EXTENSIONS, build_file_id
from culvia.recommendation import (
    FILTER_DEFAULTS,
    FILTER_THRESHOLD_COLUMNS,
    MODEL_AGREEMENT_OPTIONS,
    WEIGHT_PRESETS,
    active_weights,
    apply_model_agreement_filter as _apply_model_agreement_filter,
    calculate_recommendation,
    enrich_scores_for_display as _enrich_scores_for_display,
    model_agreement_matches as _model_agreement_matches,
    numeric_column,
    row_score_values,
    weighted_average,
)
from culvia.runtime_config import RuntimeConfig
from culvia.schema import (
    AESTHETIC_REFERENCE_FIELDS,
    AESTHETIC_REFERENCE_LABELS,
    CSV_COLUMNS,
    DEFAULT_LLM_PROMPT_PRESET,
    DEFAULT_SELECTED_MODELS,
    FIELD_GROUPS,
    LLM_OVERALL_AESTHETIC_WEIGHT,
    LLM_OVERALL_TECHNICAL_WEIGHT,
    LLM_PROMPT_PRESETS,
    LLM_REVIEW_FIELDS,
    LLM_REVIEW_LABELS,
    MODEL_BASIC_TECHNICAL,
    MODEL_CAPABILITIES,
    MODEL_CLIP_AESTHETIC,
    MODEL_CLIP_IQA,
    MODEL_CORE_AESTHETIC,
    MODEL_KEYS,
    MODEL_LLM_REVIEW,
    MODEL_QUALITY_FIELDS,
    MODEL_QUALITY_LABELS,
    MODEL_REPO_CACHE_DIRS,
    RECOMMENDATION_COLUMN,
    RUNTIME_CLIP_REFERENCE,
    RUNTIME_CORE_AESTHETIC,
    RUNTIME_LLM_REVIEW,
    RUNTIME_LOCAL,
    SCORE_FIELDS,
    SCORE_LABELS,
    SORT_FIELD_LABELS,
    SORT_FIELDS,
    TECHNICAL_FIELDS,
    TECHNICAL_LABELS,
    normalize_selected_models,
)
from culvia.scoring_runner import (
    ScoringRunnerDependencies,
    run_scoring_job as run_scoring_job_with_dependencies,
)
from culvia.scoring_service import ScoringStartError, start_scoring_job_action
from culvia.score_records import make_empty_score_record
from culvia.source_preview import (
    SourcePreviewDependencies,
    SourcePreviewStartError,
    run_source_preview_job as run_source_preview_job_with_dependencies,
    start_source_preview_job_action,
)
from culvia.source_service import (
    SourceCacheDependencies,
    apply_source_cache_state,
    filter_cache_to_folders as _filter_cache_to_folders,
    load_source_cache_action,
)
from culvia.state_payload import StatePayloadDependencies, build_state_payload
from culvia.curation_service import (
    CurationServiceError,
    accept_targets_action,
    color_targets_action,
    curation_history_payload,
    mark_photo_action,
    restore_marks_action,
    status_targets_action,
    undo_curation_action,
)
from culvia.web_app import create_runtime_state_store, create_web_app, create_web_routes
from culvia.web_context import (
    media_path_from_request as _media_path_from_request,
    path_from_query as _path_from_query,
    request_job_service as _request_job_service,
    request_runtime_config as _request_runtime_config,
    request_state_store as _request_state_store,
)
from culvia.web_routes import WebRouteHandlers
from culvia.curation import (
    COLOR_LABELS,
    PhotoMark,
    curation_export_dataframe as _curation_export_dataframe,
    curation_summary,
    load_photo_marks,
)
from culvia.curation_history import CurationActionRecord
from culvia.curation_targets import frame_file_ids
from culvia.scoring import (
    DEFAULT_CACHE_PATH,
    DEFAULT_PHOTO_DIRS,
    ANALYSIS_IMAGE_CACHE_DIR,
    clear_session_llm_config,
    clear_secure_llm_config,
    get_device,
    get_clip_reference_cache_status,
    get_huggingface_cache_root,
    get_model_cache_status,
    llm_review_base_url,
    llm_review_api_key,
    llm_review_custom_prompt,
    llm_review_endpoint,
    llm_review_model_name,
    llm_review_prompt_preset,
    llm_review_status,
    llm_review_timeout,
    load_llm_config_from_sqlite,
    load_analysis_insights,
    load_cache_records,
    mask_llm_api_key,
    normalize_score_dataframe,
    save_llm_config_to_sqlite,
    scan_image_paths,
    score_image_paths,
    set_persisted_llm_config,
    set_secure_llm_config,
    set_session_llm_config,
)
from culvia.secret_store import (
    SecretStoreError,
    SecretStoreUnavailable,
    delete_llm_api_key,
    load_llm_api_key,
    save_llm_api_key,
)


ROOT = Path(__file__).resolve().parent

RUNTIME_CONFIG = RuntimeConfig.from_settings()
WEB_DIR = RUNTIME_CONFIG.web_dir
UPLOAD_CACHE_DIR = RUNTIME_CONFIG.upload_cache_dir
THUMBNAIL_CACHE_DIR = RUNTIME_CONFIG.thumbnail_cache_dir
THUMBNAIL_MAX_SIZE = RUNTIME_CONFIG.thumbnail_max_size
THUMBNAIL_LOCK = threading.Lock()
KEYCHAIN_REFRESH_TIMEOUT_SECONDS = 1.5
_LLM_KEY_REFRESH_LOCK = threading.Lock()
_LLM_KEY_REFRESH_ATTEMPTED = False
_LLM_KEY_REFRESH_VALUE = ""
_LLM_KEY_REFRESH_ERROR: SecretStoreError | SecretStoreUnavailable | None = None

COLOR_LABEL_OPTIONS = [
    {"value": "all", "label": "全部"},
    {"value": "labeled", "label": "有色标"},
    {"value": "none", "label": "无色标"},
    *[{"value": value, "label": label} for value, label in COLOR_LABELS.items()],
]
COLOR_LABEL_FILTER_VALUES = {option["value"] for option in COLOR_LABEL_OPTIONS}
MANUAL_STATUS_OPTIONS = [
    {"value": "all", "label": "全部"},
    {"value": "pick", "label": "入选"},
    {"value": "pending", "label": "待复核"},
    {"value": "reject", "label": "淘汰"},
]
MANUAL_STATUS_FILTER_VALUES = {option["value"] for option in MANUAL_STATUS_OPTIONS}

APP_STATE = create_runtime_state_store(
    RUNTIME_CONFIG,
    load_scores=load_cache_records,
    filter_defaults=FILTER_DEFAULTS,
    default_selected_models=DEFAULT_SELECTED_MODELS,
)
STATE_LOCK = APP_STATE.lock
MODEL_RUNTIME = ModelRuntimeCache()
STATE: dict[str, Any] = APP_STATE.data
APP_JOB_SERVICE = ScoringJobService(APP_STATE)
PHOTO_PAYLOAD_FIELDS = PhotoPayloadFields(
    score_fields=tuple(SCORE_FIELDS),
    technical_fields=tuple(TECHNICAL_FIELDS),
    model_quality_fields=tuple(MODEL_QUALITY_FIELDS),
    aesthetic_reference_fields=tuple(AESTHETIC_REFERENCE_FIELDS),
    llm_review_fields=tuple(LLM_REVIEW_FIELDS),
)


def reset_llm_api_key_refresh_cache() -> None:
    global _LLM_KEY_REFRESH_ATTEMPTED, _LLM_KEY_REFRESH_VALUE, _LLM_KEY_REFRESH_ERROR
    with _LLM_KEY_REFRESH_LOCK:
        _LLM_KEY_REFRESH_ATTEMPTED = False
        _LLM_KEY_REFRESH_VALUE = ""
        _LLM_KEY_REFRESH_ERROR = None


def remember_llm_api_key_for_refresh(api_key: str) -> None:
    global _LLM_KEY_REFRESH_ATTEMPTED, _LLM_KEY_REFRESH_VALUE, _LLM_KEY_REFRESH_ERROR
    with _LLM_KEY_REFRESH_LOCK:
        _LLM_KEY_REFRESH_ATTEMPTED = True
        _LLM_KEY_REFRESH_VALUE = str(api_key or "").strip()
        _LLM_KEY_REFRESH_ERROR = None


def load_llm_api_key_for_refresh() -> str:
    global _LLM_KEY_REFRESH_ATTEMPTED, _LLM_KEY_REFRESH_VALUE, _LLM_KEY_REFRESH_ERROR
    with _LLM_KEY_REFRESH_LOCK:
        if _LLM_KEY_REFRESH_ATTEMPTED:
            if _LLM_KEY_REFRESH_ERROR is not None:
                raise _LLM_KEY_REFRESH_ERROR
            return _LLM_KEY_REFRESH_VALUE

    result: dict[str, object] = {}

    def load_key() -> None:
        try:
            result["value"] = load_llm_api_key()
        except (SecretStoreUnavailable, SecretStoreError) as exc:
            result["error"] = exc
        except Exception as exc:
            result["error"] = SecretStoreError(str(exc).strip() or exc.__class__.__name__)

    thread = threading.Thread(target=load_key, daemon=True)
    thread.start()
    thread.join(KEYCHAIN_REFRESH_TIMEOUT_SECONDS)

    if thread.is_alive():
        error = SecretStoreUnavailable("system keychain backend timed out")
        with _LLM_KEY_REFRESH_LOCK:
            _LLM_KEY_REFRESH_ATTEMPTED = True
            _LLM_KEY_REFRESH_VALUE = ""
            _LLM_KEY_REFRESH_ERROR = error
        raise error

    error = result.get("error")
    if isinstance(error, (SecretStoreUnavailable, SecretStoreError)):
        with _LLM_KEY_REFRESH_LOCK:
            _LLM_KEY_REFRESH_ATTEMPTED = True
            _LLM_KEY_REFRESH_VALUE = ""
            _LLM_KEY_REFRESH_ERROR = error
        raise error

    value = str(result.get("value") or "").strip()
    remember_llm_api_key_for_refresh(value)
    return value


def save_llm_api_key_for_config(api_key: str) -> None:
    save_llm_api_key(api_key)
    remember_llm_api_key_for_refresh(api_key)


def delete_llm_api_key_for_config() -> None:
    delete_llm_api_key()
    remember_llm_api_key_for_refresh("")


def active_thread_job_id() -> str:
    return APP_JOB_SERVICE.active_thread_job_id()


def bind_thread_job(job_id: str) -> None:
    APP_JOB_SERVICE.bind_thread_job(job_id)


def clear_thread_job() -> None:
    APP_JOB_SERVICE.clear_thread_job()


def update_job(**changes: Any) -> None:
    APP_JOB_SERVICE.update(**changes)


def reserve_scoring_job() -> str | None:
    return APP_JOB_SERVICE.reserve()


def reset_job_control(job_id: str | None = None) -> None:
    APP_JOB_SERVICE.reset_control(job_id)


def request_job_pause() -> bool:
    return APP_JOB_SERVICE.request_pause()


def request_job_resume() -> bool:
    return APP_JOB_SERVICE.request_resume()


def wait_if_job_paused(path: Path | None = None) -> None:
    APP_JOB_SERVICE.wait_if_paused(path)


def current_runtime_config() -> RuntimeConfig:
    return RuntimeConfig(
        web_dir=Path(WEB_DIR),
        upload_cache_dir=Path(UPLOAD_CACHE_DIR),
        thumbnail_cache_dir=Path(THUMBNAIL_CACHE_DIR),
        default_cache_path=str(DEFAULT_CACHE_PATH),
        default_photo_dirs=tuple(DEFAULT_PHOTO_DIRS),
        thumbnail_max_size=int(THUMBNAIL_MAX_SIZE),
    )


def request_runtime_config(request: Request) -> RuntimeConfig:
    return _request_runtime_config(request, current_runtime_config())


def safe_uploaded_relative_path(name: str) -> Path:
    return _safe_uploaded_relative_path(name)


def path_is_inside(path_text: str, folders: Iterable[str]) -> bool:
    return _path_is_inside(path_text, folders)


def is_inside_path(path: Path, root: Path) -> bool:
    return _is_inside_path(path, root)


def is_allowed_media_path(path: Path, source: dict[str, Any], scores_df: pd.DataFrame) -> bool:
    return _is_allowed_media_path(path, source, scores_df, upload_cache_dir=UPLOAD_CACHE_DIR)


def media_path_from_request(
    request: Request,
    state_store: AppStateStore | None = None,
) -> tuple[Path | None, int]:
    return _media_path_from_request(
        request,
        fallback_state_store=APP_STATE,
        fallback_runtime_config=current_runtime_config(),
        normalize_dataframe=normalize_score_dataframe,
        state_store=state_store,
    )


def path_from_query(request: Request, state_store: AppStateStore | None = None) -> Path | None:
    return _path_from_query(
        request,
        fallback_state_store=APP_STATE,
        fallback_runtime_config=current_runtime_config(),
        normalize_dataframe=normalize_score_dataframe,
        state_store=state_store,
    )


def sanitize_uploaded_paths(paths: Iterable[object]) -> list[Path]:
    return _sanitize_uploaded_paths(paths, upload_cache_dir=UPLOAD_CACHE_DIR)


def filter_cache_to_folders(df: pd.DataFrame, folders: list[str]) -> pd.DataFrame:
    return _filter_cache_to_folders(df, folders, path_matcher=path_is_inside)


def source_cache_dependencies() -> SourceCacheDependencies:
    return SourceCacheDependencies(
        default_cache_path=DEFAULT_CACHE_PATH,
        load_cache_records=load_cache_records,
        path_is_inside=path_is_inside,
    )


def curation_export_dataframe(df: pd.DataFrame, marks: dict[str, PhotoMark]) -> pd.DataFrame:
    return _curation_export_dataframe(df, marks, normalize_dataframe=normalize_score_dataframe)


def unique_destination_path(destination: Path, filename: str) -> Path:
    return _unique_destination_path(destination, filename)


def enrich_scores_for_display(df: pd.DataFrame, filters: dict[str, Any]) -> pd.DataFrame:
    return _enrich_scores_for_display(
        df,
        filters,
        normalize_dataframe=normalize_score_dataframe,
        score_fields=(
            *SCORE_FIELDS,
            *TECHNICAL_FIELDS,
            *MODEL_QUALITY_FIELDS,
            *AESTHETIC_REFERENCE_FIELDS,
            *LLM_REVIEW_FIELDS,
        ),
    )


def device_label(device: str | None = None) -> str:
    return _device_label(device or get_device())


def network_payload(network: dict[str, Any]) -> dict[str, Any]:
    return _network_payload(network, system_proxy_available=system_proxy_configured())


def llm_config_payload() -> dict[str, Any]:
    return _llm_config_payload(
        status=llm_review_status(),
        prompt_preset=llm_review_prompt_preset(),
        api_key=llm_review_api_key(),
        model=llm_review_model_name(),
        base_url=llm_review_base_url(),
        endpoint=llm_review_endpoint(),
        custom_prompt=llm_review_custom_prompt(),
        prompt_presets=LLM_PROMPT_PRESETS,
        mask_api_key=mask_llm_api_key,
    )


def llm_config_from_payload(payload: dict[str, Any]) -> dict[str, str]:
    return _llm_config_from_payload(
        payload,
        prompt_presets=LLM_PROMPT_PRESETS,
        default_prompt_preset=DEFAULT_LLM_PROMPT_PRESET,
    )


def llm_config_service_dependencies() -> LLMConfigServiceDependencies:
    return LLMConfigServiceDependencies(
        prompt_presets=LLM_PROMPT_PRESETS,
        default_prompt_preset=DEFAULT_LLM_PROMPT_PRESET,
        load_persisted_config=load_llm_config_from_sqlite,
        save_persisted_config=save_llm_config_to_sqlite,
        set_persisted_config=set_persisted_llm_config,
        set_session_config=set_session_llm_config,
        clear_session_config=clear_session_llm_config,
        set_secure_config=set_secure_llm_config,
        clear_secure_config=clear_secure_llm_config,
        load_api_key=load_llm_api_key_for_refresh,
        save_api_key=save_llm_api_key_for_config,
        delete_api_key=delete_llm_api_key_for_config,
    )


def refresh_persisted_llm_config(cache_path: str | Path) -> None:
    refresh_persisted_llm_config_action(cache_path, llm_config_service_dependencies())


def apply_llm_config(payload: dict[str, Any], cache_path: str | Path) -> None:
    apply_llm_config_action(payload, cache_path, llm_config_service_dependencies())


def llm_models_url(base_url: str, endpoint: str) -> str:
    return _llm_models_url(base_url, endpoint)


def parse_llm_model_list(payload: Any, current_model: str) -> list[dict[str, str]]:
    return _parse_llm_model_list(payload, current_model)


def fetch_llm_models(payload: dict[str, Any]) -> dict[str, Any]:
    api_key = str(payload.get("apiKey") or "").strip() or llm_review_api_key()
    base_url = str(payload.get("baseUrl") or "").strip() or llm_review_base_url()
    endpoint = str(payload.get("endpoint") or "").strip() or llm_review_endpoint()
    current_model = str(payload.get("model") or "").strip() or llm_review_model_name()
    return fetch_llm_model_catalog(
        api_key=api_key,
        base_url=base_url,
        endpoint=endpoint,
        current_model=current_model,
        timeout=max(5.0, min(float(llm_review_timeout()), 30.0)),
        get=requests.get,
    )


def image_url(path: str, max_size: int, *, file_id: str = "") -> str:
    return _image_url(path, max_size, file_id=file_id)


def thumbnail_url(path: str, max_size: int = THUMBNAIL_MAX_SIZE, *, file_id: str = "") -> str:
    return _thumbnail_url(path, max_size, file_id=file_id)


def photo_id(path: str) -> str:
    return _photo_id(path)


def make_empty_preview_record(path: Path, file_id: str, error: str = "") -> dict[str, object]:
    return make_empty_score_record(
        path,
        file_id,
        recommendation_column=RECOMMENDATION_COLUMN,
        field_groups=FIELD_GROUPS,
        error=error,
    )


def source_preview_dependencies() -> SourcePreviewDependencies:
    return SourcePreviewDependencies(
        default_cache_path=DEFAULT_CACHE_PATH,
        scan_image_paths=scan_image_paths,
        sanitize_uploaded_paths=sanitize_uploaded_paths,
        build_file_id=build_file_id,
        load_cache_records=load_cache_records,
        normalize_score_dataframe=normalize_score_dataframe,
        make_empty_record=make_empty_preview_record,
    )


def dataframe_for_display(
    df: pd.DataFrame,
    filters: dict[str, Any],
    mark_by_file_id: dict[str, PhotoMark] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return _dataframe_for_display(
        df,
        filters,
        mark_by_file_id,
        enrich_scores=enrich_scores_for_display,
        apply_model_agreement=apply_model_agreement_filter,
        sort_fields=set(SORT_FIELDS),
        manual_status_filter_values=MANUAL_STATUS_FILTER_VALUES,
        color_label_filter_values=COLOR_LABEL_FILTER_VALUES,
    )


def manual_status_matches(mark: PhotoMark | None, mode: str) -> bool:
    return _manual_status_matches(mark, mode)


def apply_manual_status_filter(df: pd.DataFrame, marks: dict[str, PhotoMark], mode: str) -> pd.DataFrame:
    return _apply_manual_status_filter(df, marks, mode, valid_modes=MANUAL_STATUS_FILTER_VALUES)


def color_label_matches(mark: PhotoMark | None, mode: str) -> bool:
    return _color_label_matches(mark, mode)


def apply_color_label_filter(df: pd.DataFrame, marks: dict[str, PhotoMark], mode: str) -> pd.DataFrame:
    return _apply_color_label_filter(df, marks, mode, valid_modes=COLOR_LABEL_FILTER_VALUES)


def model_agreement_matches(row: pd.Series, mode: str) -> bool:
    return _model_agreement_matches(
        row,
        mode,
        llm_aesthetic_weight=LLM_OVERALL_AESTHETIC_WEIGHT,
        llm_technical_weight=LLM_OVERALL_TECHNICAL_WEIGHT,
    )


def apply_model_agreement_filter(df: pd.DataFrame, mode: str) -> pd.DataFrame:
    return _apply_model_agreement_filter(
        df,
        mode,
        llm_aesthetic_weight=LLM_OVERALL_AESTHETIC_WEIGHT,
        llm_technical_weight=LLM_OVERALL_TECHNICAL_WEIGHT,
    )


def compact_text_list(value: object) -> list[str]:
    return _compact_text_list(value)


def serialize_insight(insight: Any | None) -> dict[str, Any] | None:
    return _serialize_insight(insight)


def serialize_photo(
    row: pd.Series,
    insight_by_file_id: dict[str, Any] | None = None,
    mark_by_file_id: dict[str, PhotoMark] | None = None,
) -> dict[str, Any]:
    return _serialize_photo(
        row,
        PHOTO_PAYLOAD_FIELDS,
        image_url=image_url,
        thumbnail_url=thumbnail_url,
        insight_by_file_id=insight_by_file_id,
        mark_by_file_id=mark_by_file_id,
    )


def summarize_scores(
    source_df: pd.DataFrame,
    filtered_df: pd.DataFrame,
    errors: pd.DataFrame,
    filters: dict[str, Any],
) -> dict[str, Any]:
    return _summarize_scores(
        source_df,
        filtered_df,
        errors,
        filters,
        enrich_scores_for_display=enrich_scores_for_display,
    )


def model_option_payloads(selected_models: list[str]) -> list[dict[str, Any]]:
    core_status = get_model_cache_status()
    clip_status = get_clip_reference_cache_status()
    llm_status = llm_review_status()
    return _model_option_payloads(
        selected_models,
        model_keys=MODEL_KEYS,
        model_capabilities=MODEL_CAPABILITIES,
        runtime_status={
            RUNTIME_CORE_AESTHETIC: core_status,
            RUNTIME_CLIP_REFERENCE: clip_status,
            RUNTIME_LOCAL: {"downloaded": True, "partial": False, "model_size_label": "无需下载"},
            RUNTIME_LLM_REVIEW: {
                "downloaded": bool(llm_status["configured"]),
                "partial": False,
                "model_size_label": "已配置" if llm_status["configured"] else "需配置",
            },
        },
        llm_status=llm_status,
        llm_model_key=MODEL_LLM_REVIEW,
    )


def model_payload(network: dict[str, Any], selected_models: list[str]) -> dict[str, Any]:
    status = get_model_cache_status()
    clip_status = get_clip_reference_cache_status()
    network_status = network_payload(network)
    llm_status = llm_review_status()
    selected = available_selected_models(
        normalize_selected_models(selected_models),
        llm_configured=bool(llm_status["configured"]),
        llm_model_key=MODEL_LLM_REVIEW,
    )
    options = model_option_payloads(selected)
    selected_device = get_device()
    selected_runtime_keys = model_runtime_keys(
        selected,
        model_capabilities=MODEL_CAPABILITIES,
        excluded_runtime_keys={RUNTIME_LOCAL, RUNTIME_LLM_REVIEW},
    )
    runtime_loaded = MODEL_RUNTIME.any_loaded(selected_runtime_keys, selected_device)
    return _model_payload(
        model_id=MODEL_ID,
        selected_models=selected,
        options=options,
        core_status=status,
        clip_status=clip_status,
        network_status=network_status,
        runtime_loaded=runtime_loaded,
        runtime_device_label=device_label(selected_device),
    )


def request_state_store(request: Request) -> AppStateStore:
    return _request_state_store(request, APP_STATE)


def request_job_service(request: Request) -> ScoringJobService:
    return _request_job_service(request, APP_JOB_SERVICE)


STATE_PAYLOAD_DEPENDENCIES = StatePayloadDependencies(
    app_name="Culvia",
    app_subtitle="为作品建立秩序",
    default_cache_path=DEFAULT_CACHE_PATH,
    heif_available=HEIF_AVAILABLE,
    model_llm_review=MODEL_LLM_REVIEW,
    sort_fields=SORT_FIELDS,
    sort_field_labels=SORT_FIELD_LABELS,
    model_agreement_options=MODEL_AGREEMENT_OPTIONS,
    manual_status_options=MANUAL_STATUS_OPTIONS,
    color_label_options=COLOR_LABEL_OPTIONS,
    weight_presets=WEIGHT_PRESETS,
    score_labels=SCORE_LABELS,
    technical_labels=TECHNICAL_LABELS,
    model_quality_labels=MODEL_QUALITY_LABELS,
    aesthetic_reference_labels=AESTHETIC_REFERENCE_LABELS,
    llm_review_labels=LLM_REVIEW_LABELS,
    normalize_score_dataframe=normalize_score_dataframe,
    refresh_persisted_llm_config=refresh_persisted_llm_config,
    frame_file_ids=frame_file_ids,
    load_photo_marks=load_photo_marks,
    dataframe_for_display=dataframe_for_display,
    selected_preview_for_display=selected_preview_for_display,
    load_analysis_insights=load_analysis_insights,
    serialize_photo=serialize_photo,
    curation_summary=curation_summary,
    local_capabilities=local_capabilities,
    device_label=device_label,
    network_payload=network_payload,
    llm_config_payload=llm_config_payload,
    normalize_selected_models=normalize_selected_models,
    model_payload=model_payload,
    summarize_scores=summarize_scores,
)


def state_payload(state_store: AppStateStore | None = None) -> dict[str, Any]:
    return build_state_payload(state_store or APP_STATE, STATE_PAYLOAD_DEPENDENCIES)


async def homepage(request: Request) -> Response:
    return FileResponse(request_runtime_config(request).web_dir / "index.html")


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


async def host_config(_: Request) -> JSONResponse:
    return JSONResponse({})


async def api_capabilities(_: Request) -> JSONResponse:
    return JSONResponse(local_capabilities())


async def api_state(request: Request) -> JSONResponse:
    return JSONResponse(state_payload(request_state_store(request)))


async def api_filter(request: Request) -> JSONResponse:
    payload = await request.json()
    state_store = request_state_store(request)
    with state_store.lock:
        filters = state_store.data["filters"]
        if "sortField" in payload and payload["sortField"] in SORT_FIELDS:
            filters["sortField"] = payload["sortField"]
        for filter_key in FILTER_THRESHOLD_COLUMNS:
            if filter_key in payload:
                filters[filter_key] = max(0.0, min(float(payload[filter_key]), 10.0))
        if "modelAgreement" in payload and payload["modelAgreement"] in {
            option["value"] for option in MODEL_AGREEMENT_OPTIONS
        }:
            filters["modelAgreement"] = payload["modelAgreement"]
        if "manualStatus" in payload and payload["manualStatus"] in MANUAL_STATUS_FILTER_VALUES:
            filters["manualStatus"] = payload["manualStatus"]
        if "colorLabel" in payload and payload["colorLabel"] in COLOR_LABEL_FILTER_VALUES:
            filters["colorLabel"] = payload["colorLabel"]
        if "limit" in payload:
            filters["limit"] = max(1, min(int(payload["limit"]), 500))
        if "weightPreset" in payload and payload["weightPreset"] in WEIGHT_PRESETS:
            filters["weightPreset"] = payload["weightPreset"]
        if isinstance(payload.get("customWeights"), dict):
            current = dict(filters.get("customWeights") or {})
            incoming = payload["customWeights"]
            for key in ("aesthetic", "technical", "compositionLight"):
                if key in incoming:
                    current[key] = max(0.0, min(float(incoming[key]), 1.0))
            filters["customWeights"] = current
    return JSONResponse(state_payload(state_store))


async def api_network(request: Request) -> JSONResponse:
    state_store = request_state_store(request)
    if job_is_running(state_store):
        return job_running_operation_response()
    payload = await request.json()
    with state_store.lock:
        state_store.data["network"]["mode"] = normalize_network_mode(payload.get("mode"))
    return JSONResponse(state_payload(state_store))


async def api_llm_config(request: Request) -> JSONResponse:
    state_store = request_state_store(request)
    if job_is_running(state_store):
        return api_error_response("jobRunningLlmConfig", "当前任务运行中，暂时不能修改大模型配置。", status_code=409)
    payload = await request.json()
    cache_path = str(payload.get("cachePath") or DEFAULT_CACHE_PATH)
    try:
        apply_llm_config(payload, cache_path)
    except ValueError as exc:
        return api_error_response("llmConfigInvalid", str(exc), status_code=400, params={"reason": str(exc)})
    if not bool(llm_review_status()["configured"]):
        with state_store.lock:
            selected = normalize_selected_models(state_store.data["models"].get("selected"))
            state_store.data["models"]["selected"] = (
                available_selected_models(
                    selected,
                    llm_configured=False,
                    llm_model_key=MODEL_LLM_REVIEW,
                )
                or DEFAULT_SELECTED_MODELS.copy()
            )
    return JSONResponse(state_payload(state_store))


async def api_llm_models(request: Request) -> JSONResponse:
    payload = await request.json()
    try:
        return JSONResponse(fetch_llm_models(payload))
    except ValueError as exc:
        return api_error_response("llmModelListInvalid", str(exc), status_code=400, params={"reason": str(exc)})
    except requests.RequestException as exc:
        return api_error_response(
            "llmModelListRequestFailed",
            f"模型列表读取失败：{exc!r}",
            status_code=502,
            params={"reason": repr(exc)},
        )


async def api_models(request: Request) -> JSONResponse:
    state_store = request_state_store(request)
    if job_is_running(state_store):
        return job_running_operation_response()
    payload = await request.json()
    selected = available_selected_models(
        normalize_selected_models(payload.get("selected")),
        llm_configured=bool(llm_review_status()["configured"]),
        llm_model_key=MODEL_LLM_REVIEW,
    )
    with state_store.lock:
        state_store.data["models"]["selected"] = selected or DEFAULT_SELECTED_MODELS.copy()
    return JSONResponse(state_payload(state_store))


async def api_cache(request: Request) -> JSONResponse:
    state_store = request_state_store(request)
    if job_is_running(state_store):
        return job_running_operation_response()
    payload = await request.json()
    try:
        result = load_source_cache_action(payload, source_cache_dependencies())
    except ValueError as exc:
        return api_error_response("cachePathInvalid", str(exc), status_code=400, params={"reason": str(exc)})
    apply_source_cache_state(state_store, result)
    return JSONResponse(state_payload(state_store))


async def api_source_preview(request: Request) -> JSONResponse:
    state_store = request_state_store(request)
    job_service = request_job_service(request)
    payload = await request.json()
    try:
        result = start_source_preview_job_action(
            payload,
            state_store,
            job_service,
            default_cache_path=DEFAULT_CACHE_PATH,
            run_source_preview_job=run_source_preview_job,
            thread_factory=threading.Thread,
        )
    except ValueError as exc:
        return api_error_response("sourcePreviewInvalid", str(exc), status_code=400, params={"reason": str(exc)})
    except SourcePreviewStartError as exc:
        return api_error_response(exc.error_code, exc.message, status_code=exc.status_code)
    response_payload = state_payload(state_store)
    response_payload["sourcePreviewJob"] = result.to_payload()
    return JSONResponse(response_payload)


def job_is_running(state_store: AppStateStore | None = None) -> bool:
    store = state_store or APP_STATE
    with store.lock:
        return bool(store.data["job"].get("running"))


def job_running_operation_response() -> JSONResponse:
    return api_error_response("jobRunningOperation", "当前任务运行中，暂时不能执行这个操作。", status_code=409)


async def api_clear_history(request: Request) -> JSONResponse:
    state_store = request_state_store(request)
    if job_is_running(state_store):
        return api_error_response("jobRunningClearHistory", "当前任务运行中，暂时不能清空评分记录。", status_code=409)

    payload = await request.json()
    with state_store.lock:
        current_cache_path = str(state_store.data["source"].get("cachePath") or DEFAULT_CACHE_PATH)
    cache_path, error = resolve_history_cache_path(
        payload.get("cachePath"),
        current_cache_path=current_cache_path,
        default_cache_path=DEFAULT_CACHE_PATH,
        allowed_suffixes=SQLITE_CACHE_EXTENSIONS,
    )
    if cache_path is None:
        return api_error_response(
            "historyCachePathInvalid", error or "评分记录路径不可用。", status_code=400, params={"reason": error or ""}
        )

    result = clear_history_cache(cache_path)
    with state_store.lock:
        state_store.data["scores_df"] = pd.DataFrame(columns=CSV_COLUMNS)
        state_store.data["source"]["cachePath"] = str(cache_path)
        state_store.data["job"] = empty_job()
    payload = state_payload(state_store)
    payload["maintenance"] = result.to_payload()
    return JSONResponse(payload)


async def api_clear_local_data(request: Request) -> JSONResponse:
    state_store = request_state_store(request)
    if job_is_running(state_store):
        return api_error_response("jobRunningClearLocalData", "当前任务运行中，暂时不能重置本机数据。", status_code=409)

    payload = await request.json()
    with state_store.lock:
        current_cache_path = str(state_store.data["source"].get("cachePath") or DEFAULT_CACHE_PATH)
    cache_path, error = resolve_history_cache_path(
        payload.get("cachePath"),
        current_cache_path=current_cache_path,
        default_cache_path=DEFAULT_CACHE_PATH,
        allowed_suffixes=SQLITE_CACHE_EXTENSIONS,
    )
    if cache_path is None:
        return api_error_response(
            "localDataCachePathInvalid",
            error or "评分记录路径不可用。",
            status_code=400,
            params={"reason": error or ""},
        )

    secret_warning = ""
    try:
        delete_llm_api_key()
    except SecretStoreUnavailable:
        pass
    except SecretStoreError as exc:
        secret_warning = str(exc)

    clear_session_llm_config()
    clear_secure_llm_config()
    set_persisted_llm_config({})
    MODEL_RUNTIME.clear()

    try:
        result = clear_local_data(
            cache_path=cache_path,
            upload_cache_dir=UPLOAD_CACHE_DIR,
            thumbnail_cache_dir=THUMBNAIL_CACHE_DIR,
            analysis_image_cache_dir=ANALYSIS_IMAGE_CACHE_DIR,
            app_model_cache_dir=APP_MODEL_CACHE_DIR,
            model_repo_cache_dirs=MODEL_REPO_CACHE_DIRS,
            huggingface_cache_root=get_huggingface_cache_root(),
        )
    except ValueError as exc:
        return api_error_response("localDataClearInvalid", str(exc), status_code=400, params={"reason": str(exc)})
    except OSError as exc:
        return api_error_response(
            "localDataClearFailed", f"清理失败：{exc}", status_code=500, params={"reason": str(exc)}
        )

    next_state = create_initial_state(
        scores_df=pd.DataFrame(columns=CSV_COLUMNS),
        default_photo_dirs=[],
        default_cache_path=str(cache_path),
        filter_defaults=FILTER_DEFAULTS,
        default_selected_models=DEFAULT_SELECTED_MODELS,
    )
    with state_store.lock:
        state_store.data.clear()
        state_store.data.update(next_state)
    response_payload = state_payload(state_store)
    response_payload["maintenance"] = result.to_payload()
    if secret_warning:
        response_payload["maintenance"]["secretWarning"] = secret_warning
    return JSONResponse(response_payload)


async def api_clear_model(request: Request) -> JSONResponse:
    state_store = request_state_store(request)
    if job_is_running(state_store):
        return api_error_response("jobRunningClearModel", "当前任务运行中，暂时不能删除模型文件。", status_code=409)

    try:
        result = clear_model_caches(APP_MODEL_CACHE_DIR, MODEL_REPO_CACHE_DIRS, get_huggingface_cache_root())
    except ValueError as exc:
        return api_error_response("modelClearInvalid", str(exc), status_code=400, params={"reason": str(exc)})
    except OSError as exc:
        return api_error_response("modelClearFailed", f"删除失败：{exc}", status_code=500, params={"reason": str(exc)})

    MODEL_RUNTIME.clear()
    with state_store.lock:
        state_store.data["job"] = empty_job()
    payload = state_payload(state_store)
    payload["maintenance"] = result.to_payload()
    return JSONResponse(payload)


async def api_upload(request: Request) -> JSONResponse:
    state_store = request_state_store(request)
    if job_is_running(state_store):
        return job_running_operation_response()
    runtime_config = request_runtime_config(request)
    form = await request.form()
    files = form.getlist("files")
    saved_paths: list[str] = []
    ignored = 0

    for upload in files:
        try:
            filename = getattr(upload, "filename", "") or "uploaded_image"
            data = await upload.read()
            target = save_uploaded_bytes(
                filename=filename,
                data=data,
                upload_cache_dir=runtime_config.upload_cache_dir,
                supported_extensions=SUPPORTED_EXTENSIONS,
            )
            if target is None:
                ignored += 1
                continue
            saved_paths.append(str(target))
        finally:
            close_upload = getattr(upload, "close", None)
            if callable(close_upload):
                await close_upload()

    unique_paths = sorted(set(saved_paths), key=str.casefold)
    with state_store.lock:
        state_store.data["source"].update({"mode": "uploads", "uploadedPaths": unique_paths})

    return JSONResponse({"saved": unique_paths, "count": len(unique_paths), "ignored": ignored})


def cached_model_loader(
    device: str,
    network_mode: str = "direct",
    job_service: ScoringJobService | None = None,
):
    return MODEL_RUNTIME.load_core_model(device, network_mode=network_mode, job_service=job_service or APP_JOB_SERVICE)


def cached_clip_reference_loader(
    device: str,
    network_mode: str = "direct",
    job_service: ScoringJobService | None = None,
):
    return MODEL_RUNTIME.load_clip_reference(
        device, network_mode=network_mode, job_service=job_service or APP_JOB_SERVICE
    )


def llm_review_configured() -> bool:
    return bool(llm_review_status()["configured"])


def scoring_runner_dependencies() -> ScoringRunnerDependencies:
    return ScoringRunnerDependencies(
        default_cache_path=DEFAULT_CACHE_PATH,
        empty_score_columns=CSV_COLUMNS,
        llm_review_model_key=MODEL_LLM_REVIEW,
        sanitize_uploaded_paths=sanitize_uploaded_paths,
        normalize_network_mode=normalize_network_mode,
        normalize_selected_models=normalize_selected_models,
        refresh_persisted_llm_config=refresh_persisted_llm_config,
        llm_review_configured=llm_review_configured,
        scan_image_paths=scan_image_paths,
        score_image_paths=score_image_paths,
        model_loader=cached_model_loader,
        clip_reference_loader=cached_clip_reference_loader,
        thumbnail_url=thumbnail_url,
        device_label=device_label,
    )


def run_scoring_job(
    job_id: str,
    payload: dict[str, Any],
    state_store: AppStateStore | None = None,
    job_service: ScoringJobService | None = None,
) -> None:
    run_scoring_job_with_dependencies(
        job_id,
        payload,
        state_store or APP_STATE,
        job_service or APP_JOB_SERVICE,
        scoring_runner_dependencies(),
    )


def run_source_preview_job(
    job_id: str,
    payload: dict[str, Any],
    state_store: AppStateStore | None = None,
    job_service: ScoringJobService | None = None,
) -> None:
    run_source_preview_job_with_dependencies(
        job_id,
        payload,
        state_store or APP_STATE,
        job_service or APP_JOB_SERVICE,
        source_preview_dependencies(),
    )


async def api_score(request: Request) -> JSONResponse:
    payload = await request.json()
    state_store = request_state_store(request)
    job_service = request_job_service(request)
    try:
        result = start_scoring_job_action(
            payload,
            state_store,
            job_service,
            run_scoring_job=run_scoring_job,
            thread_factory=threading.Thread,
        )
    except ScoringStartError as error:
        return scoring_start_error_response(error)
    return JSONResponse(result.to_payload())


async def api_job_pause(request: Request) -> JSONResponse:
    job_service = request_job_service(request)
    if not job_service.request_pause():
        return api_error_response("noRunningJob", "当前没有正在运行的评分任务。", status_code=409)
    return JSONResponse(state_payload(job_service.state_store))


async def api_job_resume(request: Request) -> JSONResponse:
    job_service = request_job_service(request)
    if not job_service.request_resume():
        return api_error_response("noRunningJob", "当前没有正在运行的评分任务。", status_code=409)
    return JSONResponse(state_payload(job_service.state_store))


async def api_mark_photo(request: Request) -> JSONResponse:
    state_store = request_state_store(request)
    if job_is_running(state_store):
        return job_running_operation_response()
    payload = await request.json()
    with state_store.lock:
        state = state_store.data
        source_df = normalize_score_dataframe(state["scores_df"]).copy()
        cache_path = str(state["source"].get("cachePath") or DEFAULT_CACHE_PATH)
    try:
        action = mark_photo_action(cache_path, source_df, payload)
    except CurationServiceError as error:
        return curation_service_error_response(error)
    response = state_payload(state_store)
    response["action"] = action
    return JSONResponse(response)


def curation_service_error_response(error: CurationServiceError) -> JSONResponse:
    extra = {"conflicts": error.conflicts} if error.conflicts else {}
    return api_error_response(
        error.error_code,
        error.message,
        status_code=error.status_code,
        params=error.params,
        **extra,
    )


def export_service_error_response(error: ExportServiceError) -> JSONResponse:
    return api_error_response(error.error_code, error.message, status_code=error.status_code, params=error.params)


def scoring_start_error_response(error: ScoringStartError) -> JSONResponse:
    return api_error_response(error.error_code, error.message, status_code=error.status_code)


async def api_mark_color(request: Request) -> JSONResponse:
    state_store = request_state_store(request)
    if job_is_running(state_store):
        return job_running_operation_response()
    payload = await request.json()
    with state_store.lock:
        state = state_store.data
        source_df = normalize_score_dataframe(state["scores_df"]).copy()
        filters = dict(state["filters"])
        cache_path = str(state["source"].get("cachePath") or DEFAULT_CACHE_PATH)
    try:
        action = color_targets_action(cache_path, source_df, filters, payload, dataframe_for_display)
    except CurationServiceError as error:
        return curation_service_error_response(error)
    response = state_payload(state_store)
    response["action"] = action
    return JSONResponse(response)


async def api_mark_status(request: Request) -> JSONResponse:
    state_store = request_state_store(request)
    if job_is_running(state_store):
        return job_running_operation_response()
    payload = await request.json()
    with state_store.lock:
        state = state_store.data
        source_df = normalize_score_dataframe(state["scores_df"]).copy()
        filters = dict(state["filters"])
        cache_path = str(state["source"].get("cachePath") or DEFAULT_CACHE_PATH)
    try:
        action = status_targets_action(cache_path, source_df, filters, payload, dataframe_for_display)
    except CurationServiceError as error:
        return curation_service_error_response(error)
    response = state_payload(state_store)
    response["action"] = action
    return JSONResponse(response)


async def api_restore_marks(request: Request) -> JSONResponse:
    state_store = request_state_store(request)
    if job_is_running(state_store):
        return job_running_operation_response()
    payload = await request.json()
    with state_store.lock:
        state = state_store.data
        source_df = normalize_score_dataframe(state["scores_df"]).copy()
        cache_path = str(state["source"].get("cachePath") or DEFAULT_CACHE_PATH)
    try:
        action = restore_marks_action(cache_path, source_df, payload)
    except CurationServiceError as error:
        return curation_service_error_response(error)
    response = state_payload(state_store)
    response["action"] = action
    return JSONResponse(response)


async def api_accept_marks(request: Request) -> JSONResponse:
    state_store = request_state_store(request)
    if job_is_running(state_store):
        return job_running_operation_response()
    payload = await request.json()
    with state_store.lock:
        state = state_store.data
        source_df = normalize_score_dataframe(state["scores_df"]).copy()
        filters = dict(state["filters"])
        cache_path = str(state["source"].get("cachePath") or DEFAULT_CACHE_PATH)
    try:
        action = accept_targets_action(cache_path, source_df, filters, payload, dataframe_for_display)
    except CurationServiceError as error:
        return curation_service_error_response(error)
    response = state_payload(state_store)
    response["action"] = action
    return JSONResponse(response)


async def api_curation_history(request: Request) -> JSONResponse:
    state_store = request_state_store(request)
    with state_store.lock:
        cache_path = str(state_store.data["source"].get("cachePath") or DEFAULT_CACHE_PATH)
    try:
        limit = int(request.query_params.get("limit", "50") or "50")
    except ValueError:
        limit = 50
    return JSONResponse(curation_history_payload(cache_path, limit=limit))


async def api_curation_undo(request: Request) -> JSONResponse:
    state_store = request_state_store(request)
    if job_is_running(state_store):
        return job_running_operation_response()
    payload = await request.json()
    with state_store.lock:
        state = state_store.data
        source_df = normalize_score_dataframe(state["scores_df"]).copy()
        cache_path = str(state["source"].get("cachePath") or DEFAULT_CACHE_PATH)
    try:
        action = undo_curation_action(cache_path, source_df, payload)
    except CurationServiceError as error:
        return curation_service_error_response(error)
    response = state_payload(state_store)
    response["action"] = action
    return JSONResponse(response)


async def api_image(request: Request) -> Response:
    path, status_code = media_path_from_request(request, request_state_store(request))
    max_size = int(request.query_params.get("max", "1800") or "1800")
    return image_media_response(path, status_code, max_size, wants_json=accepts_json(request.headers.get("accept", "")))


def thumbnail_cache_path(path: Path, max_size: int) -> Path:
    return _thumbnail_cache_path(path, THUMBNAIL_CACHE_DIR, max_size)


def ensure_thumbnail_file(path: Path, max_size: int) -> Path:
    return _ensure_thumbnail_file(path, THUMBNAIL_CACHE_DIR, max_size, lock=THUMBNAIL_LOCK)


async def api_thumbnail(request: Request) -> Response:
    runtime_config = request_runtime_config(request)
    path, status_code = media_path_from_request(request, request_state_store(request))
    max_size = int(
        request.query_params.get("max", str(runtime_config.thumbnail_max_size)) or runtime_config.thumbnail_max_size
    )
    return thumbnail_media_response(
        path,
        status_code,
        max_size,
        cache_dir=runtime_config.thumbnail_cache_dir,
        lock=THUMBNAIL_LOCK,
        wants_json=accepts_json(request.headers.get("accept", "")),
    )


async def api_export(request: Request) -> Response:
    state_store = request_state_store(request)
    if job_is_running(state_store):
        return job_running_operation_response()
    with state_store.lock:
        state = state_store.data
        source_df = normalize_score_dataframe(state["scores_df"]).copy()
        filters = dict(state["filters"])
        cache_path = str(state["source"].get("cachePath") or DEFAULT_CACHE_PATH)
    csv_bytes = filtered_export_csv_action(
        source_df,
        filters,
        cache_path,
        dataframe_for_display,
        normalize_dataframe=normalize_score_dataframe,
    )
    headers = {"Content-Disposition": 'attachment; filename="culvia_scores_filtered.csv"'}
    return Response(csv_bytes, media_type="text/csv; charset=utf-8", headers=headers)


async def api_export_selected_csv(request: Request) -> Response:
    state_store = request_state_store(request)
    if job_is_running(state_store):
        return job_running_operation_response()
    with state_store.lock:
        state = state_store.data
        source_df = normalize_score_dataframe(state["scores_df"]).copy()
        cache_path = str(state["source"].get("cachePath") or DEFAULT_CACHE_PATH)
    csv_bytes = selected_export_csv_action(source_df, cache_path, normalize_dataframe=normalize_score_dataframe)
    headers = {"Content-Disposition": 'attachment; filename="culvia_scores_selected.csv"'}
    return Response(csv_bytes, media_type="text/csv; charset=utf-8", headers=headers)


async def api_export_preflight(request: Request) -> JSONResponse:
    state_store = request_state_store(request)
    if job_is_running(state_store):
        return job_running_operation_response()
    payload = await request.json()
    destination_text = str(payload.get("destination") or "").strip()
    with state_store.lock:
        state = state_store.data
        source_df = normalize_score_dataframe(state["scores_df"]).copy()
        cache_path = str(state["source"].get("cachePath") or DEFAULT_CACHE_PATH)
    try:
        result = export_preflight_action(source_df, cache_path, destination_text)
    except ExportServiceError as error:
        return export_service_error_response(error)
    return JSONResponse(result.to_payload())


async def api_export_selected(request: Request) -> JSONResponse:
    state_store = request_state_store(request)
    if job_is_running(state_store):
        return job_running_operation_response()
    payload = await request.json()
    destination_text = str(payload.get("destination") or "").strip()
    with state_store.lock:
        state = state_store.data
        source_df = normalize_score_dataframe(state["scores_df"]).copy()
        cache_path = str(state["source"].get("cachePath") or DEFAULT_CACHE_PATH)
    try:
        result = export_selected_files_action(source_df, cache_path, destination_text)
    except ExportServiceError as error:
        return export_service_error_response(error)
    return JSONResponse(result.to_payload())


async def choose_folder(prompt: str) -> JSONResponse:
    try:
        folder = choose_folder_path(prompt)
    except DesktopActionUnsupported as exc:
        return api_error_response("desktopActionUnsupported", str(exc), status_code=501, params={"reason": str(exc)})
    except DesktopActionCancelled as exc:
        return api_error_response(
            "desktopActionCancelled",
            str(exc),
            status_code=400,
            params={"reason": str(exc)},
            cancelled=True,
        )
    except DesktopActionError as exc:
        return api_error_response("desktopActionFailed", str(exc), status_code=500, params={"reason": str(exc)})
    return JSONResponse({"folder": folder})


async def choose_folders(prompt: str) -> JSONResponse:
    try:
        folders = choose_folder_paths(prompt)
    except DesktopActionUnsupported as exc:
        return api_error_response("desktopActionUnsupported", str(exc), status_code=501, params={"reason": str(exc)})
    except DesktopActionCancelled as exc:
        return api_error_response(
            "desktopActionCancelled",
            str(exc),
            status_code=400,
            params={"reason": str(exc)},
            cancelled=True,
        )
    except DesktopActionError as exc:
        return api_error_response("desktopActionFailed", str(exc), status_code=500, params={"reason": str(exc)})
    return JSONResponse({"folders": folders, "folder": folders[0] if folders else ""})


async def api_pick_folder(request: Request) -> JSONResponse:
    if job_is_running(request_state_store(request)):
        return job_running_operation_response()
    return await choose_folder("选择照片目录")


async def api_pick_folders(request: Request) -> JSONResponse:
    if job_is_running(request_state_store(request)):
        return job_running_operation_response()
    return await choose_folders("选择照片目录")


async def api_pick_export_folder(request: Request) -> JSONResponse:
    if job_is_running(request_state_store(request)):
        return job_running_operation_response()
    return await choose_folder("选择导出目录")


async def api_reveal(request: Request) -> JSONResponse:
    payload = await request.json()
    try:
        path = Path(str(payload.get("path") or "")).expanduser().resolve()
    except Exception:
        return api_error_response("pathInvalid", "路径不可用", status_code=400)
    if not path.exists():
        return api_error_response("fileMissing", "文件不存在", status_code=404, params={"path": str(path)})
    if str(payload.get("purpose") or "") == "export":
        if not path.is_dir():
            return api_error_response(
                "exportDestinationNotDirectory", "导出目录不是文件夹。", status_code=400, params={"path": str(path)}
            )
        try:
            reveal_path_in_file_manager(path)
        except DesktopActionUnsupported as exc:
            return api_error_response(
                "desktopActionUnsupported", str(exc), status_code=501, params={"reason": str(exc)}
            )
        except DesktopActionError as exc:
            return api_error_response("desktopActionFailed", str(exc), status_code=500, params={"reason": str(exc)})
        return JSONResponse({"ok": True})
    state_store = request_state_store(request)
    with state_store.lock:
        state = state_store.data
        source = dict(state.get("source", {}))
        scores_df = normalize_score_dataframe(state["scores_df"]).copy()
    if not is_allowed_media_path(path, source, scores_df):
        return api_error_response(
            "revealOutsideSource", "只能定位当前照片来源中的文件。", status_code=403, params={"path": str(path)}
        )
    try:
        reveal_path_in_file_manager(path)
    except DesktopActionUnsupported as exc:
        return api_error_response("desktopActionUnsupported", str(exc), status_code=501, params={"reason": str(exc)})
    except DesktopActionError as exc:
        return api_error_response("desktopActionFailed", str(exc), status_code=500, params={"reason": str(exc)})
    return JSONResponse({"ok": True})


def route_handlers() -> WebRouteHandlers:
    return WebRouteHandlers(
        homepage=homepage,
        health=health,
        host_config=host_config,
        api_capabilities=api_capabilities,
        api_state=api_state,
        api_filter=api_filter,
        api_network=api_network,
        api_llm_config=api_llm_config,
        api_llm_models=api_llm_models,
        api_models=api_models,
        api_cache=api_cache,
        api_source_preview=api_source_preview,
        api_clear_history=api_clear_history,
        api_clear_local_data=api_clear_local_data,
        api_clear_model=api_clear_model,
        api_upload=api_upload,
        api_score=api_score,
        api_job_pause=api_job_pause,
        api_job_resume=api_job_resume,
        api_mark_photo=api_mark_photo,
        api_mark_color=api_mark_color,
        api_mark_status=api_mark_status,
        api_restore_marks=api_restore_marks,
        api_accept_marks=api_accept_marks,
        api_curation_history=api_curation_history,
        api_curation_undo=api_curation_undo,
        api_image=api_image,
        api_thumbnail=api_thumbnail,
        api_export=api_export,
        api_export_selected_csv=api_export_selected_csv,
        api_export_preflight=api_export_preflight,
        api_export_selected=api_export_selected,
        api_pick_folder=api_pick_folder,
        api_pick_folders=api_pick_folders,
        api_pick_export_folder=api_pick_export_folder,
        api_reveal=api_reveal,
    )


def create_routes(runtime_config: RuntimeConfig | None = None):
    config = runtime_config or current_runtime_config()
    return create_web_routes(route_handlers(), config)


routes = create_routes(RUNTIME_CONFIG)


def create_app(state_store: AppStateStore | None = None, runtime_config: RuntimeConfig | None = None) -> Starlette:
    config = runtime_config or current_runtime_config()
    app_state_store = state_store or APP_STATE
    return create_web_app(
        route_handlers(),
        config=config,
        state_store=app_state_store,
        job_service=APP_JOB_SERVICE if app_state_store is APP_STATE else None,
        debug=False,
    )


app = create_app()


def main(argv: list[str] | None = None) -> int:
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="启动Culvia Web 服务")
    parser.add_argument("--host", default=os.environ.get("CULVIA_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("CULVIA_PORT", "8501")))
    args = parser.parse_args(argv)
    uvicorn.run("culvia_app:app", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
