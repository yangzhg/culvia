from __future__ import annotations

import base64
import hashlib
from contextlib import nullcontext
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIF_AVAILABLE = True
except Exception:
    HEIF_AVAILABLE = False


def open_image_rgb(path: str | Path) -> Image.Image:
    try:
        with Image.open(path) as image:
            image.load()
            return ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise RuntimeError(f"cannot_open_image: {exc!r}") from exc


def bounded_image_cache_size(max_size: int | None, minimum: int = 80, maximum: int = 1600) -> int:
    return max(minimum, min(int(max_size or maximum), maximum))


def resized_image_cache_path(path: str | Path, cache_dir: str | Path, max_size: int) -> Path:
    source = Path(path).expanduser()
    stat = source.stat()
    key = hashlib.sha1(f"{source.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{max_size}".encode("utf-8")).hexdigest()
    return Path(cache_dir).expanduser() / f"{key}.jpg"


def ensure_resized_image_cache(
    path: str | Path,
    cache_dir: str | Path,
    max_size: int | None,
    *,
    minimum_size: int = 80,
    maximum_size: int = 1600,
    quality: int = 90,
    lock: object | None = None,
) -> Path:
    bounded_size = bounded_image_cache_size(max_size, minimum=minimum_size, maximum=maximum_size)
    cache_path = resized_image_cache_path(path, cache_dir, bounded_size)
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return cache_path

    context = lock if lock is not None else nullcontext()
    with context:
        if cache_path.exists() and cache_path.stat().st_size > 0:
            return cache_path
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        image = open_image_rgb(path)
        image.thumbnail((bounded_size, bounded_size))
        temp_path = cache_path.with_suffix(".tmp")
        image.save(temp_path, format="JPEG", quality=quality, optimize=True, progressive=True)
        temp_path.replace(cache_path)
    return cache_path


def image_file_data_url(path: str | Path, mime_type: str = "image/jpeg") -> str:
    encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"
