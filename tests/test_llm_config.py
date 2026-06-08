from __future__ import annotations

import unittest

from culvia import llm_config
from culvia.llm_config import LLMConfigEnvironment


class LLMConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_session = dict(llm_config.SESSION_LLM_CONFIG)
        self.original_secure = dict(llm_config.SECURE_LLM_CONFIG)
        self.original_persisted = dict(llm_config.PERSISTED_LLM_CONFIG)
        llm_config.clear_session_llm_config()
        llm_config.clear_secure_llm_config()
        llm_config.set_persisted_llm_config({})
        self.env_names = LLMConfigEnvironment(
            api_key="UNIT_LLM_API_KEY",
            base_url="UNIT_LLM_BASE_URL",
            endpoint="UNIT_LLM_ENDPOINT",
            model="UNIT_LLM_MODEL",
            provider="UNIT_LLM_PROVIDER",
            input_mode="UNIT_LLM_INPUT_MODE",
            prompt_preset="UNIT_LLM_PROMPT_PRESET",
            custom_prompt="UNIT_LLM_CUSTOM_PROMPT",
        )

    def tearDown(self) -> None:
        llm_config.clear_session_llm_config()
        llm_config.clear_secure_llm_config()
        llm_config.set_session_llm_config(self.original_session, replace=True)
        llm_config.set_secure_llm_config(self.original_secure)
        llm_config.set_persisted_llm_config(self.original_persisted)

    def test_clean_config_trims_and_keeps_known_fields_only(self) -> None:
        cleaned = llm_config.clean_llm_config(
            {
                "api_key": "  key  ",
                "model": " model ",
                "unknown": "ignored",
                "base_url": "",
            }
        )

        self.assertEqual(cleaned, {"api_key": "key", "model": "model"})

    def test_session_replace_clear_and_persisted_secret_filter(self) -> None:
        llm_config.set_session_llm_config({"model": "first"})
        llm_config.set_session_llm_config({"base_url": "https://session.test/v1"})

        self.assertEqual(
            llm_config.SESSION_LLM_CONFIG,
            {"model": "first", "base_url": "https://session.test/v1"},
        )

        llm_config.set_session_llm_config({"model": "second"}, replace=True)
        self.assertEqual(llm_config.SESSION_LLM_CONFIG, {"model": "second"})

        llm_config.clear_session_llm_config("model")
        self.assertEqual(llm_config.SESSION_LLM_CONFIG, {})

        secure = llm_config.set_secure_llm_config({"api_key": "keychain-key", "model": "ignored"})
        self.assertEqual(secure, {"api_key": "keychain-key"})
        self.assertEqual(llm_config.SECURE_LLM_CONFIG, {"api_key": "keychain-key"})
        llm_config.clear_secure_llm_config("api_key")
        self.assertEqual(llm_config.SECURE_LLM_CONFIG, {})

        persisted = llm_config.set_persisted_llm_config({"api_key": "must-not-persist", "model": "sqlite-model"})
        self.assertEqual(persisted, {"model": "sqlite-model"})
        self.assertNotIn("api_key", llm_config.PERSISTED_LLM_CONFIG)

    def test_active_config_uses_env_session_keychain_sqlite_priority(self) -> None:
        llm_config.set_persisted_llm_config({"model": "sqlite-model", "prompt_preset": "retouching"})
        llm_config.set_secure_llm_config({"api_key": "keychain-key"})
        llm_config.set_session_llm_config({"model": "session-model"})
        env = {"UNIT_LLM_MODEL": "env-model", "UNIT_LLM_BASE_URL": "https://env.test/v1"}

        layers = llm_config.llm_config_layers(env, self.env_names)
        active = llm_config.active_llm_config(layers)

        self.assertEqual(active["api_key"], "keychain-key")
        self.assertEqual(active["model"], "env-model")
        self.assertEqual(active["base_url"], "https://env.test/v1")
        self.assertEqual(active["prompt_preset"], "retouching")
        self.assertEqual(llm_config.llm_config_source("model", layers), "环境变量")
        self.assertEqual(llm_config.llm_config_source("api_key", layers), "系统钥匙串")
        self.assertEqual(llm_config.llm_config_source("provider", layers), "默认值")

        llm_config.set_session_llm_config({"api_key": "session-key"})
        layers = llm_config.llm_config_layers(env, self.env_names)
        self.assertEqual(llm_config.active_llm_config(layers)["api_key"], "session-key")
        self.assertEqual(llm_config.llm_config_source("api_key", layers), "当前会话")

    def test_env_config_accepts_openai_key_fallback(self) -> None:
        env = {"OPENAI_API_KEY": "fallback-key", "UNIT_LLM_MODEL": "unit-model"}

        config = llm_config.read_env_llm_config(env, self.env_names)

        self.assertEqual(config["api_key"], "fallback-key")
        self.assertEqual(config["model"], "unit-model")

    def test_prompt_preset_and_custom_text(self) -> None:
        presets = {
            "balanced": {"prompt": "默认提示"},
            "retouching": {"prompt": "修图提示"},
        }

        self.assertEqual(
            llm_config.normalize_llm_prompt_preset("retouching", presets, "balanced"),
            "retouching",
        )
        self.assertEqual(
            llm_config.normalize_llm_prompt_preset("missing", presets, "balanced"),
            "balanced",
        )
        self.assertEqual(
            llm_config.llm_review_prompt_text("balanced", presets, "保留胶片感"),
            "默认提示\n补充要求：保留胶片感",
        )

    def test_endpoint_input_mode_timeout_and_image_size(self) -> None:
        self.assertEqual(
            llm_config.llm_review_endpoint(
                {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/"},
                "https://api.openai.com/v1/chat/completions",
            ),
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        )
        self.assertEqual(
            llm_config.llm_review_endpoint(
                {"endpoint": "https://example.test/v1/chat/completions/"},
                "https://api.openai.com/v1/chat/completions",
            ),
            "https://example.test/v1/chat/completions",
        )
        self.assertEqual(llm_config.llm_review_input_mode({"input_mode": "TEXT"}), "text")
        self.assertEqual(llm_config.llm_review_input_mode({"input_mode": "video"}), "image")
        self.assertEqual(llm_config.llm_review_timeout({"TIMEOUT": "3"}, "TIMEOUT"), 10.0)
        self.assertEqual(llm_config.llm_review_timeout({"TIMEOUT": "bad"}, "TIMEOUT"), 90.0)
        self.assertEqual(llm_config.llm_review_max_image_size({"MAX": "99999"}, "MAX", 1024), 1600)
        self.assertEqual(llm_config.llm_review_max_image_size({"MAX": "bad"}, "MAX", 1024), 1024)

    def test_mask_api_key_only_shows_edges(self) -> None:
        self.assertEqual(llm_config.mask_llm_api_key(""), "未配置")
        self.assertEqual(llm_config.mask_llm_api_key("abcdef"), "ab****ef")
        self.assertEqual(
            llm_config.mask_llm_api_key("unit-test-api-key-0000000000003931"),
            "unit****3931",
        )


if __name__ == "__main__":
    unittest.main()
