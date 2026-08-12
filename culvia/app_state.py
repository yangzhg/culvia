from __future__ import annotations

import copy
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from culvia.job_text import text_ref
from culvia.media_catalog import MediaCatalogSnapshot, build_media_catalog


_MISSING = object()
_STORE_MANAGED_KEYS = frozenset({"scores_df", "source", "job"})


class StaleMediaStateError(RuntimeError):
    """Raised when a background result targets an obsolete media state."""


def empty_job(now: float | None = None) -> dict[str, Any]:
    return {
        "jobId": "",
        "kind": "",
        "running": False,
        "phase": "idle",
        "title": "",
        "detail": "",
        "titleText": text_ref("jobText.idleReady"),
        "detailText": text_ref("jobText.idleChooseSource"),
        "progress": 0.0,
        "done": 0,
        "total": 0,
        "warnings": [],
        "error": "",
        "errorText": None,
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
    media_revision: int = field(default=0, init=False)
    _media_catalog: MediaCatalogSnapshot = field(init=False, repr=False)
    _state_generation: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        self._media_catalog = build_media_catalog(
            self.data.get("scores_df", []),
            self.data.get("source", {}),
            revision=self.media_revision,
        )

    def reset(
        self,
        next_state: Mapping[str, Any],
        *,
        expected_job_id: str | None = None,
        preserve_job: bool = False,
    ) -> None:
        copied = copy.deepcopy(dict(next_state))
        catalog = build_media_catalog(
            copied.get("scores_df", []),
            copied.get("source", {}),
            revision=0,
        )
        with self.lock:
            self._require_expected_state(None, expected_job_id)
            if preserve_job:
                copied["job"] = copy.deepcopy(self.data.get("job", empty_job()))
            next_revision = self.media_revision + 1
            self.data.clear()
            self.data.update(copied)
            self.media_revision = next_revision
            self._media_catalog = _with_media_revision(catalog, next_revision)
            self._state_generation += 1

    def publish_media_state(
        self,
        *,
        scores_df: object = _MISSING,
        source_patch: Mapping[str, object] | None = None,
        source_preview: object = _MISSING,
        remove_source_preview: bool = False,
        expected_media_revision: int | None = None,
        expected_job_id: str | None = None,
    ) -> int:
        copied_source_patch = copy.deepcopy(dict(source_patch or {}))
        copied_source_preview = copy.deepcopy(source_preview) if source_preview is not _MISSING else _MISSING
        while True:
            with self.lock:
                base_revision = self.media_revision
                self._require_expected_state(expected_media_revision, expected_job_id)
                base_generation = self._state_generation
                next_scores = self.data.get("scores_df", []) if scores_df is _MISSING else scores_df
                next_source = copy.deepcopy(dict(self.data.get("source", {})))
            next_source.update(copied_source_patch)
            catalog = build_media_catalog(next_scores, next_source, revision=base_revision + 1)
            with self.lock:
                if self.media_revision != base_revision:
                    if expected_media_revision is not None:
                        self._require_expected_state(expected_media_revision, expected_job_id)
                    continue
                self._require_expected_state(expected_media_revision, expected_job_id)
                if self._state_generation != base_generation:
                    continue
                if scores_df is not _MISSING:
                    self.data["scores_df"] = scores_df
                self.data["source"] = next_source
                if copied_source_preview is not _MISSING:
                    self.data["sourcePreview"] = copied_source_preview
                elif remove_source_preview:
                    self.data.pop("sourcePreview", None)
                self.media_revision = base_revision + 1
                self._state_generation += 1
                self._media_catalog = catalog
                return self.media_revision

    def publish_score_values(
        self,
        scores_df: object,
        *,
        expected_media_revision: int,
        expected_job_id: str | None = None,
    ) -> None:
        """Publish trusted score-only changes whose file_id/path columns are unchanged."""
        with self.lock:
            self._require_expected_state(expected_media_revision, expected_job_id)
            self.data["scores_df"] = scores_df
            self._state_generation += 1

    def update_nonmedia_state(
        self,
        patch: Mapping[str, object],
        *,
        expected_job_id: str | None = None,
    ) -> int:
        """Atomically update state that does not affect media authorization."""
        copied = copy.deepcopy(dict(patch))
        if _STORE_MANAGED_KEYS.intersection(copied):
            raise ValueError("Managed state must use its dedicated publication API")
        with self.lock:
            self._require_expected_state(None, expected_job_id)
            self.data.update(copied)
            self._state_generation += 1
            return self.media_revision

    def current_media_revision(self) -> int:
        with self.lock:
            return self.media_revision

    def media_catalog_snapshot(self) -> MediaCatalogSnapshot:
        with self.lock:
            return self._media_catalog

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return copy.deepcopy(self.data)

    def _require_expected_state(
        self,
        expected_media_revision: int | None,
        expected_job_id: str | None,
    ) -> None:
        if expected_media_revision is not None and expected_media_revision != self.media_revision:
            raise StaleMediaStateError("Media catalog changed before the background result was published")
        if expected_job_id is not None:
            current_job_id = str(self.data.get("job", {}).get("jobId") or "")
            if current_job_id != expected_job_id:
                raise StaleMediaStateError("Background job changed before the result was published")


def _with_media_revision(catalog: MediaCatalogSnapshot, revision: int) -> MediaCatalogSnapshot:
    return MediaCatalogSnapshot(
        revision=revision,
        by_file_id=catalog.by_file_id,
        scored_paths_by_key=catalog.scored_paths_by_key,
        source_mode=catalog.source_mode,
        folder_roots=catalog.folder_roots,
        uploaded_paths_by_key=catalog.uploaded_paths_by_key,
    )
