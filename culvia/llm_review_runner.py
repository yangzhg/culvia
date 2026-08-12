from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from culvia.app_state import AppStateStore
from culvia.insight_store import AnalysisInsight, AnalysisInsightMatch
from culvia.job_service import JobCancelled, ScoringJobService
from culvia.job_text import exception_text, text_ref
from culvia.llm_provenance import resolve_llm_score_dataframe
from culvia.llm_runtime import AnalyzerOutput
from culvia.schema import (
    CSV_COLUMNS,
    FIELD_GROUPS,
    LLM_REVIEW_FIELDS,
    LLM_REVIEW_GENERATION_COLUMN,
    MODEL_LLM_REVIEW,
    RECOMMENDATION_COLUMN,
    score_column,
)
from culvia.score_records import make_empty_score_record
from culvia.source_requests import source_request_from_payload


ScoreLlmReviewImage = Callable[[str | Path, str, Mapping[str, object] | None], AnalyzerOutput]


@dataclass(frozen=True)
class LlmReviewRunnerDependencies:
    default_cache_path: str
    refresh_persisted_llm_config: Callable[[str], None]
    llm_review_configured: Callable[[], bool]
    llm_review_status: Callable[[], Mapping[str, object]]
    sanitize_uploaded_paths: Callable[[object], list[Path]]
    scan_image_paths: Callable[[Sequence[str]], tuple[list[Path], list[dict[str, Any]]]]
    build_file_id: Callable[[str | Path], str]
    normalize_score_dataframe: Callable[[pd.DataFrame], pd.DataFrame]
    score_llm_review_image: ScoreLlmReviewImage
    apply_llm_review_scores: Callable[..., dict[str, object]]
    load_cache_records: Callable[[str | Path], pd.DataFrame]
    save_cache_records: Callable[[pd.DataFrame, str | Path, pd.DataFrame | None], None]
    load_latest_matching_analysis_insight_results: Callable[..., Mapping[str, AnalysisInsightMatch]]
    save_analysis_insights: Callable[[Sequence[AnalysisInsight], str | Path], None]
    thumbnail_url: Callable[[str, int], str]


def run_llm_review_job(
    job_id: str,
    payload: dict[str, Any],
    state_store: AppStateStore,
    job_service: ScoringJobService,
    dependencies: LlmReviewRunnerDependencies,
) -> None:
    job_service.bind_thread_job(job_id)
    try:
        source_request = source_request_from_payload(payload, default_cache_path=dependencies.default_cache_path)
        cache_path = source_request.cache_path
        dependencies.refresh_persisted_llm_config(cache_path)
        if not dependencies.llm_review_configured():
            job_service.update(
                running=False,
                phase="error",
                titleText=text_ref("jobText.llmNotConfigured"),
                detailText=text_ref("jobText.llmNotConfiguredDetail"),
                error="llmReviewNotConfigured",
            )
            job_service.reset_control(job_id)
            return

        uploaded_paths = dependencies.sanitize_uploaded_paths(source_request.uploaded_paths)
        status = dependencies.llm_review_status()
        provider = str(status.get("provider") or "")
        model = str(status.get("model") or "")
        prompt_version = str(status.get("promptVersion") or "")

        with state_store.lock:
            source_df = dependencies.normalize_score_dataframe(pd.DataFrame(state_store.data.get("scores_df"))).copy()

        warnings: list[dict[str, Any]] = []
        if source_df.empty:
            if source_request.mode == "uploads":
                paths = [path for path in uploaded_paths if path.exists()]
            else:
                paths, warnings = dependencies.scan_image_paths(source_request.folders)
            source_df = _records_for_paths(paths, dependencies)

        existing_cache = dependencies.load_cache_records(cache_path)
        file_ids = [str(value) for value in source_df.get("file_id", pd.Series(dtype=object)).tolist() if str(value)]
        current_insight_results = dependencies.load_latest_matching_analysis_insight_results(
            cache_path,
            file_ids=file_ids,
            analyzer_key=MODEL_LLM_REVIEW,
            provider=provider,
            model=model,
            model_version=model,
            prompt_version=prompt_version,
        )
        resolution = resolve_llm_score_dataframe(
            source_df,
            current_insight_results,
            generation_column=LLM_REVIEW_GENERATION_COLUMN,
            score_columns=tuple(score_column(field) for field in LLM_REVIEW_FIELDS),
        )
        source_df = dependencies.normalize_score_dataframe(resolution.dataframe)
        pending_rows = [
            row.to_dict()
            for _, row in source_df.iterrows()
            if _needs_llm_review(row.to_dict(), resolution.current_file_ids)
        ]

        total = len(pending_rows)
        job_service.update(
            running=True,
            kind="llm_review",
            phase="llm_review",
            titleText=text_ref("jobText.llmRunning"),
            detailText=text_ref("jobText.llmPendingDetail", count=total),
            progress=0.0 if total else 1.0,
            done=0,
            total=total,
            warnings=warnings,
            error="",
            errorText=None,
            modelProgress=None,
            currentFile="",
            currentPath="",
            currentThumb="",
            activeEvaluation="stage.llmReview",
            completedEvaluations=[],
            paused=False,
        )

        if not total:
            with state_store.lock:
                state_store.data["scores_df"] = source_df
            job_service.update(
                running=False,
                phase="done",
                titleText=text_ref("jobText.llmUpToDate"),
                detailText=text_ref("jobText.llmUpToDateDetail"),
                progress=1.0,
                activeEvaluation="",
            )
            job_service.reset_control(job_id)
            return

        scored_df = source_df.copy()
        for index, record in enumerate(pending_rows, start=1):
            job_service.raise_if_cancelled()
            path = Path(str(record.get("path") or ""))
            file_id = str(record.get("file_id") or "")
            job_service.update(
                phase="llm_review",
                titleText=text_ref("jobText.llmRunning"),
                detailText=text_ref("jobText.photoProgressDetail", index=index, total=total, file=path.name),
                progress=(index - 1) / max(total, 1),
                done=index - 1,
                total=total,
                currentFile=path.name,
                currentPath=str(path),
                currentThumb=dependencies.thumbnail_url(str(path), 180),
                activeEvaluation="stage.llmReview",
                completedEvaluations=[],
            )
            output = dependencies.score_llm_review_image(path, file_id, record)
            generation = _llm_output_generation(output)
            updated_record = dependencies.apply_llm_review_scores(
                dict(record),
                output.scores,
                generation=generation,
            )
            updated_df = _replace_record(scored_df, updated_record, dependencies.normalize_score_dataframe)
            dependencies.save_cache_records(updated_df, cache_path, existing_cache)
            scored_df = updated_df
            with state_store.lock:
                state_store.data["scores_df"] = scored_df
            if output.insights:
                dependencies.save_analysis_insights(output.insights, cache_path)
            job_service.update(
                detailText=text_ref("jobText.llmCompletedDetail", index=index, total=total, file=path.name),
                progress=index / max(total, 1),
                done=index,
                completedEvaluations=["stage.llmReview"],
            )

        job_service.update(
            running=False,
            phase="done",
            titleText=text_ref("jobText.llmDone"),
            detailText=text_ref("jobText.llmDoneDetail", count=total),
            progress=1.0,
            modelProgress=None,
            currentFile="",
            currentPath="",
            currentThumb="",
            activeEvaluation="",
            completedEvaluations=[],
            paused=False,
        )
        job_service.reset_control(job_id)
    except JobCancelled:
        job_service.update(
            running=False,
            phase="cancelled",
            titleText=text_ref("jobText.llmCancelled"),
            detailText=text_ref("jobText.llmCancelledDetail"),
            progress=0.0,
            modelProgress=None,
            currentFile="",
            currentPath="",
            currentThumb="",
            activeEvaluation="",
            completedEvaluations=[],
            paused=False,
        )
        job_service.reset_control(job_id)
    except Exception as exc:
        job_service.update(
            running=False,
            phase="error",
            titleText=text_ref("jobText.llmFailed"),
            detailText=text_ref("jobText.llmFailedDetail"),
            error=repr(exc),
            errorText=exception_text(exc),
            modelProgress=None,
            currentFile="",
            currentPath="",
            currentThumb="",
            activeEvaluation="",
            completedEvaluations=[],
            paused=False,
        )
        job_service.reset_control(job_id)
    finally:
        job_service.clear_thread_job()


