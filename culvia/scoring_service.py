from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from culvia.app_state import AppStateStore
from culvia.job_service import ScoringJobService
from culvia.job_text import text_ref


class ThreadLike(Protocol):
    def start(self) -> None: ...


ThreadFactory = Callable[..., ThreadLike]
RunScoringJob = Callable[[str, dict[str, Any], AppStateStore, ScoringJobService], None]


class ScoringStartError(Exception):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        status_code: int = 400,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class ScoringStartResult:
    job_id: str

    def to_payload(self) -> dict[str, object]:
        return {"started": True, "jobId": self.job_id}


def start_scoring_job_action(
    payload: dict[str, Any],
    state_store: AppStateStore,
    job_service: ScoringJobService,
    *,
    run_scoring_job: RunScoringJob,
    thread_factory: ThreadFactory,
) -> ScoringStartResult:
    job_id = job_service.reserve()
    if not job_id:
        raise ScoringStartError("scoringAlreadyRunning", "评分正在进行中", status_code=409)

    thread = thread_factory(
        target=run_scoring_job,
        args=(job_id, payload, state_store, job_service),
        daemon=True,
    )
    thread.start()
    return ScoringStartResult(job_id)


def start_llm_review_job_action(
    payload: dict[str, Any],
    state_store: AppStateStore,
    job_service: ScoringJobService,
    *,
    run_llm_review_job: RunScoringJob,
    thread_factory: ThreadFactory,
) -> ScoringStartResult:
    job_id = job_service.reserve(
        kind="llm_review",
        phase="queued",
        title_text=text_ref("jobText.llmQueued"),
    )
    if not job_id:
        raise ScoringStartError("scoringAlreadyRunning", "评分正在进行中", status_code=409)

    thread = thread_factory(
        target=run_llm_review_job,
        args=(job_id, payload, state_store, job_service),
        daemon=True,
    )
    thread.start()
    return ScoringStartResult(job_id)
