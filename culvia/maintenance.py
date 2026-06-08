from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


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


def resolve_history_cache_path(
    requested_path: object,
    *,
    current_cache_path: object,
    default_cache_path: str | Path,
    allowed_suffixes: Iterable[str],
) -> tuple[Path | None, str]:
    current_text = str(current_cache_path or default_cache_path).strip()
    requested_text = str(requested_path or "").strip()
    selected = Path(requested_text or current_text).expanduser()
    current = Path(current_text or default_cache_path).expanduser()
    allowed = {suffix.lower() for suffix in allowed_suffixes}

    if selected.suffix.lower() not in allowed:
        return None, "评分记录只支持清理 SQLite 文件。"

    try:
        selected_resolved = selected.resolve()
        current_resolved = current.resolve()
    except Exception:
        return None, "评分记录路径不可用。"

    if selected_resolved != current_resolved:
        return None, "只能清理当前正在使用的评分记录。"

    if selected.exists() and not selected.is_file():
        return None, "缓存路径不是文件，未执行清理。"

    return selected, ""


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


def clear_model_caches(
    app_model_cache_dir: Path,
    model_repo_cache_dirs: Iterable[str],
    huggingface_cache_root: Path,
) -> ModelClearResult:
    repo_cache_paths = [huggingface_cache_root / repo_dir for repo_dir in model_repo_cache_dirs]
    for repo_dir, path in zip(model_repo_cache_dirs, repo_cache_paths):
        if path.name != repo_dir:
            raise ValueError("模型缓存路径异常，未执行清理。")

    deleted_paths: list[Path] = []
    for path in (app_model_cache_dir, *repo_cache_paths):
        if remove_path_safely(path):
            deleted_paths.append(path)
    return ModelClearResult(paths=deleted_paths)
