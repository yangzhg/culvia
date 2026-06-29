from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from culvia.job_text import text_ref


class ModelCapabilityLike(Protocol):
    key: str
    model_id: str
    runtime_key: str
    requires_download: bool
    provider: str
    supports_text_insights: bool


def device_text_key(device: str | None) -> str:
    """i18n key for the device name, resolved by the web UI."""
    return "device.appleSilicon" if device == "mps" else "device.genericCpu"


def device_text(device: str | None) -> dict[str, Any]:
    return text_ref(device_text_key(device))


def normalize_network_mode(value: object) -> str:
    return str(value) if value in {"direct", "system"} else "direct"


def network_label_key(mode: str) -> str:
    return "network.systemConnection" if mode == "system" else "network.directConnection"


def network_payload(network: Mapping[str, Any], *, system_proxy_available: bool) -> dict[str, Any]:
    mode = normalize_network_mode(network.get("mode"))
    return {
        "mode": mode,
        "labelText": text_ref(network_label_key(mode)),
        "systemProxyAvailable": system_proxy_available,
    }


def llm_config_payload(
    *,
    status: Mapping[str, Any],
    prompt_preset: str,
    api_key: str,
    model: str,
    base_url: str,
    endpoint: str,
    custom_prompt: str,
    prompt_presets: Mapping[str, Mapping[str, Any]],
    mask_api_key: Callable[[str], str],
) -> dict[str, Any]:
    configured = bool(status.get("configured"))
    key_label = mask_api_key(api_key) if configured else ""
    return {
        "configured": configured,
        "source": status.get("sources", {}).get("apiKey") if configured else "",
        "model": model,
        "baseUrl": base_url,
        "endpoint": endpoint,
        "inputMode": status.get("inputMode") or "image",
        "promptPreset": prompt_preset,
        "customPrompt": custom_prompt,
        "promptPresets": [
            {
                "value": key,
                "label": str(config["label"]),
                "description": str(config["description"]),
                "prompt": str(config.get("prompt") or ""),
            }
            for key, config in prompt_presets.items()
        ],
        "keyLabel": key_label,
        "sources": status.get("sources", {}),
    }


def available_selected_models(selected_models: Sequence[str], *, llm_configured: bool, llm_model_key: str) -> list[str]:
    if llm_configured:
        return list(selected_models)
    return [model_key for model_key in selected_models if model_key != llm_model_key]


def model_runtime_keys(
    selected_models: Sequence[str],
    *,
    model_capabilities: Mapping[str, ModelCapabilityLike],
    excluded_runtime_keys: set[str],
) -> set[str]:
    return {
        model_capabilities[model_key].runtime_key
        for model_key in selected_models
        if model_key in model_capabilities and model_capabilities[model_key].runtime_key not in excluded_runtime_keys
    }


def model_option_payloads(
    selected_models: Sequence[str],
    *,
    model_keys: Sequence[str],
    model_capabilities: Mapping[str, ModelCapabilityLike],
    runtime_status: Mapping[str, Mapping[str, Any]],
    llm_status: Mapping[str, Any],
    llm_model_key: str,
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for model_key in model_keys:
        capability = model_capabilities[model_key]
        status = runtime_status.get(capability.runtime_key, {})
        is_llm = capability.key == llm_model_key
        available = (not is_llm) or bool(llm_status.get("configured"))
        state_text: dict[str, Any] | None = None
        detail_text: dict[str, Any] | None = None
        if is_llm:
            state_text = text_ref("model.configured") if available else text_ref("model.needsConfig")
            input_mode_key = "llm.inputMode.text" if llm_status.get("inputMode") == "text" else "llm.inputMode.image"
            detail_text = (
                text_ref(
                    "model.option.llm_review.detailConfigured",
                    model=str(llm_status["model"]),
                    inputMode=text_ref(input_mode_key),
                )
                if available
                else text_ref("model.option.llm_review.detailNeedsKey")
            )
        payloads.append(
            {
                "key": capability.key,
                "model": str(llm_status["model"]) if is_llm else capability.model_id,
                "requiresDownload": capability.requires_download,
                "downloaded": bool(status.get("downloaded")),
                "partial": bool(status.get("partial")),
                "size": status.get("model_size_label") or "",
                "selected": capability.key in selected_models and available,
                "disabled": not available,
                "stateText": state_text,
                "detailText": detail_text,
                "provider": capability.provider,
                "supportsTextInsights": capability.supports_text_insights,
            }
        )
    return payloads


def model_payload(
    *,
    model_id: str,
    selected_models: Sequence[str],
    options: Sequence[Mapping[str, Any]],
    core_status: Mapping[str, Any],
    clip_status: Mapping[str, Any],
    network_status: Mapping[str, Any],
    runtime_loaded: bool,
    runtime_device_text: Mapping[str, Any],
) -> dict[str, Any]:
    selected_downloadables = [option for option in options if option["selected"] and option["requiresDownload"]]
    downloaded = (
        all(bool(option["downloaded"]) for option in selected_downloadables) if selected_downloadables else True
    )
    any_downloaded = any(bool(option["downloaded"]) for option in selected_downloadables)
    partial = any(option["selected"] and option["requiresDownload"] and option["partial"] for option in options)
    if downloaded:
        state_key = "ready"
        tone = "ready"
    elif partial:
        state_key = "preparing"
        tone = "partial"
    elif any_downloaded:
        state_key = "partiallyReady"
        tone = "partial"
    else:
        state_key = "pending"
        tone = "missing"

    return {
        "id": model_id,
        "selected": list(selected_models),
        "options": list(options),
        "labelText": text_ref(f"model.state.{state_key}"),
        "tone": tone,
        "hintText": text_ref(f"model.hint.{state_key}"),
        "size": core_status.get("model_size_label") or "",
        "clipSize": clip_status.get("model_size_label") or "",
        "downloaded": downloaded,
        "runtimeLoaded": runtime_loaded,
        "runtimeDeviceText": dict(runtime_device_text),
        "proxyEnabled": network_status["mode"] == "system" and bool(network_status["systemProxyAvailable"]),
        "proxyLabelText": dict(network_status["labelText"]),
    }
