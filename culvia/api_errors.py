from __future__ import annotations

from typing import Any

from starlette.responses import JSONResponse


def api_error_payload(
    error_code: str, message: str, params: dict[str, Any] | None = None, **extra: Any
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "error": message,
        "errorCode": error_code,
        "errorParams": params or {},
    }
    payload.update(extra)
    return payload


def api_error_response(
    error_code: str,
    message: str,
    *,
    status_code: int = 400,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    **extra: Any,
) -> JSONResponse:
    return JSONResponse(
        api_error_payload(error_code, message, params, **extra), status_code=status_code, headers=headers
    )
