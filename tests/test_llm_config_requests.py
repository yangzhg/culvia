from __future__ import annotations

import unittest

from culvia.llm_config_requests import llm_config_from_payload, llm_config_update_from_payload


PROMPT_PRESETS = {
    "balanced": {"label": "综合评审"},
    "technical": {"label": "技术质检"},
}


class LLMConfigRequestTests(unittest.TestCase):
    def test_llm_config_from_payload_trims_and_normalizes_fields(self) -> None:
        config = llm_config_from_payload(
            {
                "apiKey": "  session-key  ",
                "baseUrl": " https://example.test/v1 ",
                "endpoint": " /chat/completions ",
                "model": " mock-vlm ",
                "promptPreset": "technical",
                "customPrompt": " 保留胶片感 ",
                "inputMode": " image ",
            },
            prompt_presets=PROMPT_PRESETS,
            default_prompt_preset="balanced",
        )

        self.assertEqual(
            config,
            {
                "api_key": "session-key",
                "base_url": "https://example.test/v1",
                "endpoint": "/chat/completions",
                "model": "mock-vlm",
                "prompt_preset": "technical",
                "custom_prompt": "保留胶片感",
                "input_mode": "image",
            },
        )

    def test_llm_config_from_payload_falls_back_to_default_prompt_preset(self) -> None:
        config = llm_config_from_payload(
            {"promptPreset": "missing"},
            prompt_presets=PROMPT_PRESETS,
            default_prompt_preset="balanced",
        )

        self.assertEqual(config["prompt_preset"], "balanced")

    def test_update_omits_api_key_when_key_was_not_submitted(self) -> None:
        update = llm_config_update_from_payload(
            {"model": "mock-vlm"},
            prompt_presets=PROMPT_PRESETS,
            default_prompt_preset="balanced",
        )

        self.assertFalse(update.clear_api_key)
        self.assertFalse(update.persist)
        self.assertNotIn("api_key", update.config)
        self.assertEqual(update.config["model"], "mock-vlm")

    def test_update_can_clear_api_key(self) -> None:
        update = llm_config_update_from_payload(
            {"apiKey": "ignored", "clearKey": True},
            prompt_presets=PROMPT_PRESETS,
            default_prompt_preset="balanced",
        )

        self.assertTrue(update.clear_api_key)
        self.assertEqual(update.config["api_key"], "")

    def test_update_keeps_persist_flag(self) -> None:
        update = llm_config_update_from_payload(
            {"apiKey": "session-key", "persist": True},
            prompt_presets=PROMPT_PRESETS,
            default_prompt_preset="balanced",
        )

        self.assertTrue(update.persist)
        self.assertEqual(update.config["api_key"], "session-key")


if __name__ == "__main__":
    unittest.main()
