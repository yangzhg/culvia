from __future__ import annotations

import os
import sys
from pathlib import Path

APP_SLUG = "culvia"
APP_DISPLAY_NAME = "Culvia"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _truthy_existing(path: Path) -> Path | None:
    return path if path.exists() else None


def _path_from_env(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else None


def user_data_dir() -> Path:
    override = _path_from_env("CULVIA_DATA_DIR")
    if override is not None:
        return override
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DISPLAY_NAME
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / APP_DISPLAY_NAME
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / APP_SLUG


def user_cache_dir() -> Path:
    override = _path_from_env("CULVIA_CACHE_DIR")
    if override is not None:
        return override
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / APP_DISPLAY_NAME
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / APP_DISPLAY_NAME / "Cache"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / APP_SLUG


def default_cache_path() -> str:
    override = _path_from_env("CULVIA_CACHE_PATH")
    if override is not None:
        return str(override)
    return str(user_data_dir() / "culvia_scores.sqlite")


def default_output_path() -> str:
    override = _path_from_env("CULVIA_OUTPUT_PATH")
    if override is not None:
        return str(override)
    return str(Path.home() / "Downloads" / "culvia_scores.csv")


def default_photo_dirs() -> list[str]:
    override = os.environ.get("CULVIA_PHOTO_DIRS")
    if override:
        return [str(Path(item).expanduser()) for item in override.split(os.pathsep) if item.strip()]
    return []


def rsinema_model_cache_dir() -> Path:
    override = _path_from_env("CULVIA_RSINEMA_MODEL_DIR")
    if override is not None:
        return override
    data_dir = _path_from_env("CULVIA_DATA_DIR")
    if data_dir is not None:
        return data_dir / "model_cache" / "rsinema_aesthetic_scorer"
    project_dir = PROJECT_ROOT / "model_cache" / "rsinema_aesthetic_scorer"
    return _truthy_existing(project_dir) or user_cache_dir() / "models" / "rsinema_aesthetic_scorer"


def analysis_image_cache_dir() -> Path:
    override = _path_from_env("CULVIA_ANALYSIS_CACHE_DIR")
    if override is not None:
        return override
    data_dir = _path_from_env("CULVIA_DATA_DIR")
    if data_dir is not None:
        return data_dir / "analysis_cache"
    project_dir = PROJECT_ROOT / "analysis_cache"
    return _truthy_existing(project_dir) or user_cache_dir() / "analysis_images"


def thumbnail_cache_dir() -> Path:
    override = _path_from_env("CULVIA_THUMBNAIL_CACHE_DIR")
    if override is not None:
        return override
    data_dir = _path_from_env("CULVIA_DATA_DIR")
    if data_dir is not None:
        return data_dir / "thumbnail_cache"
    project_dir = PROJECT_ROOT / "thumbnail_cache"
    return _truthy_existing(project_dir) or user_cache_dir() / "thumbnails"


def upload_cache_dir() -> Path:
    override = _path_from_env("CULVIA_UPLOAD_DIR")
    if override is not None:
        return override
    return user_cache_dir() / "uploads"


def resolve_web_dir() -> Path:
    override = _path_from_env("CULVIA_WEB_DIR")
    if override is not None:
        return override

    frozen_root_value = getattr(sys, "_MEIPASS", None)
    if frozen_root_value:
        frozen_root = Path(frozen_root_value)
        for bundled_data in (
            frozen_root / "share" / "culvia" / "web",
            frozen_root / "web",
        ):
            if bundled_data.exists():
                return bundled_data

    project_web = PROJECT_ROOT / "web"
    if project_web.exists():
        return project_web

    for installed_data in (
        Path(sys.prefix) / "share" / "culvia" / "web",
        Path(sys.prefix) / "culvia" / "web",
    ):
        if installed_data.exists():
            return installed_data
    return project_web
