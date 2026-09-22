from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from culvia.export_receipts import ExportReceiptError
from culvia.job_text import TranslatableValueError, text_ref
from culvia.path_semantics import is_same_or_child_path, stable_path


@dataclass(frozen=True)
class HistoryClearResult:
    path: Path
    deleted: bool

    def to_payload(self) -> dict[str, object]:
        return {
            "kind": "history",
            "deleted": self.deleted,
            "path": str(self.path),
        }


@dataclass(frozen=True)
class ModelClearResult:
    paths: list[Path]

    @property
    def deleted(self) -> bool:
        return bool(self.paths)

    def to_payload(self) -> dict[str, object]:
        return {
            "kind": "model",
            "deleted": self.deleted,
            "paths": [str(path) for path in self.paths],
        }


@dataclass(frozen=True)
class LocalDataClearResult:
    history: HistoryClearResult
    models: ModelClearResult
    paths: list[Path]
    export_receipts_deleted: int = 0

    @property
    def deleted(self) -> bool:
        return self.history.deleted or self.models.deleted or bool(self.paths) or bool(self.export_receipts_deleted)

    def to_payload(self) -> dict[str, object]:
        return {
            "kind": "localData",
            "deleted": self.deleted,
            "history": self.history.to_payload(),
            "models": self.models.to_payload(),
            "paths": [str(path) for path in self.paths],
            "exportReceiptsCleared": self.export_receipts_deleted,
        }


def resolve_history_cache_path(
    requested_path: object,
    *,
    current_cache_path: object,
    default_cache_path: str | Path,
    allowed_suffixes: Iterable[str],
) -> tuple[Path | None, dict[str, object] | None]:
    """Resolve the cache path to clear; the error is a text ref for the web UI."""
    current_text = str(current_cache_path or default_cache_path).strip()
    requested_text = str(requested_path or "").strip()
    selected = Path(requested_text or current_text).expanduser()
    current = Path(current_text or default_cache_path).expanduser()
    allowed = {suffix.lower() for suffix in allowed_suffixes}

    if selected.suffix.lower() not in allowed:
        return None, text_ref("error.historyCacheNotSqlite")

    try:
        selected_resolved = selected.resolve()
        current_resolved = current.resolve()
    except Exception:
        return None, text_ref("error.historyCachePathUnavailable")

    if selected_resolved != current_resolved:
        return None, text_ref("error.historyCacheNotCurrent")

    if selected.exists() and not selected.is_file():
        return None, text_ref("error.historyCacheNotFile")

    return selected, None


def remove_path_safely(path: Path) -> bool:
    if not path.exists():
        return False
    if path.is_dir():
        shutil.rmtree(path)
        return True
    path.unlink()
    return True


def clear_history_cache(cache_path: Path) -> HistoryClearResult:
    return HistoryClearResult(path=cache_path, deleted=remove_path_safely(cache_path))


def model_cache_paths(
    app_model_cache_dir: Path,
    model_repo_cache_dirs: Iterable[str],
    huggingface_cache_root: Path,
) -> list[Path]:
    model_repo_cache_dirs = tuple(model_repo_cache_dirs)
    repo_cache_paths = [huggingface_cache_root / repo_dir for repo_dir in model_repo_cache_dirs]
    lock_cache_paths = [huggingface_cache_root / ".locks" / repo_dir for repo_dir in model_repo_cache_dirs]
    for repo_dir, path in zip(model_repo_cache_dirs, repo_cache_paths):
        if path.name != repo_dir:
            raise TranslatableValueError("error.modelCachePathInvalid", fallback="模型缓存路径异常，未执行清理。")
    for repo_dir, path in zip(model_repo_cache_dirs, lock_cache_paths):
        if path.name != repo_dir:
            raise TranslatableValueError("error.modelCachePathInvalid", fallback="模型缓存路径异常，未执行清理。")
    return [app_model_cache_dir, *repo_cache_paths, *lock_cache_paths]


def validate_export_receipt_cleanup(removal_paths: Iterable[Path], *, receipt_path: Path, lock_path: Path) -> None:
    """Keep cleanup from unlinking a receipt database or its shared process lock."""
    for removal_path in removal_paths:
        if any(
            stable_path(path).is_relative_to(stable_path(removal_path)) or is_same_or_child_path(path, removal_path)
            for path in (receipt_path, lock_path)
        ):
            raise ExportReceiptError(
                "exportReceiptPathConflict",
                "Delivery receipt storage overlaps the data selected for cleanup.",
                status_code=400,
            )


def clear_model_caches(
    app_model_cache_dir: Path,
    model_repo_cache_dirs: Iterable[str],
    huggingface_cache_root: Path,
) -> ModelClearResult:
    deleted_paths: list[Path] = []
    for path in model_cache_paths(app_model_cache_dir, model_repo_cache_dirs, huggingface_cache_root):
        if remove_path_safely(path):
            deleted_paths.append(path)
    return ModelClearResult(paths=deleted_paths)


def clear_local_data(
    *,
    cache_path: Path,
    upload_cache_dir: Path,
    thumbnail_cache_dir: Path,
    analysis_image_cache_dir: Path,
    app_model_cache_dir: Path,
    model_repo_cache_dirs: Iterable[str],
    huggingface_cache_root: Path,
    clear_thumbnail_cache: Callable[[Path], bool] | None = None,
    clear_export_receipts: Callable[[], int] | None = None,
) -> LocalDataClearResult:
    receipt_count = clear_export_receipts() if clear_export_receipts is not None else 0
    history_result = clear_history_cache(cache_path)
    model_result = clear_model_caches(app_model_cache_dir, model_repo_cache_dirs, huggingface_cache_root)
    deleted_paths: list[Path] = []
    for path in (upload_cache_dir, analysis_image_cache_dir):
        if remove_path_safely(path):
            deleted_paths.append(path)
    thumbnail_deleted = (
        clear_thumbnail_cache(thumbnail_cache_dir)
        if clear_thumbnail_cache is not None
        else remove_path_safely(thumbnail_cache_dir)
    )
    if thumbnail_deleted:
        deleted_paths.append(thumbnail_cache_dir)
    return LocalDataClearResult(
        history=history_result, models=model_result, paths=deleted_paths, export_receipts_deleted=receipt_count
    )
