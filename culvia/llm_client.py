from __future__ import annotations

from typing import Callable, Protocol

import requests


class LLMHTTPResponse(Protocol):
    status_code: int

    def raise_for_status(self) -> None: ...

    def json(self) -> object: ...


LLMPost = Callable[..., LLMHTTPResponse]


def post_openai_compatible_chat(
    payload: dict[str, object],
    *,
    api_key: str,
    endpoint: str,
    timeout: float,
    post: LLMPost = requests.post,
) -> dict[str, object]:
    if not api_key:
        raise RuntimeError("大模型评审未配置：请设置 CULVIA_LLM_API_KEY 或 OPENAI_API_KEY。")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    response = post(endpoint, headers=headers, json=payload, timeout=timeout)
    if response.status_code >= 400 and "response_format" in payload:
        retry_payload = dict(payload)
        retry_payload.pop("response_format", None)
        response = post(endpoint, headers=headers, json=retry_payload, timeout=timeout)
    response.raise_for_status()
    parsed = response.json()
    if not isinstance(parsed, dict):
        raise RuntimeError("大模型接口返回内容不是 JSON 对象。")
    return dict(parsed)
