from __future__ import annotations

import base64
import hashlib
import os
import tempfile
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIF_AVAILABLE = True
except Exception:
    HEIF_AVAILABLE = False


def open_image_rgb(
    path: str | Path,
    *,
    max_size_hint: int | None = None,
    max_decode_pixels: int | None = None,
    resize_before_copy: bool = False,
) -> Image.Image:
    try:
        with Image.open(path) as image:
            source_width, source_height = image.size
            if max_size_hint is not None:
                image.draft("RGB", (max_size_hint, max_size_hint))
            decode_width, decode_height = image.size
            if max_decode_pixels is not None and decode_width * decode_height > max_decode_pixels:
                raise RuntimeError(f"image_too_large: {source_width}x{source_height}")
            image.load()
            resized_image = image
            if resize_before_copy and max_size_hint is not None:
                try:
                    resized_image.thumbnail((max_size_hint, max_size_hint))
                except ValueError:
                    if not image.mode.startswith("I;16"):
                        raise
                    resized_image = image.convert("RGB")
                    resized_image.thumbnail((max_size_hint, max_size_hint))
            transposed = ImageOps.exif_transpose(resized_image)
            if resized_image is not image:
                resized_image.close()
            if transposed.mode == "RGB":
                return transposed
            converted = transposed.convert("RGB")
            transposed.close()
            return converted
    except RuntimeError:
        raise
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError) as exc:
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
    cache_path: Path | None = None,
    max_decode_pixels: int | None = None,
    use_draft: bool = False,
    resize_before_copy: bool = False,
    publish_temp: Callable[[Path, Path], None] | None = None,
) -> Path:
    bounded_size = bounded_image_cache_size(max_size, minimum=minimum_size, maximum=maximum_size)
    cache_path = cache_path or resized_image_cache_path(path, cache_dir, bounded_size)
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return cache_path

    context = lock if lock is not None else nullcontext()
    with context:
        if cache_path.exists() and cache_path.stat().st_size > 0:
            return cache_path
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        image = open_image_rgb(
            path,
            max_size_hint=bounded_size if use_draft else None,
            max_decode_pixels=max_decode_pixels,
            resize_before_copy=resize_before_copy,
        )
        image.thumbnail((bounded_size, bounded_size))
        descriptor, temp_name = tempfile.mkstemp(
            dir=cache_path.parent,
            prefix=f".{cache_path.name}.",
            suffix=".tmp",
        )
        os.close(descriptor)
        temp_path = Path(temp_name)
        try:
            image.save(temp_path, format="JPEG", quality=quality, optimize=True, progressive=True)
            try:
                (publish_temp or os.replace)(temp_path, cache_path)
            except OSError:
                if not _is_nonempty_file(cache_path):
                    raise
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
    return cache_path


def _is_nonempty_file(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def image_file_data_url(path: str | Path, mime_type: str = "image/jpeg") -> str:
    encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"
