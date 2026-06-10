from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from culvia.app_state import AppStateStore
from culvia.job_service import ScoringJobService
from culvia.job_text import exception_text, text_ref
from culvia.source_requests import SourceRequest, source_request_from_payload


class ThreadLike(Protocol):
    def start(self) -> None: ...


ThreadFactory = Callable[..., ThreadLike]
RunSourcePreviewJob = Callable[[str, dict[str, Any], AppStateStore, ScoringJobService], None]


@dataclass(frozen=True)
class SourcePreviewDependencies:
    default_cache_path: str | Path
    scan_image_paths: Callable[[Iterable[str | Path]], tuple[list[Path], list[dict[str, Any]]]]
    sanitize_uploaded_paths: Callable[[object], list[Path]]
    build_file_id: Callable[[Path], str]
    load_cache_records: Callable[[str | Path], pd.DataFrame]
    save_source_config: Callable[[Mapping[str, object], str | Path], Mapping[str, object]]
    normalize_score_dataframe: Callable[[pd.DataFrame], pd.DataFrame]
    make_empty_record: Callable[[Path, str, str], dict[str, object]]


@dataclass(frozen=True)
class SourcePreviewResult:
    request: SourceRequest
    paths: list[Path]
    warnings: list[dict[str, Any]]
    scores_df: pd.DataFrame

    def source_payload(self) -> dict[str, object]:
        return {
            "mode": self.request.mode,
            "folders": self.request.folders,
            "cachePath": self.request.cache_path,
            "uploadedPaths": [str(path) for path in self.paths]
            if self.request.mode == "uploads"
            else [str(path) for path in self.request.uploaded_paths],
        }

    def to_payload(self) -> dict[str, object]:
        return {
            "mode": self.request.mode,
            "folders": self.request.folders,
            "cachePath": self.request.cache_path,
            "total": len(self.paths),
            "ready": True,
            "warnings": self.warnings,
        }


class SourcePreviewStartError(Exception):
    def __init__(self, error_code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class SourcePreviewStartResult:
    job_id: str

    def to_payload(self) -> dict[str, object]:
        return {"started": True, "jobId": self.job_id}


def _records_by_file_id(frame: pd.DataFrame) -> dict[str, dict[str, object]]:
    if frame.empty or "file_id" not in frame.columns:
        return {}
    records: dict[str, dict[str, object]] = {}
    for record in frame.to_dict(orient="records"):
        file_id = str(record.get("file_id") or "").strip()
        if file_id:
            records[file_id] = record
    return records


def source_preview_action(
    payload: Mapping[str, object],
    dependencies: SourcePreviewDependencies,
) -> SourcePreviewResult:
    request = source_request_from_payload(payload, default_cache_path=dependencies.default_cache_path)
    if request.mode == "uploads":
        paths = dependencies.sanitize_uploaded_paths(request.uploaded_paths)
        warnings: list[dict[str, Any]] = []
        cached_records: dict[str, dict[str, object]] = {}
    else:
        paths, warnings = dependencies.scan_image_paths(request.folders)
        cached_records = _records_by_file_id(
            dependencies.normalize_score_dataframe(dependencies.load_cache_records(request.cache_path))
        )

    rows: list[dict[str, object]] = []
    valid_paths: list[Path] = []
    for path in paths:
        try:
            file_id = dependencies.build_file_id(path)
        except OSError as exc:
            warnings.append(text_ref("warning.photoReadFailed", path=str(path), error=repr(exc)))
            continue
        valid_paths.append(path)
        rows.append(cached_records.get(file_id) or dependencies.make_empty_record(path, file_id, ""))

    return SourcePreviewResult(
        request=request,
        paths=valid_paths,
        warnings=warnings,
        scores_df=dependencies.normalize_score_dataframe(pd.DataFrame(rows)),
    )


def start_source_preview_job_action(
    payload: dict[str, Any],
    state_store: AppStateStore,
    job_service: ScoringJobService,
    *,
    default_cache_path: str | Path,
    run_source_preview_job: RunSourcePreviewJob,
    thread_factory: ThreadFactory,
) -> SourcePreviewStartResult:
    source_request_from_payload(payload, default_cache_path=default_cache_path)
    job_id = job_service.reserve(
        kind="source_preview",
        phase="source_scanning",
        title_text=text_ref("jobText.scanningSource"),
        detail_text=text_ref("jobText.scanningSourceDetail"),
    )
    if not job_id:
        raise SourcePreviewStartError("jobAlreadyRunning", "当前已有任务正在运行。", status_code=409)

    thread = thread_factory(
        target=run_source_preview_job,
        args=(job_id, payload, state_store, job_service),
        daemon=True,
    )
    thread.start()
    return SourcePreviewStartResult(job_id)


def run_source_preview_job(
    job_id: str,
    payload: dict[str, Any],
    state_store: AppStateStore,
    job_service: ScoringJobService,
    dependencies: SourcePreviewDependencies,
) -> None:
    job_service.bind_thread_job(job_id)
    try:
        request = source_request_from_payload(payload, default_cache_path=dependencies.default_cache_path)
        with state_store.lock:
            state_store.data["source"].update(
                {
                    "mode": request.mode,
                    "folders": request.folders,
                    "cachePath": request.cache_path,
                    "uploadedPaths": [str(path) for path in request.uploaded_paths],
                }
            )
            state_store.data["sourcePreview"] = {
                "mode": request.mode,
                "folders": request.folders,
                "cachePath": request.cache_path,
                "total": 0,
                "ready": False,
                "warnings": [],
            }
        job_service.update(
            phase="source_scanning",
            titleText=text_ref("jobText.scanningSource"),
            detailText=text_ref("jobText.scanningSourceDedupeDetail"),
            progress=0.2,
            done=0,
            total=0,
            warnings=[],
            error="",
            errorText=None,
            currentFile="",
            currentPath="",
            currentThumb="",
            activeEvaluation="",
            completedEvaluations=[],
            modelProgress=None,
            paused=False,
        )
        result = source_preview_action(payload, dependencies)
        apply_source_preview_state(state_store, result)
        persist_source_preview_config(result, dependencies)
        total = len(result.paths)
        job_service.update(
            running=False,
            phase="source_ready" if total else "source_empty",
            titleText=text_ref("jobText.sourceUpdated") if total else text_ref("jobText.noPhotos"),
            detailText=text_ref("jobText.sourceUpdatedDetail", count=total)
            if total
            else text_ref("jobText.sourceEmptyDetail"),
            progress=1.0,
            done=total,
            total=total,
            warnings=result.warnings,
            modelProgress=None,
            currentFile="",
            currentPath="",
            currentThumb="",
            activeEvaluation="",
            completedEvaluations=[],
            paused=False,
        )
    except Exception as exc:
        job_service.update(
            running=False,
            phase="error",
            titleText=text_ref("jobText.scanFailed"),
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
    finally:
        job_service.reset_control(job_id)
        job_service.clear_thread_job()


def apply_source_preview_state(state_store: Any, result: SourcePreviewResult) -> None:
    # Kept as a pure state mutation helper for tests and callers that do not persist config.
    with state_store.lock:
        state = state_store.data
        state["scores_df"] = result.scores_df
        state["source"].update(result.source_payload())
        state["sourcePreview"] = result.to_payload()


def persist_source_preview_config(result: SourcePreviewResult, dependencies: SourcePreviewDependencies) -> None:
    dependencies.save_source_config(result.source_payload(), result.request.cache_path)
