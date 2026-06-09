from __future__ import annotations

import copy
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


def empty_job(now: float | None = None) -> dict[str, Any]:
    return {
        "jobId": "",
        "kind": "",
        "running": False,
        "phase": "idle",
        "title": "准备就绪",
        "detail": "选择照片来源后即可开始评分",
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
        "updatedAt": time.time() if now is None else now,
    }


def create_initial_state(
    *,
    scores_df: Any,
    default_photo_dirs: Sequence[str],
    default_cache_path: str,
    filter_defaults: Mapping[str, Any],
    default_selected_models: Sequence[str],
) -> dict[str, Any]:
    return {
        "scores_df": scores_df,
        "source": {
            "mode": "folders",
            "folders": list(default_photo_dirs),
            "cachePath": default_cache_path,
            "uploadedPaths": [],
        },
        "sourcePreview": {
            "mode": "folders",
            "folders": list(default_photo_dirs),
            "cachePath": default_cache_path,
            "total": 0,
            "ready": False,
            "warnings": [],
        },
        "filters": copy.deepcopy(dict(filter_defaults)),
        "network": {
            "mode": "direct",
        },
        "models": {
            "selected": list(default_selected_models),
        },
        "job": empty_job(),
    }


@dataclass
class AppStateStore:
    data: dict[str, Any]
    lock: threading.RLock = field(default_factory=threading.RLock)

    def reset(self, next_state: Mapping[str, Any]) -> None:
        with self.lock:
            self.data.clear()
            self.data.update(copy.deepcopy(dict(next_state)))

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return copy.deepcopy(self.data)
