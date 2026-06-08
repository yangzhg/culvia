from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol


class ResponseLike(Protocol):
    status_code: int
    text: str
    reason: str

    def json(self) -> Any: ...


HttpGet = Callable[..., ResponseLike]


def llm_models_url(base_url: str, endpoint: str) -> str:
    base = base_url.strip().rstrip("/")
    if base:
        return f"{base}/models"

    endpoint_text = endpoint.strip()
    for suffix in ("/chat/completions", "/responses"):
        if endpoint_text.endswith(suffix):
            return endpoint_text[: -len(suffix)].rstrip("/") + "/models"
    return endpoint_text.rstrip("/") + "/models"


def parse_llm_model_list(payload: Any, current_model: str) -> list[dict[str, str]]:
    raw_items = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(raw_items, list):
        raw_items = []

    seen: set[str] = set()
    model_ids: list[str] = []
    for item in raw_items:
        if isinstance(item, dict):
            model_id = str(item.get("id") or "").strip()
        else:
            model_id = str(item or "").strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        model_ids.append(model_id)

    current = current_model.strip()
    if current and current not in seen:
        model_ids.insert(0, current)

    pinned = [current] if current and current in model_ids else []
    rest = sorted((model_id for model_id in model_ids if model_id != current), key=str.casefold)
    return [
        {
            "value": model_id,
            "label": model_id,
            "source": "current" if model_id == current else "provider",
        }
        for model_id in [*pinned, *rest]
    ]


def fetch_llm_model_catalog(
    *,
    api_key: str,
    base_url: str,
    endpoint: str,
    current_model: str,
    timeout: float,
    get: HttpGet,
) -> dict[str, Any]:
    cleaned_key = api_key.strip()
    if not cleaned_key:
        raise ValueError("请先填写或保存 API Key。")

    models_url = llm_models_url(base_url, endpoint)
    response = get(
        models_url,
        headers={"Authorization": f"Bearer {cleaned_key}"},
        timeout=timeout,
    )
    if response.status_code >= 400:
        detail = response.text.strip()[:240] or response.reason
        raise ValueError(f"模型列表读取失败：HTTP {response.status_code} {detail}")

    try:
        response_payload = response.json()
    except ValueError as exc:
        raise ValueError("模型列表读取失败：接口没有返回 JSON。") from exc

    models = parse_llm_model_list(response_payload, current_model)
    if not models:
        raise ValueError("模型列表为空。")
    return {
        "models": models,
        "currentModel": current_model,
        "modelsUrl": models_url,
    }
