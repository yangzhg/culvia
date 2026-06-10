from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import pandas as pd

from culvia.app_state import AppStateStore
from culvia.job_service import JobCancelled, ScoringJobService
from culvia.job_text import exception_text, text_ref
from culvia.scoring_progress import scoring_progress
from culvia.source_requests import source_request_from_payload


ModelLoader = Callable[[str, str, ScoringJobService], object]
ScoreImagePaths = Callable[..., tuple[pd.DataFrame, str]]


@dataclass(frozen=True)
class ScoringRunnerDependencies:
    default_cache_path: str
    empty_score_columns: Sequence[str]
    llm_review_model_key: str
    sanitize_uploaded_paths: Callable[[object], list[Path]]
    normalize_network_mode: Callable[[object], str]
    normalize_selected_models: Callable[[object], list[str]]
    refresh_persisted_llm_config: Callable[[str], None]
    save_source_config: Callable[[dict[str, Any], str], Any]
    llm_review_configured: Callable[[], bool]
    scan_image_paths: Callable[[Sequence[str]], tuple[list[Path], list[dict[str, Any]]]]
    score_image_paths: ScoreImagePaths
    model_loader: ModelLoader
    clip_reference_loader: ModelLoader
    thumbnail_url: Callable[[str, int], str]
    device_key: Callable[[str | None], str]


def run_scoring_job(
    job_id: str,
    payload: dict[str, Any],
    state_store: AppStateStore,
    job_service: ScoringJobService,
    dependencies: ScoringRunnerDependencies,
) -> None:
    job_service.bind_thread_job(job_id)
    try:
        source_request = source_request_from_payload(payload, default_cache_path=dependencies.default_cache_path)
    except Exception as exc:
        job_service.update(
            running=False,
            phase="error",
            titleText=text_ref("jobText.scoringFailed"),
            detailText=text_ref("jobText.checkSourceOrCache"),
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
        job_service.clear_thread_job()
        return
    mode = source_request.mode
    folders = source_request.folders
    cache_path = source_request.cache_path
    uploaded_paths = dependencies.sanitize_uploaded_paths(source_request.uploaded_paths)
    network_mode = dependencies.normalize_network_mode(payload.get("networkMode"))
    selected_models = dependencies.normalize_selected_models(payload.get("selectedModels"))
    dependencies.refresh_persisted_llm_config(cache_path)
    if dependencies.llm_review_model_key in selected_models and not dependencies.llm_review_configured():
        selected_models = [model_key for model_key in selected_models if model_key != dependencies.llm_review_model_key]

    _write_source_state(state_store, mode, folders, cache_path, uploaded_paths, network_mode, selected_models)
    dependencies.save_source_config(_source_payload(mode, folders, cache_path, uploaded_paths), cache_path)

    job_service.update(
        running=True,
        phase="scanning",
        titleText=text_ref("jobText.organizingPhotos"),
        detailText=None,
        progress=0.0,
        done=0,
        total=0,
        warnings=[],
        error="",
        errorText=None,
        modelProgress=None,
        currentFile="",
        currentPath="",
        currentThumb="",
        activeEvaluation="",
        completedEvaluations=[],
        paused=False,
    )

    try:
        if mode == "uploads":
            paths = [path for path in uploaded_paths if path.exists()]
            warnings: list[dict[str, Any]] = []
            active_cache_path = cache_path
            use_cache = False
        else:
            paths, warnings = dependencies.scan_image_paths(folders)
            active_cache_path = cache_path
            use_cache = True

        job_service.update(
            phase="ready",
            titleText=text_ref("jobText.photosReady"),
            detailText=text_ref("jobText.photosReadyDetail", count=len(paths)),
            total=len(paths),
            warnings=warnings,
        )

        if not paths:
            with state_store.lock:
                state_store.data["scores_df"] = pd.DataFrame(columns=dependencies.empty_score_columns)
                state_store.data["source"].update(_source_payload(mode, folders, cache_path, uploaded_paths))
            job_service.update(
                running=False,
                phase="empty",
                titleText=text_ref("jobText.noPhotos"),
                detailText=text_ref("jobText.noPhotosDetail"),
                progress=0.0,
            )
            return

        def update_score_progress(done: int, total: int, path: Path, state: str) -> None:
            job_service.raise_if_cancelled()
            progress = scoring_progress(done, total, state, selected_models)
            job_service.update(
                phase="scoring",
                titleText=text_ref(progress.title_key),
                detailText=text_ref(
                    "jobText.photoProgressDetail",
                    index=progress.current_index,
                    total=total,
                    file=path.name,
                ),
                progress=done / max(total, 1),
                done=done,
                total=total,
                currentFile=path.name,
                currentPath=str(path),
                currentThumb=dependencies.thumbnail_url(str(path), 180),
                activeEvaluation=progress.active_evaluation,
                completedEvaluations=progress.completed_evaluations,
            )
            job_service.wait_if_paused(path)
            job_service.raise_if_cancelled()

        scored_df, device = dependencies.score_image_paths(
            paths,
            cache_path=active_cache_path,
            use_cache=use_cache,
            model_loader=lambda selected_device: dependencies.model_loader(
                selected_device,
                network_mode,
                job_service,
            ),
            clip_reference_loader=lambda selected_device: dependencies.clip_reference_loader(
                selected_device,
                network_mode,
                job_service,
            ),
            selected_models=selected_models,
            progress_callback=update_score_progress,
        )
        with state_store.lock:
            state_store.data["scores_df"] = scored_df
            state_store.data["source"].update(_source_payload(mode, folders, cache_path, uploaded_paths))
        job_service.update(
            running=False,
            phase="done",
            titleText=text_ref("jobText.scoringDone"),
            detailText=text_ref(
                "jobText.scoringDoneDetail",
                count=len(scored_df),
                device=text_ref(dependencies.device_key(device)),
            ),
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
            titleText=text_ref("jobText.scoringCancelled"),
            detailText=text_ref("jobText.scoringCancelledDetail"),
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
            titleText=text_ref("jobText.scoringFailed"),
            detailText=text_ref("jobText.checkNetworkOrModels"),
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


def _write_source_state(
    state_store: AppStateStore,
    mode: str,
    folders: list[str],
    cache_path: str,
    uploaded_paths: list[Path],
    network_mode: str,
    selected_models: list[str],
) -> None:
    with state_store.lock:
        state = state_store.data
        state["network"]["mode"] = network_mode
        state["models"]["selected"] = selected_models
        state["source"].update(_source_payload(mode, folders, cache_path, uploaded_paths))


def _source_payload(
    mode: str,
    folders: list[str],
    cache_path: str,
    uploaded_paths: list[Path],
) -> dict[str, Any]:
    return {
        "mode": mode,
        "folders": folders,
        "cachePath": cache_path,
        "uploadedPaths": [str(path) for path in uploaded_paths],
    }
