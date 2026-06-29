from __future__ import annotations

import unittest

from culvia.llm_client import post_openai_compatible_chat


class FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self.payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> object:
        return self.payload


class LLMClientTests(unittest.TestCase):
    def test_missing_api_key_is_rejected_before_http_call(self) -> None:
        calls: list[dict[str, object]] = []
        credentials = {
            "api_key": "",
            "endpoint": "https://example.test/v1/chat/completions",
            "timeout": 5,
        }

        with self.assertRaises(RuntimeError):
            post_openai_compatible_chat(
                {"model": "mock"},
                **credentials,
                post=lambda **kwargs: calls.append(kwargs) or FakeResponse(200, {}),
            )

        self.assertEqual(calls, [])

    def test_successful_request_uses_bearer_header_and_returns_json_object(self) -> None:
        calls: list[dict[str, object]] = []
        credentials = {
            "api_key": "test-key",
            "endpoint": "https://example.test/v1/chat/completions",
            "timeout": 7,
        }

        result = post_openai_compatible_chat(
            {"model": "mock", "messages": []},
            **credentials,
            post=lambda *args, **kwargs: calls.append({"args": args, **kwargs}) or FakeResponse(200, {"ok": True}),
        )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(calls[0]["args"], ("https://example.test/v1/chat/completions",))
        self.assertEqual(calls[0]["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(calls[0]["timeout"], 7)

    def test_response_format_error_retries_without_response_format(self) -> None:
        calls: list[dict[str, object]] = []
        responses = [
            FakeResponse(400, {"error": "unsupported response_format"}),
            FakeResponse(200, {"choices": []}),
        ]
        credentials = {
            "api_key": "test-key",
            "endpoint": "https://example.test/v1/chat/completions",
            "timeout": 5,
        }

        result = post_openai_compatible_chat(
            {"model": "mock", "response_format": {"type": "json_object"}, "messages": []},
            **credentials,
            post=lambda *args, **kwargs: calls.append(kwargs) or responses.pop(0),
        )

        self.assertEqual(result, {"choices": []})
        self.assertIn("response_format", calls[0]["json"])
        self.assertNotIn("response_format", calls[1]["json"])

    def test_non_object_json_response_is_rejected(self) -> None:
        credentials = {
            "api_key": "test-key",
            "endpoint": "https://example.test/v1/chat/completions",
            "timeout": 5,
        }

        with self.assertRaises(RuntimeError):
            post_openai_compatible_chat(
                {"model": "mock"},
                **credentials,
                post=lambda *args, **kwargs: FakeResponse(200, []),
            )


if __name__ == "__main__":
    unittest.main()
