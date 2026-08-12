from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ContextManager, Protocol

import pandas as pd

from culvia.cache_schema import is_sqlite_cache_path
from culvia.insight_store import AnalysisInsight, AnalysisInsightMatch
from culvia.job_service import JobCancelled
from culvia.llm_provenance import resolve_llm_score_dataframe
from culvia.schema import (
    CSV_COLUMNS,
    LLM_REVIEW_FIELDS,
    LLM_REVIEW_GENERATION_COLUMN,
    MODEL_BASIC_TECHNICAL,
    MODEL_CLIP_AESTHETIC,
    MODEL_CLIP_IQA,
    MODEL_CORE_AESTHETIC,
    MODEL_LLM_REVIEW,
    RECOMMENDATION_COLUMN,
    score_column,
)

ProgressCallback = Callable[[int, int, Path, str], None]
ModelLoader = Callable[[str], object]
ResultPublisher = Callable[[pd.DataFrame], None]


class ScoreCheckpointWriter(Protocol):
    def upsert(self, records_df: pd.DataFrame) -> None: ...


@dataclass
class ScoreEntry:
    path: Path
    file_id: str
    cached_record: dict[str, object] | None
    pre_error: str | None
    needs: dict[str, bool]
    cache_dirty: bool = False

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
    open_checkpoint_writer: Callable[[str | Path], ContextManager[ScoreCheckpointWriter]]
    normalize_score_dataframe: Callable[[pd.DataFrame], pd.DataFrame]
    make_empty_record: Callable[[Path, str, str], dict[str, object]]
    score_aesthetic_image: Callable[[Path, object], dict[str, float]]
    apply_aesthetic_scores: Callable[[dict[str, object], dict[str, float]], dict[str, object]]
    analyze_technical_quality: Callable[[Path], dict[str, float]]
    apply_technical_scores: Callable[[dict[str, object], dict[str, float]], dict[str, object]]
    score_clip_reference_image: Callable[[Path, object], dict[str, float]]
    apply_clip_reference_scores: Callable[[dict[str, object], dict[str, float]], dict[str, object]]
    score_llm_review_image: Callable[..., Any]
    apply_llm_review_scores: Callable[..., dict[str, object]]
    load_latest_matching_analysis_insight_results: Callable[..., Mapping[str, AnalysisInsightMatch]]
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
    publish_result: ResultPublisher | None = None,
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
    current_llm_file_ids = _resolve_cached_llm_reviews(
        entries,
        cache_path=cache_path,
        use_cache=use_cache,
        dependencies=dependencies,
    )
    _refresh_llm_review_needs(entries, active_models, current_llm_file_ids=current_llm_file_ids)

    loaded_model: object | None = None
    if pending_core_count:
        loaded_model = model_loader(device)
        device = getattr(loaded_model, "device", device)

    loaded_clip_reference_model: object | None = None
    if pending_clip_count:
        loaded_clip_reference_model = clip_reference_loader(device)
        device = getattr(loaded_clip_reference_model, "device", device)

    rows: list[dict[str, object]] = []
    total = len(entries)
    checkpoint_context = dependencies.open_checkpoint_writer(cache_path) if cache_path else nullcontext(None)
    with checkpoint_context as checkpoint_writer:
        for index, entry in enumerate(entries, start=1):
            status = "cached" if entry.cached_record is not None and not entry.should_score else "scored"
            record_checkpointed = False
            if entry.pre_error:
                record = dependencies.make_empty_record(entry.path, entry.file_id, entry.pre_error)
                status = "error"
                _checkpoint_record(record, checkpoint_writer)
                record_checkpointed = True
            else:
                record = (
                    dict(entry.cached_record)
                    if entry.cached_record is not None
                    else dependencies.make_empty_record(entry.path, entry.file_id, "")
                )
                if progress_callback is not None and entry.should_score:
                    progress_callback(index - 1, total, entry.path, "started")
                if entry.should_score:
                    record["error"] = ""

                failure: Exception | None = None

                if entry.needs.get(MODEL_CORE_AESTHETIC):
                    try:
                        assert loaded_model is not None
                        record = dependencies.apply_aesthetic_scores(
                            record,
                            dependencies.score_aesthetic_image(entry.path, loaded_model),
                        )
                    except JobCancelled:
                        raise
                    except Exception as exc:
                        failure = exc
                    else:
                        _checkpoint_record(record, checkpoint_writer)
                        record_checkpointed = True
                        if progress_callback is not None:
                            progress_callback(index - 1, total, entry.path, "aesthetic_done")

                if failure is None and entry.needs.get(MODEL_BASIC_TECHNICAL):
                    try:
                        record = dependencies.apply_technical_scores(
                            record,
                            dependencies.analyze_technical_quality(entry.path),
                        )
                    except JobCancelled:
                        raise
                    except Exception as exc:
                        failure = exc
                    else:
                        status = (
                            "inspected"
                            if entry.cached_record is not None and not entry.needs.get(MODEL_CORE_AESTHETIC)
                            else status
                        )
                        _checkpoint_record(record, checkpoint_writer)
                        record_checkpointed = True
                        if progress_callback is not None:
                            progress_callback(index - 1, total, entry.path, "technical_done")

                if failure is None and (entry.needs.get(MODEL_CLIP_IQA) or entry.needs.get(MODEL_CLIP_AESTHETIC)):
                    try:
                        assert loaded_clip_reference_model is not None
                        clip_scores = dependencies.score_clip_reference_image(entry.path, loaded_clip_reference_model)
                        requested_clip_fields: set[str] = set()
                        for model_key in (MODEL_CLIP_IQA, MODEL_CLIP_AESTHETIC):
                            if entry.needs.get(model_key):
                                requested_clip_fields.update(dependencies.model_output_fields(model_key))
                        clip_scores = {key: value for key, value in clip_scores.items() if key in requested_clip_fields}
                        record = dependencies.apply_clip_reference_scores(record, clip_scores)
                    except JobCancelled:
                        raise
                    except Exception as exc:
                        failure = exc
                    else:
                        _checkpoint_record(record, checkpoint_writer)
                        record_checkpointed = True
                        if progress_callback is not None:
                            progress_callback(index - 1, total, entry.path, "clip_done")

                if failure is None and entry.needs.get(MODEL_LLM_REVIEW):
                    try:
                        llm_output = dependencies.score_llm_review_image(
                            entry.path,
                            file_id=entry.file_id,
                            score_context=record,
                        )
                        generation = _llm_output_generation(llm_output)
                        record = dependencies.apply_llm_review_scores(
                            record,
                            llm_output.scores,
                            generation=generation,
                        )
                    except JobCancelled:
                        raise
                    except Exception as exc:
                        failure = exc
                    else:
                        status = "reviewed"
                        try:
                            _checkpoint_record(record, checkpoint_writer)
                            record_checkpointed = True
                            if cache_path and llm_output.insights:
                                dependencies.save_analysis_insights(llm_output.insights, cache_path)
                        except Exception:
                            _clear_llm_review_scores(record)
                            _checkpoint_record(record, checkpoint_writer)
                            raise
                        if progress_callback is not None:
                            progress_callback(index - 1, total, entry.path, "llm_done")

                if failure is not None:
                    record["error"] = repr(failure)
                    status = "error"
                    _checkpoint_record(record, checkpoint_writer)
                    record_checkpointed = True
                elif not record_checkpointed and (entry.cache_dirty or entry.cached_record is None):
                    _checkpoint_record(record, checkpoint_writer)
                    record_checkpointed = True

            rows.append(record)

            if progress_callback is not None:
                progress_callback(index, total, entry.path, status)

    result_df = dependencies.normalize_score_dataframe(pd.DataFrame(rows))
    if publish_result is not None:
        publish_result(result_df)

    return result_df, device


