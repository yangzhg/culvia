from __future__ import annotations

from pathlib import Path

from starlette.responses import FileResponse, Response

from culvia.api_errors import api_error_response
from culvia.media_service import ensure_thumbnail_file, resized_jpeg_bytes

MEDIA_ERROR_VARY_HEADERS = {"Vary": "Accept"}


def accepts_json(accept_header: str) -> bool:
    for item in str(accept_header or "").split(","):
        parts = [part.strip() for part in item.split(";")]
        media_type = parts[0].lower() if parts else ""
        quality = 1.0
        for part in parts[1:]:
            if not part.lower().startswith("q="):
                continue
            try:
                quality = float(part.split("=", 1)[1])
            except ValueError:
                quality = 0.0
            break
        if quality <= 0:
            continue
        if media_type == "application/json" or media_type.endswith("+json"):
            return True
    return False


def unavailable_media_response(kind: str, status_code: int, *, wants_json: bool = False) -> Response:
    if status_code == 403:
        message = "thumbnail access denied" if kind == "thumbnail" else "image access denied"
        if wants_json:
            error_code = "thumbnailAccessDenied" if kind == "thumbnail" else "imageAccessDenied"
            return api_error_response(
                error_code, message, status_code=403, params={"kind": kind}, headers=MEDIA_ERROR_VARY_HEADERS
            )
        return Response(message, status_code=403, headers=MEDIA_ERROR_VARY_HEADERS)
    if wants_json:
        return api_error_response(
            "mediaNotFound", "image not found", status_code=404, params={"kind": kind}, headers=MEDIA_ERROR_VARY_HEADERS
        )
    return Response("image not found", status_code=404, headers=MEDIA_ERROR_VARY_HEADERS)


def image_media_response(path: Path | None, status_code: int, max_size: int, *, wants_json: bool = False) -> Response:
    if path is None:
        return unavailable_media_response("image", status_code, wants_json=wants_json)
    try:
        return Response(resized_jpeg_bytes(path, max_size), media_type="image/jpeg")
    except Exception as exc:
        if wants_json:
            return api_error_response(
                "imageGenerationFailed",
                "image failed",
                status_code=500,
                params={"kind": "image", "reason": exc.__class__.__name__},
                headers=MEDIA_ERROR_VARY_HEADERS,
            )
        return Response(f"image failed: {exc!r}", status_code=500, headers=MEDIA_ERROR_VARY_HEADERS)


def thumbnail_media_response(
    path: Path | None,
    status_code: int,
    max_size: int,
    *,
    cache_dir: Path,
    lock: object | None = None,
    wants_json: bool = False,
) -> Response:
    if path is None:
        return unavailable_media_response("thumbnail", status_code, wants_json=wants_json)
    try:
        thumb_path = ensure_thumbnail_file(path, cache_dir, max_size, lock=lock)
    except Exception as exc:
        if wants_json:
            return api_error_response(
                "thumbnailGenerationFailed",
                "thumbnail failed",
                status_code=500,
                params={"kind": "thumbnail", "reason": exc.__class__.__name__},
                headers=MEDIA_ERROR_VARY_HEADERS,
            )
        return Response(f"thumbnail failed: {exc!r}", status_code=500, headers=MEDIA_ERROR_VARY_HEADERS)
    return FileResponse(thumb_path, media_type="image/jpeg")
