from __future__ import annotations

import os
import sqlite3
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterable

import pandas as pd

from culvia.cache_schema import (
    APP_CONFIG_TABLE,
    INSIGHT_COLUMNS,
    INSIGHT_TABLE,
    LLM_CONFIG_STORAGE_KEYS,
    SQLITE_CACHE_EXTENSIONS,
    SOURCE_CONFIG_STORAGE_KEYS,
    json_dumps,
    json_loads,
)
from culvia.cache_records import ScoreCacheStore
from culvia.image_io import (
    HEIF_AVAILABLE,
    bounded_image_cache_size,
    ensure_resized_image_cache,
    image_file_data_url,
    open_image_rgb,
    resized_image_cache_path,
)
from culvia.insight_store import AnalysisInsight, AnalysisInsightStore, AppConfigStore
from culvia.llm_config import (
    LLMConfigEnvironment,
    LLM_CONFIG_FIELDS,
    PERSISTED_LLM_CONFIG,
    SESSION_LLM_CONFIG,
    active_llm_config as _active_llm_config,
    clean_llm_config as _clean_llm_config,
    clear_secure_llm_config,
    clear_session_llm_config,
    llm_config_layers as _llm_config_layers,
    llm_config_source as _llm_config_source,
    llm_review_endpoint as _llm_config_review_endpoint,
    llm_review_input_mode as _llm_config_review_input_mode,
    llm_review_max_image_size as _llm_config_review_max_image_size,
    llm_review_prompt_text as _llm_config_review_prompt_text,
    llm_review_timeout as _llm_config_review_timeout,
    mask_llm_api_key,
    set_persisted_llm_config,
    set_secure_llm_config,
    set_session_llm_config,
)
from culvia.llm_runtime import (
    AnalyzerOutput,
    build_llm_image_prompt,
    build_llm_review_request_payload,
    build_llm_text_only_prompt,
    build_score_context_lines,
    llm_prompt_signature,
    post_llm_review_request,
    score_llm_review_image as run_llm_review_image,
)
from culvia.local_model_scoring import (
    CLIP_PROMPT_PAIRS,
    LoadedAestheticModel,
    LoadedClipReferenceModel,
    build_aesthetic_scorer as _build_aesthetic_scorer,
    load_torch_object as _load_torch_object,
    normalize_torch_features as _normalize_torch_features,
    score_aesthetic_image as _score_aesthetic_image,
    score_clip_reference_image as _score_clip_reference_image,
    state_dict_from_loaded_object as _state_dict_from_loaded_object,
    torch_feature_tensor as _torch_feature_tensor,
)
from culvia.model_loaders import get_device, load_clip_reference_model, load_model
from culvia.model_files import (
    APP_MODEL_CACHE_DIR,
    CLIP_REFERENCE_MODEL_ID,
    CLIP_REFERENCE_MODEL_REPO_DIR,
    CLIP_REFERENCE_REQUIRED_CACHE_FILES,
    MODEL_CACHE_REPO_DIR,
    MODEL_ID,
    MODEL_REQUIRED_CACHE_FILES,
    download_hf_file as _download_hf_file,
    download_hf_repo_file as _download_hf_repo_file,
    download_model_pt_with_progress as _download_model_pt_with_progress,
    ensure_clip_reference_model_files,
    ensure_model_files,
    format_bytes,
    format_duration,
    get_active_hf_download_size,
    get_active_model_download_size,
    get_app_model_part_path,
    get_app_model_path,
    get_clip_reference_cache_status,
    get_hf_repo_cache_dir,
    get_hf_snapshot_status,
    get_huggingface_cache_root,
    get_model_assets_dir,
    get_model_cache_status,
    request_headers as _request_headers,
    sanitize_proxy_env_for_httpx,
)
from culvia.photo_scan import SUPPORTED_EXTENSIONS, build_file_id, scan_image_paths
from culvia.llm_review import (
    extract_json_mapping,
    first_text_choice,
    llm_float,
    llm_review_scores,
    llm_suggestions,
    strip_json_fence,
)
from culvia.llm_prompt import (
    LLM_REVIEW_SYSTEM_PROMPT,
    LLM_REVIEW_TEXT_SYSTEM_PROMPT,
    LLM_REVIEW_USER_PROMPT,
)
from culvia.schema import (
    AESTHETIC_REFERENCE_FIELDS,
    AESTHETIC_REFERENCE_GROUP,
    AESTHETIC_REFERENCE_LABELS,
    BASE_RECORD_COLUMNS,
    CSV_COLUMNS,
    CORE_AESTHETIC_GROUP,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_PROMPT_PRESET,
    DEFAULT_SELECTED_MODELS,
    FIELD_GROUPS,
    FIELD_GROUP_BY_KEY,
    LLM_OVERALL_AESTHETIC_WEIGHT,
    LLM_OVERALL_TECHNICAL_WEIGHT,
    LLM_PROMPT_PRESETS,
    LLM_REVIEW_FIELDS,
    LLM_REVIEW_GROUP,
    LLM_REVIEW_LABELS,
    LLM_REVIEW_PROMPT_VERSION,
    MODEL_BASIC_TECHNICAL,
    MODEL_CAPABILITIES,
    MODEL_CLIP_AESTHETIC,
    MODEL_CLIP_IQA,
    MODEL_CORE_AESTHETIC,
    MODEL_QUALITY_GROUP,
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
    TECHNICAL_GROUP,
    TECHNICAL_LABELS,
    ModelCapability,
    ScoreFieldGroup,
    field_group_for_model,
    has_score_columns,
    missing_model_output_columns,
    missing_score_columns,
    model_output_columns,
    model_output_fields,
    model_recompute_plan,
    normalize_llm_prompt_preset,
    normalize_selected_models,
    score_column,
    score_columns_for_fields,
)
from culvia.source_requests import normalize_cache_path, normalize_source_folders, normalize_source_mode
from culvia.score_records import (
    apply_dual_scale_scores,
    apply_single_scale_scores,
    make_empty_score_record,
)
from culvia.scoring_core import (
    ScoreImagePathDependencies,
    score_image_paths as _run_score_image_paths,
)
from culvia.settings import (
    analysis_image_cache_dir,
    default_cache_path,
    default_output_path,
    default_photo_dirs,
    user_cache_dir,
)
from culvia.technical_metrics import analyze_technical_quality

