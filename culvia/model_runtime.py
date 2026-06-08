from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Any, Iterable

from culvia.job_service import ScoringJobService
from culvia.model_loaders import load_clip_reference_model, load_model
from culvia.model_files import ensure_clip_reference_model_files, ensure_model_files
from culvia.schema import (
    RUNTIME_CLIP_REFERENCE,
    RUNTIME_CORE_AESTHETIC,
)


PROXY_ENV_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")
ORIGINAL_PROXY_ENV = {key: os.environ.get(key) for key in PROXY_ENV_KEYS}


def system_proxy_configured() -> bool:
    return any(bool(value) for value in ORIGINAL_PROXY_ENV.values())


@contextmanager
def temporary_proxy_environment(mode: str):
    original_values = {key: os.environ.get(key) for key in PROXY_ENV_KEYS}
    try:
        if mode == "system":
            for key in PROXY_ENV_KEYS:
                value = ORIGINAL_PROXY_ENV.get(key)
                if value:
                    os.environ[key] = value
                else:
                    os.environ.pop(key, None)
        else:
            for key in PROXY_ENV_KEYS:
                os.environ.pop(key, None)
        yield
    finally:
        for key, value in original_values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def model_progress_payload(
    filename: str, stage: int, total: int, state: str, info: dict[str, Any]
) -> dict[str, Any] | None:
    if filename != "model.pt":
        progress = max(0.03, min((stage - 0.35) / max(total, 1), 0.94))
        active_size = str(info.get("active_download_size_label") or "")
        suffix = f" · 已接收 {active_size}" if active_size and active_size != "0.0 B" else ""
        if state in {"cached", "ready"}:
            return None
        return {
            "label": f"准备参考模型 {stage}/{total}",
            "progress": progress,
            "detail": f"正在准备 {filename}{suffix}",
        }

    fraction = info.get("download_fraction")
    progress = float(fraction) if isinstance(fraction, float) else 0.02
    progress = max(0.02, min(progress, 0.995))
    percent = str(info.get("download_percent_label") or "准备中")
    speed = str(info.get("speed_label") or "等待数据")
    eta = str(info.get("eta_label") or "计算中")
    downloaded = str(info.get("active_download_size_label") or "")
    expected = str(info.get("expected_size_label") or "")

    if state in {"cached", "ready"}:
        return None
    if state in {"connecting", "connected", "starting"}:
        return {
            "label": "准备模型",
            "progress": progress,
            "detail": "正在连接下载源",
        }
    return {
        "label": f"下载模型 {percent}",
        "progress": progress,
        "detail": f"{downloaded} / {expected} · {speed} · 约 {eta}",
    }


class ModelRuntimeCache:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.cache: dict[str, object] = {}

    def cache_key(self, runtime_key: str, device: str) -> str:
        return f"{runtime_key}:{device}"

    def get(self, runtime_key: str, device: str) -> object | None:
        with self.lock:
            return self.cache.get(self.cache_key(runtime_key, device))

    def set(self, runtime_key: str, device: str, loaded: object) -> None:
        with self.lock:
            self.cache[self.cache_key(runtime_key, device)] = loaded

    def clear(self) -> None:
        with self.lock:
            self.cache.clear()

    def any_loaded(self, runtime_keys: Iterable[str], device: str) -> bool:
        keys = [str(runtime_key) for runtime_key in runtime_keys]
        if not keys:
            return True
        with self.lock:
            return any(self.cache.get(self.cache_key(runtime_key, device)) is not None for runtime_key in keys)

    def load_core_model(
        self,
        device: str,
        *,
        network_mode: str = "direct",
        job_service: ScoringJobService,
    ) -> object:
        loaded = self.get(RUNTIME_CORE_AESTHETIC, device)
        if loaded is not None:
            return loaded

        def update_model_progress(
            filename: str,
            stage: int,
            total: int,
            state: str,
            info: dict[str, Any],
        ) -> None:
            progress = model_progress_payload(filename, stage, total, state, info)
            job_service.update(phase="model", title="正在准备评分模型", modelProgress=progress)

        with temporary_proxy_environment(network_mode):
            ensure_model_files(update_model_progress)
            job_service.update(
                phase="loading_model",
                modelProgress=None,
                title="正在载入评分模型",
                detail="模型已在本机准备好",
            )
            loaded = load_model(device)
        self.set(RUNTIME_CORE_AESTHETIC, device, loaded)
        return loaded

    def load_clip_reference(
        self,
        device: str,
        *,
        network_mode: str = "direct",
        job_service: ScoringJobService,
    ) -> object:
        loaded = self.get(RUNTIME_CLIP_REFERENCE, device)
        if loaded is not None:
            return loaded

        def update_model_progress(
            filename: str,
            stage: int,
            total: int,
            state: str,
            info: dict[str, Any],
        ) -> None:
            progress = model_progress_payload(filename, stage, total, state, info)
            job_service.update(phase="model", title="正在准备 CLIP 参考模型", modelProgress=progress)

        with temporary_proxy_environment(network_mode):
            ensure_clip_reference_model_files(update_model_progress)
            job_service.update(
                phase="loading_model",
                modelProgress=None,
                title="正在载入 CLIP 参考模型",
                detail="用于模型画质和审美参考",
            )
            loaded = load_clip_reference_model(device)
        self.set(RUNTIME_CLIP_REFERENCE, device, loaded)
        return loaded
