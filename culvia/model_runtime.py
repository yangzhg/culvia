from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Any, Iterable

from culvia.job_service import ScoringJobService
from culvia.job_text import text_ref
from culvia.model_loaders import load_clip_reference_model, load_model
from culvia.model_files import ensure_clip_reference_model_files, ensure_model_files, format_bytes
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


def duration_text_ref(seconds: int | float | None) -> dict[str, Any]:
    if seconds is None:
        return text_ref("jobText.downloadCalculating")
    seconds = max(0, int(seconds))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return text_ref("duration.hoursMinutes", hours=hours, minutes=f"{minutes:02d}")
    if minutes:
        return text_ref("duration.minutesSeconds", minutes=minutes, seconds=f"{sec:02d}")
    return text_ref("duration.seconds", seconds=sec)


def model_progress_payload(
    filename: str, stage: int, total: int, state: str, info: dict[str, Any]
) -> dict[str, Any] | None:
    if filename != "model.pt":
        progress = max(0.03, min((stage - 0.35) / max(total, 1), 0.94))
        active_size = str(info.get("active_download_size_label") or "")
        if state in {"cached", "ready"}:
            return None
        detail = (
            text_ref("jobText.prepFileWithSize", filename=filename, size=active_size)
            if active_size and active_size != "0.0 B"
            else text_ref("jobText.prepFile", filename=filename)
        )
        return {
            "labelText": text_ref("jobText.prepRefModel", stage=stage, total=total),
            "progress": progress,
            "detailText": detail,
        }

    fraction = info.get("download_fraction")
    progress = float(fraction) if isinstance(fraction, float) else 0.02
    progress = max(0.02, min(progress, 0.995))

    if state in {"cached", "ready"}:
        return None
    if state in {"connecting", "connected", "starting"}:
        return {
            "labelText": text_ref("jobText.prepModel"),
            "progress": progress,
            "detailText": text_ref("jobText.connectingSource"),
        }

    percent = f"{fraction * 100:.1f}%" if isinstance(fraction, float) else text_ref("jobText.downloadPreparing")
    speed_bps = info.get("speed_bps")
    speed = f"{format_bytes(speed_bps)}/s" if speed_bps else text_ref("jobText.downloadWaitingData")
    expected_size = info.get("expected_size")
    expected = format_bytes(expected_size) if expected_size else text_ref("jobText.unknown")
    return {
        "labelText": text_ref("jobText.downloadingModel", percent=percent),
        "progress": progress,
        "detailText": text_ref(
            "jobText.downloadStats",
            downloaded=format_bytes(info.get("active_download_size") or 0),
            expected=expected,
            speed=speed,
            eta=duration_text_ref(info.get("eta_seconds")),
        ),
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
            job_service.update(phase="model", titleText=text_ref("jobText.prepScoringModel"), modelProgress=progress)

        with temporary_proxy_environment(network_mode):
            ensure_model_files(update_model_progress)
            job_service.update(
                phase="loading_model",
                modelProgress=None,
                titleText=text_ref("jobText.loadingScoringModel"),
                detailText=text_ref("jobText.modelReadyLocal"),
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
            job_service.update(phase="model", titleText=text_ref("jobText.prepClipModel"), modelProgress=progress)

        with temporary_proxy_environment(network_mode):
            ensure_clip_reference_model_files(update_model_progress)
            job_service.update(
                phase="loading_model",
                modelProgress=None,
                titleText=text_ref("jobText.loadingClipModel"),
                detailText=text_ref("jobText.clipModelPurpose"),
            )
            loaded = load_clip_reference_model(device)
        self.set(RUNTIME_CLIP_REFERENCE, device, loaded)
        return loaded