def _records_for_paths(paths: Sequence[Path], dependencies: LlmReviewRunnerDependencies) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for path in paths:
        try:
            file_id = dependencies.build_file_id(path)
            rows.append(
                make_empty_score_record(
                    path,
                    file_id,
                    recommendation_column=RECOMMENDATION_COLUMN,
                    field_groups=FIELD_GROUPS,
                )
            )
        except Exception as exc:
            rows.append(
                make_empty_score_record(
                    path,
                    f"error:{path}",
                    recommendation_column=RECOMMENDATION_COLUMN,
                    field_groups=FIELD_GROUPS,
                    error=repr(exc),
                )
            )
    return dependencies.normalize_score_dataframe(pd.DataFrame(rows, columns=CSV_COLUMNS))


def _replace_record(
    frame: pd.DataFrame,
    record: Mapping[str, object],
    normalize_score_dataframe: Callable[[pd.DataFrame], pd.DataFrame],
) -> pd.DataFrame:
    current = normalize_score_dataframe(frame.copy())
    file_id = str(record.get("file_id") or "")
    if not file_id:
        return current
    if "file_id" in current.columns:
        matches = current["file_id"].astype(str) == file_id
        if matches.any():
            for key, value in record.items():
                if key not in current.columns:
                    current[key] = pd.NA
                current.loc[matches, key] = value
            return normalize_score_dataframe(current)
    return normalize_score_dataframe(pd.concat([current, pd.DataFrame([dict(record)])], ignore_index=True))


def _needs_llm_review(
    record: Mapping[str, object],
    current_file_ids: frozenset[str],
) -> bool:
    file_id = str(record.get("file_id") or "")
    if not file_id or file_id not in current_file_ids:
        return True
    for field in LLM_REVIEW_FIELDS:
        value = record.get(score_column(field, "0_10"))
        try:
            number = float(value)
        except Exception:
            return True
        if pd.isna(number):
            return True
    return False


def _llm_output_generation(output: AnalyzerOutput) -> float:
    generations = {
        float(insight.created_at)
        for insight in output.insights
        if insight.analyzer_key == MODEL_LLM_REVIEW and not pd.isna(insight.created_at)
    }
    if len(generations) != 1:
        raise ValueError("LLM review output must contain exactly one generation")
    return generations.pop()
