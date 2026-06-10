from __future__ import annotations

import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass

from culvia.image_io import bounded_image_cache_size

LLM_CONFIG_FIELDS = (
    "api_key",
    "base_url",
    "endpoint",
    "model",
    "provider",
    "input_mode",
    "prompt_preset",
    "custom_prompt",
)
LLM_CONFIG_LAYER_ORDER = ("env", "session", "keychain", "sqlite")
LLM_CONFIG_SOURCE_LABELS = {
    "env": "环境变量",
    "session": "当前会话",
    "keychain": "系统钥匙串",
    "sqlite": "SQLite",
}
DEFAULT_LLM_PROVIDER = "openai-compatible"
DEFAULT_LLM_INPUT_MODE = "image"
DEFAULT_LLM_TIMEOUT = 90.0
MIN_LLM_TIMEOUT = 10.0
DEFAULT_MAX_IMAGE_LIMIT = 1600


@dataclass(frozen=True)
class LLMConfigEnvironment:
    api_key: str
    base_url: str
    endpoint: str
    model: str
    provider: str
    input_mode: str
    prompt_preset: str
    custom_prompt: str
    fallback_api_key: str = "OPENAI_API_KEY"


LLM_CONFIG_LOCK = threading.Lock()
SESSION_LLM_CONFIG: dict[str, str] = {}
SECURE_LLM_CONFIG: dict[str, str] = {}
PERSISTED_LLM_CONFIG: dict[str, str] = {}


def clean_llm_config(config: Mapping[str, object] | None) -> dict[str, str]:
    if not config:
        return {}
    cleaned: dict[str, str] = {}
    for key in LLM_CONFIG_FIELDS:
        value = str(config.get(key) or "").strip()
        if value:
            cleaned[key] = value
    return cleaned


def set_session_llm_config(config: Mapping[str, object] | None, *, replace: bool = False) -> dict[str, str]:
    cleaned = clean_llm_config(config)
    with LLM_CONFIG_LOCK:
        if replace:
            SESSION_LLM_CONFIG.clear()
        SESSION_LLM_CONFIG.update(cleaned)
        return dict(SESSION_LLM_CONFIG)


def clear_session_llm_config(*keys: str) -> None:
    with LLM_CONFIG_LOCK:
        if keys:
            for key in keys:
                SESSION_LLM_CONFIG.pop(key, None)
        else:
            SESSION_LLM_CONFIG.clear()


def set_secure_llm_config(config: Mapping[str, object] | None) -> dict[str, str]:
    cleaned = clean_llm_config(config)
    if cleaned:
        cleaned = {"api_key": cleaned["api_key"]} if cleaned.get("api_key") else {}
    with LLM_CONFIG_LOCK:
        SECURE_LLM_CONFIG.clear()
        SECURE_LLM_CONFIG.update(cleaned)
        return dict(SECURE_LLM_CONFIG)


def clear_secure_llm_config(*keys: str) -> None:
    with LLM_CONFIG_LOCK:
        if keys:
            for key in keys:
                SECURE_LLM_CONFIG.pop(key, None)
        else:
            SECURE_LLM_CONFIG.clear()


def set_persisted_llm_config(config: Mapping[str, object] | None) -> dict[str, str]:
    cleaned = clean_llm_config(config)
    cleaned.pop("api_key", None)
    with LLM_CONFIG_LOCK:
        PERSISTED_LLM_CONFIG.clear()
        PERSISTED_LLM_CONFIG.update(cleaned)
        return dict(PERSISTED_LLM_CONFIG)


def read_env_llm_config(
    environ: Mapping[str, str] | None,
    names: LLMConfigEnvironment,
) -> dict[str, str]:
    source = os.environ if environ is None else environ
    return clean_llm_config(
        {
            "api_key": source.get(names.api_key) or source.get(names.fallback_api_key) or "",
            "base_url": source.get(names.base_url) or "",
            "endpoint": source.get(names.endpoint) or "",
            "model": source.get(names.model) or "",
            "provider": source.get(names.provider) or "",
            "input_mode": source.get(names.input_mode) or "",
            "prompt_preset": source.get(names.prompt_preset) or "",
            "custom_prompt": source.get(names.custom_prompt) or "",
        }
    )


def llm_config_layers(
    environ: Mapping[str, str] | None,
    names: LLMConfigEnvironment,
) -> dict[str, dict[str, str]]:
    with LLM_CONFIG_LOCK:
        session_config = dict(SESSION_LLM_CONFIG)
        secure_config = dict(SECURE_LLM_CONFIG)
        persisted_config = dict(PERSISTED_LLM_CONFIG)
    return {
        "env": read_env_llm_config(environ, names),
        "session": clean_llm_config(session_config),
        "keychain": clean_llm_config(secure_config),
        "sqlite": clean_llm_config(persisted_config),
    }


def active_llm_config(layers: Mapping[str, Mapping[str, str]]) -> dict[str, str]:
    active: dict[str, str] = {}
    for field in LLM_CONFIG_FIELDS:
        for layer_name in LLM_CONFIG_LAYER_ORDER:
            value = layers.get(layer_name, {}).get(field)
            if value:
                active[field] = value
                break
    return active


def llm_config_source(field: str, layers: Mapping[str, Mapping[str, str]]) -> str:
    for layer_name in LLM_CONFIG_LAYER_ORDER:
        if layers.get(layer_name, {}).get(field):
            return LLM_CONFIG_SOURCE_LABELS[layer_name]
    return "默认值"


def normalize_llm_prompt_preset(
    value: object,
    presets: Mapping[str, object],
    default_preset: str,
) -> str:
    key = str(value or "").strip()
    return key if key in presets else default_preset


def llm_review_prompt_text(
    preset: str,
    presets: Mapping[str, Mapping[str, object]],
    custom_prompt: str = "",
) -> str:
    parts = [str(presets[preset]["prompt"])]
    custom = str(custom_prompt or "").strip()
    if custom:
        parts.append(f"补充要求：{custom}")
    return "\n".join(parts)


def mask_llm_api_key(api_key: str) -> str:
    # Empty keys mask to empty; the web UI shows its own localized "not configured" label.
    key = str(api_key or "").strip()
    if not key:
        return ""
    if len(key) <= 8:
        return f"{key[:2]}****{key[-2:]}"
    return f"{key[:4]}****{key[-4:]}"


def llm_review_endpoint(config: Mapping[str, str], default_endpoint: str) -> str:
    explicit = config.get("endpoint")
    if explicit:
        return explicit.rstrip("/")
    base_url = (config.get("base_url") or default_endpoint).rstrip("/")
    if base_url.endswith("/chat/completions"):
        return base_url
    return f"{base_url}/chat/completions"


def llm_review_input_mode(config: Mapping[str, str]) -> str:
    explicit = str(config.get("input_mode") or "").strip().lower()
    if explicit in {"image", "text"}:
        return explicit
    return DEFAULT_LLM_INPUT_MODE


def llm_review_timeout(
    environ: Mapping[str, str] | None,
    env_name: str,
    default: float = DEFAULT_LLM_TIMEOUT,
) -> float:
    source = os.environ if environ is None else environ
    try:
        return max(MIN_LLM_TIMEOUT, float(source.get(env_name) or default))
    except Exception:
        return default


def llm_review_max_image_size(
    environ: Mapping[str, str] | None,
    env_name: str,
    default_size: int,
    *,
    maximum: int = DEFAULT_MAX_IMAGE_LIMIT,
) -> int:
    source = os.environ if environ is None else environ
    try:
        return bounded_image_cache_size(int(source.get(env_name) or default_size), maximum=maximum)
    except Exception:
        return default_size
