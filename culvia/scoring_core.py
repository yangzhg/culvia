from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from culvia.cache_schema import is_sqlite_cache_path
from culvia.insight_store import AnalysisInsight
from culvia.schema import (
    CSV_COLUMNS,
    MODEL_CLIP_AESTHETIC,
    MODEL_CLIP_IQA,
    MODEL_CORE_AESTHETIC,
    MODEL_LLM_REVIEW,
    MODEL_BASIC_TECHNICAL,
)

ProgressCallback = Callable[[int, int, Path, str], None]
ModelLoader = Callable[[str], object]


@dataclass
class ScoreEntry:
    path: Path
    file_id: str
    cached_record: dict[str, object] | None
    pre_error: str | None
    needs: dict[str, bool]

    @property
    def should_score(self) -> bool:
        return bool(self.needs and any(self.needs.values()))


@dataclass(frozen=True)
class ScoreImagePathDependencies:
    build_file_id: Callable[[Path], str]
    get_device: Callable[[], str]
    normalize_selected_models: Callable[[Iterable[str] | None], list[str]]
    model_recompute_plan: Callable[[Mapping[str, object] | pd.Series | None, Iterable[str] | None], dict[str, bool]]
    model_output_fields: Callable[[str], tuple[str, ...]]
    load_cache_records: Callable[[str | Path], pd.DataFrame]
    save_cache_records: Callable[[pd.DataFrame, str | Path, pd.DataFrame | None], None]
    normalize_score_dataframe: Callable[[pd.DataFrame], pd.DataFrame]
    make_empty_record: Callable[[Path, str, str], dict[str, object]]
    score_aesthetic_image: Callable[[Path, object], dict[str, float]]
    apply_aesthetic_scores: Callable[[dict[str, object], dict[str, float]], dict[str, object]]
    analyze_technical_quality: Callable[[Path], dict[str, float]]
    apply_technical_scores: Callable[[dict[str, object], dict[str, float]], dict[str, object]]
    score_clip_reference_image: Callable[[Path, object], dict[str, float]]
    apply_clip_reference_scores: Callable[[dict[str, object], dict[str, float]], dict[str, object]]
    score_llm_review_image: Callable[..., Any]
    apply_llm_review_scores: Callable[[dict[str, object], Mapping[str, float]], dict[str, object]]
    load_analysis_insights: Callable[..., list[AnalysisInsight]]
    save_analysis_insights: Callable[[Iterable[AnalysisInsight], str | Path], None]
    llm_review_prompt_version: Callable[[], str]
    llm_review_provider: Callable[[], str]
    llm_review_model_name: Callable[[], str]


