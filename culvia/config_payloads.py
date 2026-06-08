from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol


class ModelCapabilityLike(Protocol):
    key: str
    label: str
    subtitle: str
    model_id: str
    runtime_key: str
    requires_download: bool
    provider: str
    supports_text_insights: bool


def device_label(device: str | None) -> str:
    return "Apple 芯片加速" if device == "mps" else "通用处理器"


def normalize_network_mode(value: object) -> str:
    return str(value) if value in {"direct", "system"} else "direct"


def network_payload(network: Mapping[str, Any], *, system_proxy_available: bool) -> dict[str, Any]:
    mode = normalize_network_mode(network.get("mode"))
    label = "跟随系统设置" if mode == "system" else "普通连接"
    return {
        "mode": mode,
        "label": label,
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
    key_label = mask_api_key(api_key) if configured else "未配置"
    return {
        "configured": configured,
        "source": status.get("sources", {}).get("apiKey") if configured else "未配置",
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
        state = ""
        detail = ""
        if is_llm:
            state = "已配置" if available else "需配置"
            input_mode_label = "文本评审" if llm_status.get("inputMode") == "text" else "图片评审"
            detail = (
                f"使用 {llm_status['model']} · {input_mode_label} · 生成影像评价和建议"
                if available
                else "设置 CULVIA_LLM_API_KEY 或 OPENAI_API_KEY 后可用"
            )
        payloads.append(
            {
                "key": capability.key,
                "label": capability.label,
                "subtitle": capability.subtitle,
                "model": str(llm_status["model"]) if is_llm else capability.model_id,
                "requiresDownload": capability.requires_download,
                "downloaded": bool(status.get("downloaded")),
                "partial": bool(status.get("partial")),
                "size": status.get("model_size_label") or "未知",
                "selected": capability.key in selected_models and available,
                "disabled": not available,
                "state": state,
                "detail": detail,
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
    runtime_device_label: str,
) -> dict[str, Any]:
    selected_downloadables = [option for option in options if option["selected"] and option["requiresDownload"]]
    downloaded = (
        all(bool(option["downloaded"]) for option in selected_downloadables) if selected_downloadables else True
    )
    any_downloaded = any(bool(option["downloaded"]) for option in selected_downloadables)
    partial = any(option["selected"] and option["requiresDownload"] and option["partial"] for option in options)
    if downloaded:
        label = "模型已就绪"
        tone = "ready"
        hint = "可直接开始评分"
    elif partial:
        label = "模型准备中"
        tone = "partial"
        hint = "首次评分会继续下载"
    elif any_downloaded:
        label = "部分模型待准备"
        tone = "partial"
        hint = "首次使用新增模型会自动下载"
    else:
        label = "模型待准备"
        tone = "missing"
        hint = "首次评分会自动下载"

    return {
        "id": model_id,
        "selected": list(selected_models),
        "options": list(options),
        "label": label,
        "tone": tone,
        "hint": hint,
        "size": core_status.get("model_size_label") or "未知",
        "clipSize": clip_status.get("model_size_label") or "未知",
        "downloaded": downloaded,
        "runtimeLoaded": runtime_loaded,
        "runtimeDevice": runtime_device_label,
        "proxyEnabled": network_status["mode"] == "system" and bool(network_status["systemProxyAvailable"]),
        "proxyLabel": network_status["label"],
    }
