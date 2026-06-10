from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from culvia.job_text import text_ref
from culvia.path_semantics import path_identity_key, stable_path


SUPPORTED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
    ".heic",
    ".heif",
}


def _canonical_path(path: Path) -> Path:
    return stable_path(path)


def scan_image_paths(folders: Iterable[str | Path]) -> tuple[list[Path], list[dict[str, Any]]]:
    paths: list[Path] = []
    warnings: list[dict[str, Any]] = []

    for folder in folders:
        folder_text = str(folder).strip()
        if not folder_text:
            continue

        root = Path(folder_text).expanduser()
        if not root.exists():
            warnings.append(text_ref("warning.folderMissing", path=str(root)))
            continue

        if root.is_file():
            if root.suffix.lower() in SUPPORTED_EXTENSIONS:
                paths.append(_canonical_path(root))
            else:
                warnings.append(text_ref("warning.unsupportedImage", path=str(root)))
            continue

        try:
            for child in root.rglob("*"):
                if child.is_file() and child.suffix.lower() in SUPPORTED_EXTENSIONS:
                    paths.append(_canonical_path(child))
        except Exception as exc:
            warnings.append(text_ref("warning.scanFailed", path=str(root), error=repr(exc)))

    unique_by_key: dict[str, Path] = {}
    for path in paths:
        unique_by_key.setdefault(path_identity_key(path), path)
    unique_paths = sorted(unique_by_key.values(), key=lambda item: str(item).casefold())
    return unique_paths, warnings


def build_file_id(path: str | Path) -> str:
    source = Path(path)
    stat = source.stat()
    return f"{source}|{stat.st_size}|{stat.st_mtime_ns}"