def score_image_paths(
    paths: Iterable[str | Path],
    *,
    dependencies: ScoreImagePathDependencies,
    cache_path: str | Path | None = None,
    use_cache: bool = True,
    model_loader: ModelLoader,
    clip_reference_loader: ModelLoader,
    selected_models: Iterable[str] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[pd.DataFrame, str]:
    path_list = [Path(path).expanduser() for path in paths]
    active_models = dependencies.normalize_selected_models(selected_models)
    device = dependencies.get_device()

    existing_cache = (
        dependencies.load_cache_records(cache_path) if cache_path and use_cache else pd.DataFrame(columns=CSV_COLUMNS)
    )
    cache_by_id = {
        str(row["file_id"]): row.to_dict()
        for _, row in existing_cache.iterrows()
        if str(row.get("file_id", "")).strip()
    }

    entries, pending_core_count, pending_clip_count = _build_entries(
        path_list,
        active_models,
        cache_by_id=cache_by_id,
        use_cache=use_cache,
        dependencies=dependencies,
    )
    _refresh_llm_review_needs(
        entries,
        active_models,
        cache_path=cache_path,
        use_cache=use_cache,
        dependencies=dependencies,
    )

    loaded_model: object | None = None
    if pending_core_count:
        loaded_model = model_loader(device)
        device = getattr(loaded_model, "device", device)

    loaded_clip_reference_model: object | None = None
    if pending_clip_count:
        loaded_clip_reference_model = clip_reference_loader(device)
        device = getattr(loaded_clip_reference_model, "device", device)

    rows: list[dict[str, object]] = []
    insights: list[AnalysisInsight] = []
    total = len(entries)
    for index, entry in enumerate(entries, start=1):
        status = "cached" if entry.cached_record is not None and not entry.should_score else "scored"
        if entry.pre_error:
            rows.append(dependencies.make_empty_record(entry.path, entry.file_id, entry.pre_error))
            status = "error"
        else:
            record = (
                dict(entry.cached_record)
                if entry.cached_record is not None
                else dependencies.make_empty_record(entry.path, entry.file_id, "")
            )
            try:
                if progress_callback is not None and entry.should_score:
                    progress_callback(index - 1, total, entry.path, "started")
                if entry.needs.get(MODEL_CORE_AESTHETIC):
                    assert loaded_model is not None
                    record = dependencies.apply_aesthetic_scores(
                        record,
                        dependencies.score_aesthetic_image(entry.path, loaded_model),
                    )
                    if progress_callback is not None:
                        progress_callback(index - 1, total, entry.path, "aesthetic_done")
                if entry.needs.get(MODEL_BASIC_TECHNICAL):
                    record = dependencies.apply_technical_scores(
                        record,
                        dependencies.analyze_technical_quality(entry.path),
                    )
                    status = (
                        "inspected"
                        if entry.cached_record is not None and not entry.needs.get(MODEL_CORE_AESTHETIC)
                        else status
                    )
                    if progress_callback is not None:
                        progress_callback(index - 1, total, entry.path, "technical_done")
                if entry.needs.get(MODEL_CLIP_IQA) or entry.needs.get(MODEL_CLIP_AESTHETIC):
                    assert loaded_clip_reference_model is not None
                    clip_scores = dependencies.score_clip_reference_image(entry.path, loaded_clip_reference_model)
                    requested_clip_fields: set[str] = set()
                    for model_key in (MODEL_CLIP_IQA, MODEL_CLIP_AESTHETIC):
                        if entry.needs.get(model_key):
                            requested_clip_fields.update(dependencies.model_output_fields(model_key))
                    clip_scores = {key: value for key, value in clip_scores.items() if key in requested_clip_fields}
                    record = dependencies.apply_clip_reference_scores(record, clip_scores)
                    if progress_callback is not None:
                        progress_callback(index - 1, total, entry.path, "clip_done")
                if entry.needs.get(MODEL_LLM_REVIEW):
                    llm_output = dependencies.score_llm_review_image(
                        entry.path,
                        file_id=entry.file_id,
                        score_context=record,
                    )
                    record = dependencies.apply_llm_review_scores(record, llm_output.scores)
                    insights.extend(llm_output.insights)
                    status = "reviewed"
                    if progress_callback is not None:
                        progress_callback(index - 1, total, entry.path, "llm_done")
                rows.append(record)
            except Exception as exc:
                record["error"] = repr(exc)
                rows.append(record)
                status = "error"

        if progress_callback is not None:
            progress_callback(index, total, entry.path, status)

    result_df = dependencies.normalize_score_dataframe(pd.DataFrame(rows))
    if cache_path:
        dependencies.save_cache_records(result_df, cache_path, existing_cache)
        if insights:
            dependencies.save_analysis_insights(insights, cache_path)

    return result_df, device


def _build_entries(
    path_list: Iterable[Path],
    active_models: Iterable[str],
    *,
    cache_by_id: Mapping[str, dict[str, object]],
    use_cache: bool,
    dependencies: ScoreImagePathDependencies,
) -> tuple[list[ScoreEntry], int, int]:
    entries: list[ScoreEntry] = []
    pending_core_count = 0
    pending_clip_count = 0
    for path in path_list:
        try:
            file_id = dependencies.build_file_id(path)
        except Exception as exc:
            entries.append(ScoreEntry(path, str(path), None, f"stat_failed: {exc!r}", {}))
            continue

        cached_record = cache_by_id.get(file_id) if use_cache else None
        needs = dependencies.model_recompute_plan(cached_record, active_models)
        if needs[MODEL_CORE_AESTHETIC]:
            pending_core_count += 1
        if needs[MODEL_CLIP_IQA] or needs[MODEL_CLIP_AESTHETIC]:
            pending_clip_count += 1
        entries.append(ScoreEntry(path, file_id, cached_record, None, needs))

    return entries, pending_core_count, pending_clip_count


def _refresh_llm_review_needs(
    entries: list[ScoreEntry],
    active_models: Iterable[str],
    *,
    cache_path: str | Path | None,
    use_cache: bool,
    dependencies: ScoreImagePathDependencies,
) -> None:
    active_model_set = set(active_models)
    if MODEL_LLM_REVIEW not in active_model_set or not cache_path or not use_cache:
        return

    matching_llm_review_file_ids = _matching_llm_review_file_ids(entries, cache_path, dependencies)
    for entry in entries:
        if (
            not entry.pre_error
            and entry.cached_record is not None
            and not entry.needs.get(MODEL_LLM_REVIEW)
            and entry.file_id not in matching_llm_review_file_ids
        ):
            entry.needs[MODEL_LLM_REVIEW] = True


def _matching_llm_review_file_ids(
    entries: Iterable[ScoreEntry],
    cache_path: str | Path,
    dependencies: ScoreImagePathDependencies,
) -> set[str]:
    cache_path_obj = Path(cache_path).expanduser()
    if not is_sqlite_cache_path(cache_path_obj) or not cache_path_obj.exists():
        return set()

    current_prompt_version = dependencies.llm_review_prompt_version()
    current_provider = dependencies.llm_review_provider()
    current_model = dependencies.llm_review_model_name()
    file_ids = [entry.file_id for entry in entries if not entry.pre_error]
    matching_file_ids: set[str] = set()
    for insight in dependencies.load_analysis_insights(cache_path_obj, file_ids=file_ids):
        if (
            insight.analyzer_key == MODEL_LLM_REVIEW
            and insight.provider == current_provider
            and insight.model == current_model
            and insight.model_version == current_model
            and insight.prompt_version == current_prompt_version
        ):
            matching_file_ids.add(insight.file_id)
    return matching_file_ids