if TYPE_CHECKING:
    from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_DATA_DIR = "CULVIA_DATA_DIR"
ENV_CACHE_PATH = "CULVIA_CACHE_PATH"
ENV_OUTPUT_PATH = "CULVIA_OUTPUT_PATH"
ENV_PHOTO_DIRS = "CULVIA_PHOTO_DIRS"
ENV_LLM_API_KEY = "CULVIA_LLM_API_KEY"
ENV_LLM_ENDPOINT = "CULVIA_LLM_ENDPOINT"
ENV_LLM_BASE_URL = "CULVIA_LLM_BASE_URL"
ENV_LLM_MODEL = "CULVIA_LLM_MODEL"
ENV_LLM_PROVIDER = "CULVIA_LLM_PROVIDER"
ENV_LLM_TIMEOUT = "CULVIA_LLM_TIMEOUT"
ENV_LLM_MAX_IMAGE_SIZE = "CULVIA_LLM_MAX_IMAGE_SIZE"
ENV_LLM_INPUT_MODE = "CULVIA_LLM_INPUT_MODE"
ENV_LLM_PROMPT_PRESET = "CULVIA_LLM_PROMPT_PRESET"
ENV_LLM_CUSTOM_PROMPT = "CULVIA_LLM_CUSTOM_PROMPT"
LLM_CONFIG_ENV = LLMConfigEnvironment(
    api_key=ENV_LLM_API_KEY,
    base_url=ENV_LLM_BASE_URL,
    endpoint=ENV_LLM_ENDPOINT,
    model=ENV_LLM_MODEL,
    provider=ENV_LLM_PROVIDER,
    input_mode=ENV_LLM_INPUT_MODE,
    prompt_preset=ENV_LLM_PROMPT_PRESET,
    custom_prompt=ENV_LLM_CUSTOM_PROMPT,
)


