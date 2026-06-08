from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


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


def scan_image_paths(folders: Iterable[str | Path]) -> tuple[list[Path], list[str]]:
    paths: list[Path] = []
    warnings: list[str] = []

    for folder in folders:
        folder_text = str(folder).strip()
        if not folder_text:
            continue

        root = Path(folder_text).expanduser()
        if not root.exists():
            warnings.append(f"目录不存在：{root}")
            continue

        if root.is_file():
            if root.suffix.lower() in SUPPORTED_EXTENSIONS:
                paths.append(root)
            else:
                warnings.append(f"不是支持的图片格式：{root}")
            continue

        try:
            for child in root.rglob("*"):
                if child.is_file() and child.suffix.lower() in SUPPORTED_EXTENSIONS:
                    paths.append(child)
        except Exception as exc:
            warnings.append(f"扫描目录失败：{root} ({exc!r})")

    unique_paths = sorted(set(paths), key=lambda item: str(item).casefold())
    return unique_paths, warnings


def build_file_id(path: str | Path) -> str:
    source = Path(path)
    stat = source.stat()
    return f"{source}|{stat.st_size}|{stat.st_mtime_ns}"
