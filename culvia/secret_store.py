from __future__ import annotations

import os
from typing import Any


SERVICE_NAME = "culvia"
LLM_API_KEY_USERNAME = "llm-review-api-key"
DISABLE_KEYCHAIN_ENV = "CULVIA_DISABLE_KEYCHAIN"


class SecretStoreError(Exception):
    """Raised when a system secret-store operation fails."""


class SecretStoreUnavailable(SecretStoreError):
    """Raised when the optional system keychain backend is unavailable."""


def _load_keyring(keyring_module: Any = None) -> Any:
    if os.environ.get(DISABLE_KEYCHAIN_ENV) == "1":
        raise SecretStoreUnavailable("system keychain backend is disabled")
    if keyring_module is not None:
        return keyring_module
    try:
        import keyring  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - depends on optional desktop extra.
        raise SecretStoreUnavailable("system keychain backend is unavailable") from exc
    return keyring


def keyring_available(keyring_module: Any = None) -> bool:
    try:
        keyring = _load_keyring(keyring_module)
    except SecretStoreUnavailable:
        return False
    return all(hasattr(keyring, name) for name in ("get_password", "set_password", "delete_password"))


def _handle_backend_error(exc: Exception) -> SecretStoreError:
    message = str(exc).strip() or exc.__class__.__name__
    return SecretStoreError(message)


def load_llm_api_key(*, keyring_module: Any = None) -> str:
    keyring = _load_keyring(keyring_module)
    try:
        return str(keyring.get_password(SERVICE_NAME, LLM_API_KEY_USERNAME) or "").strip()
    except Exception as exc:
        raise _handle_backend_error(exc) from exc


def save_llm_api_key(api_key: str, *, keyring_module: Any = None) -> None:
    key = str(api_key or "").strip()
    if not key:
        delete_llm_api_key(keyring_module=keyring_module)
        return
    keyring = _load_keyring(keyring_module)
    try:
        keyring.set_password(SERVICE_NAME, LLM_API_KEY_USERNAME, key)
    except Exception as exc:
        raise _handle_backend_error(exc) from exc


def delete_llm_api_key(*, keyring_module: Any = None) -> None:
    keyring = _load_keyring(keyring_module)
    try:
        keyring.delete_password(SERVICE_NAME, LLM_API_KEY_USERNAME)
    except Exception as exc:
        message = str(exc).lower()
        if "not found" in message or "no such" in message:
            return
        raise _handle_backend_error(exc) from exc
