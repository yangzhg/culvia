from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Any

from culvia.app_state import AppStateStore


class ScoringJobService:
    def __init__(
        self,
        state_store: AppStateStore,
        *,
        condition: threading.Condition | None = None,
        context: threading.local | None = None,
    ) -> None:
        self.state_store = state_store
        self.condition = condition or threading.Condition()
        self.context = context or threading.local()
        self.control: dict[str, Any] = {"pauseRequested": False, "jobId": ""}

    def active_thread_job_id(self) -> str:
        return str(getattr(self.context, "job_id", "") or "")

    def bind_thread_job(self, job_id: str) -> None:
        self.context.job_id = job_id

    def clear_thread_job(self) -> None:
        if hasattr(self.context, "job_id"):
            delattr(self.context, "job_id")

    def is_running(self) -> bool:
        with self.state_store.lock:
            return bool(self.state_store.data["job"].get("running"))

    def update(self, **changes: Any) -> None:
        job_id = self.active_thread_job_id()
        with self.state_store.lock:
            if job_id and str(self.state_store.data["job"].get("jobId") or "") != job_id:
                return
            self.state_store.data["job"].update(changes)
            self.state_store.data["job"]["updatedAt"] = time.time()

    def reserve(
        self,
        *,
        kind: str = "scoring",
        phase: str = "queued",
        title: str = "准备开始评分",
        detail: str = "正在启动后台任务",
    ) -> str | None:
        job_id = uuid.uuid4().hex
        with self.state_store.lock:
            job = self.state_store.data["job"]
            if job.get("running"):
                return None
            job.update(
                {
                    "jobId": job_id,
                    "kind": kind,
                    "running": True,
                    "phase": phase,
                    "title": title,
                    "detail": detail,
                    "progress": 0.0,
                    "done": 0,
                    "total": 0,
                    "warnings": [],
                    "error": "",
                    "modelProgress": None,
                    "currentFile": "",
                    "currentPath": "",
                    "currentThumb": "",
                    "activeEvaluation": "",
                    "completedEvaluations": [],
                    "paused": False,
                    "updatedAt": time.time(),
                }
            )
        with self.condition:
            self.control["jobId"] = job_id
            self.control["pauseRequested"] = False
            self.condition.notify_all()
        return job_id

    def reset_control(self, job_id: str | None = None) -> None:
        with self.condition:
            active_job_id = str(self.control.get("jobId") or "")
            if job_id is not None and active_job_id and active_job_id != job_id:
                return
            self.control["pauseRequested"] = False
            self.control["jobId"] = ""
            self.condition.notify_all()

    def request_pause(self) -> bool:
        with self.state_store.lock:
            job = self.state_store.data["job"]
            if not job.get("running") or job.get("kind") != "scoring":
                return False
            job_id = str(job.get("jobId") or "")
        if not job_id:
            return False
        with self.condition:
            if str(self.control.get("jobId") or "") != job_id:
                return False
            self.control["pauseRequested"] = True
        self.update(paused=True, phase="pausing", title="准备暂停", detail="当前阶段结束后会暂停")
        return True

    def request_resume(self) -> bool:
        with self.state_store.lock:
            job = self.state_store.data["job"]
            if not job.get("running") or job.get("kind") != "scoring":
                return False
            job_id = str(job.get("jobId") or "")
        if not job_id:
            return False
        with self.condition:
            if str(self.control.get("jobId") or "") != job_id:
                return False
            self.control["pauseRequested"] = False
            self.condition.notify_all()
        self.update(paused=False, phase="scoring", title="继续评分", detail="正在恢复任务")
        return True

    def wait_if_paused(self, path: Path | None = None) -> None:
        job_id = self.active_thread_job_id()
        with self.condition:
            while self.control["pauseRequested"] and (not job_id or str(self.control.get("jobId") or "") == job_id):
                detail = f"已暂停 · {path.name}" if path is not None else "已暂停"
                self.update(paused=True, phase="paused", title="已暂停", detail=detail)
                self.condition.wait(timeout=0.5)
        self.update(paused=False)
