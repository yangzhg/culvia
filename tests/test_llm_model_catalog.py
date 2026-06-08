from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Any

from culvia.llm_model_catalog import fetch_llm_model_catalog, llm_models_url, parse_llm_model_list


@dataclass
class FakeResponse:
    status_code: int = 200
    payload: Any = None
    text: str = ""
    reason: str = "OK"

    def json(self) -> Any:
        if isinstance(self.payload, ValueError):
            raise self.payload
        return self.payload


class LlmModelCatalogTests(unittest.TestCase):
    def test_models_url_prefers_base_url_and_derives_from_endpoint(self) -> None:
        self.assertEqual(
            llm_models_url(
                "https://dashscope.aliyuncs.com/compatible-mode/v1/",
                "https://ignored.test/v1/chat/completions",
            ),
            "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
        )
        self.assertEqual(
            llm_models_url("", "https://api.openai.com/v1/chat/completions"),
            "https://api.openai.com/v1/models",
        )
        self.assertEqual(
            llm_models_url("", "https://api.openai.com/v1/responses"),
            "https://api.openai.com/v1/models",
        )

    def test_parse_model_list_pins_current_model_and_deduplicates(self) -> None:
        models = parse_llm_model_list(
            {
                "data": [
                    {"id": "qwen-plus"},
                    {"id": "qwen3.7-plus"},
                    {"id": "qwen-plus"},
                    {"id": ""},
                ]
            },
            "qwen3.7-plus",
        )

        self.assertEqual([item["value"] for item in models], ["qwen3.7-plus", "qwen-plus"])
        self.assertEqual(models[0]["source"], "current")

    def test_fetch_rejects_missing_api_key_without_request(self) -> None:
        calls: list[str] = []

        with self.assertRaisesRegex(ValueError, "API Key"):
            fetch_llm_model_catalog(
                api_key="",
                base_url="https://example.test/v1",
                endpoint="",
                current_model="mock-vlm",
                timeout=5,
                get=lambda url, **_: calls.append(url) or FakeResponse(),
            )

        self.assertEqual(calls, [])

    def test_fetch_returns_models_without_echoing_key(self) -> None:
        seen_headers: dict[str, str] = {}

        def get(url: str, **kwargs: Any) -> FakeResponse:
            seen_headers.update(kwargs["headers"])
            return FakeResponse(payload={"data": [{"id": "qwen-plus"}]})

        result = fetch_llm_model_catalog(
            api_key="unit-test-api-key-0000000000003931",
            base_url="https://example.test/v1",
            endpoint="",
            current_model="qwen-current",
            timeout=9,
            get=get,
        )

        self.assertEqual(result["modelsUrl"], "https://example.test/v1/models")
        self.assertEqual([item["value"] for item in result["models"]], ["qwen-current", "qwen-plus"])
        self.assertNotIn("api-key", str(result))
        self.assertEqual(seen_headers["Authorization"], "Bearer unit-test-api-key-0000000000003931")

    def test_fetch_reports_http_and_json_errors(self) -> None:
        with self.assertRaisesRegex(ValueError, "HTTP 401"):
            fetch_llm_model_catalog(
                api_key="key",
                base_url="https://example.test/v1",
                endpoint="",
                current_model="",
                timeout=5,
                get=lambda *_args, **_kwargs: FakeResponse(status_code=401, text="unauthorized"),
            )

        with self.assertRaisesRegex(ValueError, "没有返回 JSON"):
            fetch_llm_model_catalog(
                api_key="key",
                base_url="https://example.test/v1",
                endpoint="",
                current_model="",
                timeout=5,
                get=lambda *_args, **_kwargs: FakeResponse(payload=ValueError("bad json")),
            )


if __name__ == "__main__":
    unittest.main()
