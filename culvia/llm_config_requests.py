from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from culvia.llm_config import normalize_llm_prompt_preset


@dataclass(frozen=True)
class LLMConfigUpdate:
    config: dict[str, str]
    clear_api_key: bool
    persist: bool


def llm_config_from_payload(
    payload: Mapping[str, object],
    *,
    prompt_presets: Mapping[str, object],
    default_prompt_preset: str,
) -> dict[str, str]:
    return {
        "api_key": str(payload.get("apiKey") or "").strip(),
        "base_url": str(payload.get("baseUrl") or "").strip(),
        "endpoint": str(payload.get("endpoint") or "").strip(),
        "model": str(payload.get("model") or "").strip(),
        "prompt_preset": normalize_llm_prompt_preset(
            payload.get("promptPreset") or default_prompt_preset,
            prompt_presets,
            default_prompt_preset,
        ),
        "custom_prompt": str(payload.get("customPrompt") or "").strip(),
        "input_mode": str(payload.get("inputMode") or "").strip(),
    }


def llm_config_update_from_payload(
    payload: Mapping[str, object],
    *,
    prompt_presets: Mapping[str, object],
    default_prompt_preset: str,
) -> LLMConfigUpdate:
    api_key = str(payload.get("apiKey") or "").strip()
    clear_key = bool(payload.get("clearKey"))
    config = llm_config_from_payload(
        payload,
        prompt_presets=prompt_presets,
        default_prompt_preset=default_prompt_preset,
    )

    if clear_key:
        config["api_key"] = ""
    elif not api_key:
        config.pop("api_key", None)

    return LLMConfigUpdate(config=config, clear_api_key=clear_key, persist=bool(payload.get("persist")))