def _checkpoint_record(
    record: Mapping[str, object],
    checkpoint_writer: ScoreCheckpointWriter | None,
) -> None:
    if checkpoint_writer is not None:
        checkpoint_writer.upsert(pd.DataFrame([dict(record)]))


def _clear_llm_review_scores(record: dict[str, object]) -> None:
    for field in LLM_REVIEW_FIELDS:
        record[score_column(field)] = pd.NA
    record[LLM_REVIEW_GENERATION_COLUMN] = pd.NA
    record[RECOMMENDATION_COLUMN] = pd.NA


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


def _resolve_cached_llm_reviews(
    entries: list[ScoreEntry],
    *,
    cache_path: str | Path | None,
    use_cache: bool,
    dependencies: ScoreImagePathDependencies,
) -> frozenset[str]:
    if not cache_path or not use_cache:
        return frozenset()

    matching_llm_review_results = _matching_llm_review_results(entries, cache_path, dependencies)
    cached_entries = [entry for entry in entries if not entry.pre_error and entry.cached_record is not None]
    resolution = resolve_llm_score_dataframe(
        pd.DataFrame([entry.cached_record for entry in cached_entries]),
        matching_llm_review_results,
        generation_column=LLM_REVIEW_GENERATION_COLUMN,
        score_columns=tuple(score_column(field) for field in LLM_REVIEW_FIELDS),
        derived_columns=(RECOMMENDATION_COLUMN,),
    )
    llm_identity_columns = (
        *(score_column(field) for field in LLM_REVIEW_FIELDS),
        LLM_REVIEW_GENERATION_COLUMN,
    )
    stale_file_ids = {
        entry.file_id
        for entry in cached_entries
        if entry.file_id not in resolution.current_file_ids
        and any(_has_cached_value(entry.cached_record.get(column)) for column in llm_identity_columns)
    }
    resolved_by_id = {
        str(row["file_id"]): row.to_dict()
        for _, row in resolution.dataframe.iterrows()
        if str(row.get("file_id") or "")
    }
    for entry in entries:
        if entry.cached_record is not None and entry.file_id in resolved_by_id:
            entry.cached_record = resolved_by_id[entry.file_id]
            entry.cache_dirty = entry.file_id in stale_file_ids
    return resolution.current_file_ids