def _env_path(name: str, fallback: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else fallback


def _env_path_list(name: str, fallback: Iterable[Path]) -> list[str]:
    value = os.environ.get(name)
    if not value:
        return [str(path) for path in fallback]
    return [str(Path(part).expanduser()) for part in value.split(os.pathsep) if part.strip()]


def _default_app_data_dir() -> Path:
    if (PROJECT_ROOT / "pyproject.toml").exists() and (PROJECT_ROOT / "web").exists():
        return PROJECT_ROOT
    return Path.home() / ".culvia"


APP_DATA_DIR = _env_path(ENV_DATA_DIR, user_cache_dir())
ANALYSIS_IMAGE_CACHE_DIR = analysis_image_cache_dir()
MODEL_INPUT_MAX_SIZE = 768
LLM_INPUT_MAX_SIZE = 1024
DEFAULT_LLM_ENDPOINT = "https://api.openai.com/v1/chat/completions"
ANALYSIS_IMAGE_CACHE_LOCK = threading.Lock()
DEFAULT_PHOTO_DIRS = default_photo_dirs()
DEFAULT_CACHE_PATH = default_cache_path()
DEFAULT_OUTPUT_PATH = default_output_path()

ProgressCallback = Callable[[int, int, Path, str], None]
ModelDownloadCallback = Callable[[str, int, int, str, dict[str, object]], None]
ModelLoader = Callable[[str], "LoadedAestheticModel"]
ClipReferenceLoader = Callable[[str], "LoadedClipReferenceModel"]


def llm_config_layers() -> dict[str, dict[str, str]]:
    return _llm_config_layers(os.environ, LLM_CONFIG_ENV)


def active_llm_config() -> dict[str, str]:
    return _active_llm_config(llm_config_layers())


def llm_config_source(field: str) -> str:
    return _llm_config_source(field, llm_config_layers())


def llm_review_api_key() -> str:
    return active_llm_config().get("api_key", "")


def llm_review_base_url() -> str:
    return active_llm_config().get("base_url", "")


def llm_review_endpoint() -> str:
    return _llm_config_review_endpoint(active_llm_config(), DEFAULT_LLM_ENDPOINT)


def llm_review_model_name() -> str:
    return active_llm_config().get("model") or DEFAULT_LLM_MODEL


def llm_review_provider() -> str:
    return active_llm_config().get("provider") or "openai-compatible"


def llm_review_prompt_preset() -> str:
    return normalize_llm_prompt_preset(active_llm_config().get("prompt_preset"))


def llm_review_custom_prompt() -> str:
    return active_llm_config().get("custom_prompt", "")


def llm_review_prompt_text() -> str:
    return _llm_config_review_prompt_text(
        llm_review_prompt_preset(),
        LLM_PROMPT_PRESETS,
        llm_review_custom_prompt(),
    )


def llm_review_prompt_version() -> str:
    return llm_prompt_signature(
        LLM_REVIEW_PROMPT_VERSION,
        llm_review_input_mode(),
        llm_review_prompt_preset(),
        llm_review_prompt_text(),
    )


def llm_review_input_mode() -> str:
    return _llm_config_review_input_mode(active_llm_config())


def llm_review_timeout() -> float:
    return _llm_config_review_timeout(os.environ, ENV_LLM_TIMEOUT)


def llm_review_max_image_size() -> int:
    return _llm_config_review_max_image_size(
        os.environ,
        ENV_LLM_MAX_IMAGE_SIZE,
        LLM_INPUT_MAX_SIZE,
        maximum=1600,
    )


def llm_review_configured() -> bool:
    return bool(llm_review_api_key())


def llm_review_status() -> dict[str, object]:
    layers = llm_config_layers()
    return {
        "configured": llm_review_configured(),
        "provider": llm_review_provider(),
        "model": llm_review_model_name(),
        "baseUrl": llm_review_base_url(),
        "endpoint": llm_review_endpoint(),
        "inputMode": llm_review_input_mode(),
        "promptPreset": llm_review_prompt_preset(),
        "customPrompt": llm_review_custom_prompt(),
        "promptVersion": LLM_REVIEW_PROMPT_VERSION,
        "sources": {
            "apiKey": llm_config_source("api_key"),
            "baseUrl": llm_config_source("base_url"),
            "endpoint": llm_config_source("endpoint"),
            "model": llm_config_source("model"),
            "inputMode": llm_config_source("input_mode"),
            "promptPreset": llm_config_source("prompt_preset"),
            "customPrompt": llm_config_source("custom_prompt"),
        },
        "layers": {
            name: {key: ("***" if key == "api_key" else value) for key, value in layer.items()}
            for name, layer in layers.items()
        },
    }


TEXT_COLUMNS = set(BASE_RECORD_COLUMNS)
SCORE_CACHE_STORE = ScoreCacheStore(
    csv_columns=tuple(CSV_COLUMNS),
    text_columns=frozenset(TEXT_COLUMNS),
    field_groups=tuple(FIELD_GROUPS),
    recommendation_column=RECOMMENDATION_COLUMN,
)


def normalize_score_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    return SCORE_CACHE_STORE.normalize_dataframe(df)


def _ensure_cache_schema(conn: sqlite3.Connection) -> None:
    SCORE_CACHE_STORE.ensure_schema(conn)


ANALYSIS_INSIGHT_STORE = AnalysisInsightStore(schema_ensurer=_ensure_cache_schema)
LLM_CONFIG_STORE = AppConfigStore(schema_ensurer=_ensure_cache_schema, clean_config=_clean_llm_config)


def _clean_source_config(config: Mapping[str, object] | None) -> dict[str, str]:
    source = dict(config or {})
    if not any(key in source for key in ("mode", "folders", "folders_json", "cache_path", "cachePath")):
        return {}
    mode = normalize_source_mode(source.get("mode"))
    folders_value = source.get("folders")
    if folders_value is None:
        folders_value = json_loads(source.get("folders_json"), [])
    folders = normalize_source_folders(folders_value)
    cleaned: dict[str, str] = {"mode": mode, "folders_json": json_dumps(folders)}
    cache_path = str(source.get("cache_path") or source.get("cachePath") or "").strip()
    if cache_path:
        cleaned["cache_path"] = cache_path
    return cleaned


SOURCE_CONFIG_STORE = AppConfigStore(
    schema_ensurer=_ensure_cache_schema,
    clean_config=_clean_source_config,
    storage_keys=SOURCE_CONFIG_STORAGE_KEYS,
)


def _load_cache_sqlite(cache_path: str | Path) -> pd.DataFrame:
    return SCORE_CACHE_STORE.load_sqlite(cache_path)


def _save_cache_sqlite(
    current_df: pd.DataFrame, cache_path: str | Path, existing_df: pd.DataFrame | None = None
) -> None:
    SCORE_CACHE_STORE.save_sqlite(current_df, cache_path, existing_df)


def save_analysis_insights(insights: Iterable[AnalysisInsight], cache_path: str | Path) -> None:
    ANALYSIS_INSIGHT_STORE.save(insights, cache_path)


def load_analysis_insights(cache_path: str | Path, file_ids: Iterable[str] | None = None) -> list[AnalysisInsight]:
    return ANALYSIS_INSIGHT_STORE.load(cache_path, file_ids=file_ids)


def load_llm_config_from_sqlite(cache_path: str | Path) -> dict[str, str]:
    return LLM_CONFIG_STORE.load(cache_path)


def save_llm_config_to_sqlite(config: Mapping[str, object], cache_path: str | Path) -> dict[str, str]:
    return LLM_CONFIG_STORE.save(config, cache_path)


def load_source_config_from_sqlite(cache_path: str | Path) -> dict[str, object]:
    loaded = SOURCE_CONFIG_STORE.load(cache_path)
    folders = normalize_source_folders(json_loads(loaded.get("folders_json"), []))
    if not loaded and not folders:
        return {}
    config: dict[str, object] = {
        "mode": normalize_source_mode(loaded.get("mode")),
        "folders": folders,
    }
    if loaded.get("cache_path"):
        try:
            config["cachePath"] = normalize_cache_path(loaded.get("cache_path"), default_cache_path=cache_path)
        except ValueError:
            config["cachePath"] = str(cache_path)
    return config


def save_source_config_to_sqlite(config: Mapping[str, object], cache_path: str | Path) -> dict[str, object]:
    if normalize_source_mode(config.get("mode")) != "folders":
        return load_source_config_from_sqlite(cache_path)
    saved = SOURCE_CONFIG_STORE.save(
        {
            "mode": config.get("mode"),
            "folders": config.get("folders"),
            "cache_path": config.get("cachePath") or cache_path,
        },
        cache_path,
    )
    return load_source_config_from_sqlite(cache_path) if saved else {}


def load_cache_records(cache_path: str | Path) -> pd.DataFrame:
    return SCORE_CACHE_STORE.load(cache_path)


def save_cache_records(
    current_df: pd.DataFrame, cache_path: str | Path, existing_df: pd.DataFrame | None = None
) -> None:
    SCORE_CACHE_STORE.save(current_df, cache_path, existing_df)


def cached_resized_image_path(path: str | Path, max_size: int = MODEL_INPUT_MAX_SIZE) -> Path:
    return ensure_resized_image_cache(
        path,
        ANALYSIS_IMAGE_CACHE_DIR,
        max_size,
        minimum_size=224,
        maximum_size=1600,
        quality=90,
        lock=ANALYSIS_IMAGE_CACHE_LOCK,
    )


def open_model_image_rgb(path: str | Path, max_size: int = MODEL_INPUT_MAX_SIZE) -> Image.Image:
    return open_image_rgb(cached_resized_image_path(path, max_size=max_size))


def _llm_image_data_url(path: str | Path) -> str:
    image_path = cached_resized_image_path(path, max_size=llm_review_max_image_size())
    return image_file_data_url(image_path)


_strip_json_fence = strip_json_fence
_extract_json_mapping = extract_json_mapping
_first_text_choice = first_text_choice
_llm_float = llm_float
_llm_suggestions = llm_suggestions


def _llm_review_scores(raw: Mapping[str, object]) -> dict[str, float]:
    return llm_review_scores(
        raw,
        aesthetic_weight=LLM_OVERALL_AESTHETIC_WEIGHT,
        technical_weight=LLM_OVERALL_TECHNICAL_WEIGHT,
    )


def _score_context_lines(record: Mapping[str, object] | None) -> list[str]:
    return build_score_context_lines(
        record,
        field_groups=FIELD_GROUPS,
        excluded_group_key=LLM_REVIEW_GROUP.key,
        score_column=score_column,
    )


def _llm_text_only_prompt(path: str | Path, score_context: Mapping[str, object] | None) -> str:
    return build_llm_text_only_prompt(
        path,
        score_context=score_context,
        score_context_lines=_score_context_lines,
        prompt_text=llm_review_prompt_text(),
    )


def _llm_image_prompt() -> str:
    return build_llm_image_prompt(llm_review_prompt_text())


def _llm_request_payload(path: str | Path, score_context: Mapping[str, object] | None = None) -> dict[str, object]:
    return build_llm_review_request_payload(
        path,
        model=llm_review_model_name(),
        input_mode=llm_review_input_mode(),
        prompt_text=llm_review_prompt_text(),
        score_context=score_context,
        score_context_lines=_score_context_lines,
        image_data_url=_llm_image_data_url,
    )


def _post_llm_request(payload: dict[str, object]) -> dict[str, object]:
    return post_llm_review_request(
        payload,
        api_key=llm_review_api_key(),
        endpoint=llm_review_endpoint(),
        timeout=llm_review_timeout(),
    )


def score_llm_review_image(
    path: str | Path,
    file_id: str = "",
    score_context: Mapping[str, object] | None = None,
) -> AnalyzerOutput:
    return run_llm_review_image(
        path,
        file_id=file_id,
        score_context=score_context,
        analyzer_key=MODEL_LLM_REVIEW,
        provider=llm_review_provider(),
        model=llm_review_model_name(),
        prompt_version=llm_review_prompt_version(),
        prompt_text=llm_review_prompt_text(),
        input_mode=llm_review_input_mode(),
        score_context_lines=_score_context_lines,
        image_data_url=_llm_image_data_url,
        api_key=llm_review_api_key(),
        endpoint=llm_review_endpoint(),
        timeout=llm_review_timeout(),
        aesthetic_weight=LLM_OVERALL_AESTHETIC_WEIGHT,
        technical_weight=LLM_OVERALL_TECHNICAL_WEIGHT,
    )


def _clamp_score(value: float) -> float:
    return max(0.0, min(float(value), 10.0))


def _has_technical_scores(record: dict[str, object] | pd.Series | None) -> bool:
    return has_score_columns(record, model_output_columns(MODEL_BASIC_TECHNICAL))


def _has_score_columns(record: dict[str, object] | pd.Series | None, columns: Iterable[str]) -> bool:
    return has_score_columns(record, columns)


def _make_empty_record(path: Path, file_id: str, error: str = "") -> dict[str, object]:
    return make_empty_score_record(
        path,
        file_id,
        recommendation_column=RECOMMENDATION_COLUMN,
        field_groups=FIELD_GROUPS,
        error=error,
    )


def score_image(path: str | Path, loaded_model: LoadedAestheticModel) -> dict[str, float]:
    return _score_aesthetic_image(
        path,
        loaded_model,
        score_fields=SCORE_FIELDS,
        image_opener=open_model_image_rgb,
    )


def score_clip_reference_image(path: str | Path, loaded_model: LoadedClipReferenceModel) -> dict[str, float]:
    return _score_clip_reference_image(
        path,
        loaded_model,
        image_opener=open_model_image_rgb,
        clamp_score=_clamp_score,
    )


def _record_from_scores(path: Path, file_id: str, scores: dict[str, float]) -> dict[str, object]:
    record = _make_empty_record(path, file_id)
    return _apply_aesthetic_scores(record, scores)


def _apply_aesthetic_scores(record: dict[str, object], scores: dict[str, float]) -> dict[str, object]:
    return apply_dual_scale_scores(
        record,
        fields=SCORE_FIELDS,
        scores=scores,
        source_scale="0_5",
        target_scale="0_10",
        multiplier=2.0,
    )


def _apply_technical_scores(record: dict[str, object], scores: dict[str, float]) -> dict[str, object]:
    return apply_single_scale_scores(record, fields=TECHNICAL_FIELDS, scores=scores)


def _apply_clip_reference_scores(record: dict[str, object], scores: dict[str, float]) -> dict[str, object]:
    return apply_single_scale_scores(
        record,
        fields=MODEL_QUALITY_FIELDS + AESTHETIC_REFERENCE_FIELDS,
        scores=scores,
        only_present=True,
    )


def _apply_llm_review_scores(record: dict[str, object], scores: Mapping[str, float]) -> dict[str, object]:
    return apply_single_scale_scores(record, fields=LLM_REVIEW_FIELDS, scores=scores, only_present=True)


def apply_llm_review_scores(record: dict[str, object], scores: Mapping[str, float]) -> dict[str, object]:
    return _apply_llm_review_scores(record, scores)


def _score_image_path_dependencies() -> ScoreImagePathDependencies:
    return ScoreImagePathDependencies(
        build_file_id=build_file_id,
        get_device=get_device,
        normalize_selected_models=normalize_selected_models,
        model_recompute_plan=model_recompute_plan,
        model_output_fields=model_output_fields,
        load_cache_records=load_cache_records,
        save_cache_records=save_cache_records,
        normalize_score_dataframe=normalize_score_dataframe,
        make_empty_record=_make_empty_record,
        score_aesthetic_image=score_image,
        apply_aesthetic_scores=_apply_aesthetic_scores,
        analyze_technical_quality=analyze_technical_quality,
        apply_technical_scores=_apply_technical_scores,
        score_clip_reference_image=score_clip_reference_image,
        apply_clip_reference_scores=_apply_clip_reference_scores,
        score_llm_review_image=score_llm_review_image,
        apply_llm_review_scores=_apply_llm_review_scores,
        load_analysis_insights=load_analysis_insights,
        save_analysis_insights=save_analysis_insights,
        llm_review_prompt_version=llm_review_prompt_version,
        llm_review_provider=llm_review_provider,
        llm_review_model_name=llm_review_model_name,
    )


def score_image_paths(
    paths: Iterable[str | Path],
    cache_path: str | Path | None = None,
    use_cache: bool = True,
    model_loader: ModelLoader = load_model,
    clip_reference_loader: ClipReferenceLoader = load_clip_reference_model,
    selected_models: Iterable[str] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[pd.DataFrame, str]:
    return _run_score_image_paths(
        paths,
        dependencies=_score_image_path_dependencies(),
        cache_path=cache_path,
        use_cache=use_cache,
        model_loader=model_loader,
        clip_reference_loader=clip_reference_loader,
        selected_models=selected_models,
        progress_callback=progress_callback,
    )


def write_csv(df: pd.DataFrame, output_path: str | Path) -> None:
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    normalize_score_dataframe(df).to_csv(path, index=False, encoding="utf-8-sig")


from culvia.batch_cli import main, parse_args, print_top_scores


if __name__ == "__main__":
    raise SystemExit(main())
