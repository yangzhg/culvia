from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import pandas as pd

from culvia.app_state import AppStateStore
from culvia.job_service import ScoringJobService
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
    llm_review_configured: Callable[[], bool]
    scan_image_paths: Callable[[Sequence[str]], tuple[list[Path], list[str]]]
    score_image_paths: ScoreImagePaths
    model_loader: ModelLoader
    clip_reference_loader: ModelLoader
    thumbnail_url: Callable[[str, int], str]
    device_label: Callable[[str | None], str]


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
            title="评分失败",
            detail="请检查照片来源或评分记录路径",
            error=repr(exc),
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

    job_service.update(
        running=True,
        phase="scanning",
        title="正在整理照片",
        detail="",
        progress=0.0,
        done=0,
        total=0,
        warnings=[],
        error="",
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
            warnings: list[str] = []
            active_cache_path = cache_path
            use_cache = False
        else:
            paths, warnings = dependencies.scan_image_paths(folders)
            active_cache_path = cache_path
            use_cache = True

        job_service.update(
            phase="ready",
            title="照片已就绪",
            detail=f"找到 {len(paths)} 张可评分照片",
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
                title="没有找到照片",
                detail="换一个目录或拖入图片后再试",
                progress=0.0,
            )
            return

        def update_score_progress(done: int, total: int, path: Path, state: str) -> None:
            progress = scoring_progress(done, total, state, selected_models)
            job_service.update(
                phase="scoring",
                title=progress.title,
                detail=f"第 {progress.current_index} / {total} 张 · {path.name}",
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
            title="评分完成",
            detail=f"{len(scored_df)} 张照片 · {dependencies.device_label(device)}",
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
    except Exception as exc:
        job_service.update(
            running=False,
            phase="error",
            title="评分失败",
            detail="请检查网络、目录或模型文件",
            error=repr(exc),
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