def _refresh_llm_review_needs(
    entries: list[ScoreEntry],
    active_models: Iterable[str],
    *,
    current_llm_file_ids: frozenset[str],
) -> None:
    if MODEL_LLM_REVIEW not in set(active_models):
        return
    for entry in entries:
        if not entry.pre_error and entry.cached_record is not None and entry.file_id not in current_llm_file_ids:
            entry.needs[MODEL_LLM_REVIEW] = True


def _matching_llm_review_results(
    entries: Iterable[ScoreEntry],
    cache_path: str | Path,
    dependencies: ScoreImagePathDependencies,
) -> Mapping[str, AnalysisInsightMatch]:
    cache_path_obj = Path(cache_path).expanduser()
    if not is_sqlite_cache_path(cache_path_obj) or not cache_path_obj.exists():
        return {}

    current_prompt_version = dependencies.llm_review_prompt_version()
    current_provider = dependencies.llm_review_provider()
    current_model = dependencies.llm_review_model_name()
    file_ids = [entry.file_id for entry in entries if not entry.pre_error]
    return dependencies.load_latest_matching_analysis_insight_results(
        cache_path_obj,
        file_ids=file_ids,
        analyzer_key=MODEL_LLM_REVIEW,
        provider=current_provider,
        model=current_model,
        model_version=current_model,
        prompt_version=current_prompt_version,
    )


def _llm_output_generation(output: Any) -> float:
    generations = {
        float(insight.created_at)
        for insight in output.insights
        if insight.analyzer_key == MODEL_LLM_REVIEW and not pd.isna(insight.created_at)
    }
    if len(generations) != 1:
        raise ValueError("LLM review output must contain exactly one generation")
    return generations.pop()


def _has_cached_value(value: object) -> bool:
    if value is None:
        return False
    try:
        return not bool(pd.isna(value))
    except (TypeError, ValueError):
        return True
