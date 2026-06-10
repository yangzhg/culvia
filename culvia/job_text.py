from __future__ import annotations

from typing import Any


def text_ref(key: str, **params: Any) -> dict[str, Any]:
    """Build a translatable text reference resolved by the web UI.

    The payload shape is ``{"key": ..., "params": {...}}``; param values may
    themselves be text refs, which the frontend resolves recursively.
    """
    if params:
        return {"key": key, "params": params}
    return {"key": key}


class TranslatableError(Exception):
    """Exception whose user-facing message is an i18n text reference.

    ``fallback`` keeps server logs readable; the web UI resolves ``text``.
    """

    def __init__(self, key: str, *, fallback: str = "", **params: Any) -> None:
        self.text = text_ref(key, **params)
        super().__init__(fallback or key)


class TranslatableValueError(TranslatableError, ValueError):
    pass


class TranslatableRuntimeError(TranslatableError, RuntimeError):
    pass


def exception_text(exc: BaseException) -> dict[str, Any] | None:
    """Text reference attached to ``exc``, or ``None`` for plain exceptions."""
    text = getattr(exc, "text", None)
    if isinstance(text, dict) and text.get("key"):
        return dict(text)
    return None


def exception_reason(exc: BaseException) -> dict[str, Any] | str:
    """Reason payload for API errors: a text ref when available, else ``str(exc)``."""
    return exception_text(exc) or str(exc)
