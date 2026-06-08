from __future__ import annotations

import unittest
from dataclasses import dataclass

from culvia.config_payloads import (
    available_selected_models,
    device_label,
    llm_config_payload,
    model_option_payloads,
    model_payload,
    model_runtime_keys,
    network_payload,
    normalize_network_mode,
)


@dataclass(frozen=True)
class FakeCapability:
    key: str
    label: str
    subtitle: str
    model_id: str
    runtime_key: str
    requires_download: bool
    provider: str = "local"
    supports_text_insights: bool = False


class ConfigPayloadTests(unittest.TestCase):
    def test_network_payload_uses_friendly_labels(self) -> None:
        self.assertEqual(normalize_network_mode("weird"), "direct")
        self.assertEqual(network_payload({"mode": "direct"}, system_proxy_available=True)["label"], "普通连接")

        payload = network_payload({"mode": "system"}, system_proxy_available=True)

        self.assertEqual(payload["mode"], "system")
        self.assertEqual(payload["label"], "跟随系统设置")
        self.assertTrue(payload["systemProxyAvailable"])

    def test_llm_config_payload_masks_key_and_preserves_prompt_presets(self) -> None:
        payload = llm_config_payload(
            status={"configured": True, "inputMode": "text", "sources": {"apiKey": "session"}},
            prompt_preset="balanced",
            api_key="unit-test-api-key-0000000000003931",
            model="qwen-plus",
            base_url="https://example.test/v1",
            endpoint="https://example.test/v1/chat/completions",
            custom_prompt="更重视情绪",
            prompt_presets={"balanced": {"label": "综合", "description": "审美优先"}},
            mask_api_key=lambda key: f"{key[:4]}****{key[-4:]}",
        )

        self.assertTrue(payload["configured"])
        self.assertEqual(payload["keyLabel"], "unit****3931")
        self.assertNotIn("test-api-key", str(payload))
        self.assertEqual(payload["source"], "session")
        self.assertEqual(payload["inputMode"], "text")
        self.assertEqual(payload["promptPresets"], [{"value": "balanced", "label": "综合", "description": "审美优先"}])

    def test_llm_config_payload_hides_unconfigured_key(self) -> None:
        payload = llm_config_payload(
            status={"configured": False, "sources": {"apiKey": "session"}},
            prompt_preset="balanced",
            api_key="secret",
            model="qwen-plus",
            base_url="",
            endpoint="",
            custom_prompt="",
            prompt_presets={},
            mask_api_key=lambda key: key,
        )

        self.assertFalse(payload["configured"])
        self.assertEqual(payload["keyLabel"], "未配置")
        self.assertEqual(payload["source"], "未配置")

    def test_model_options_disable_llm_until_configured(self) -> None:
        capabilities = {
            "core": FakeCapability("core", "核心审美", "构图光线", "core-model", "core-runtime", True),
            "llm": FakeCapability(
                "llm",
                "大模型评审",
                "文本评价",
                "default-llm",
                "llm-runtime",
                False,
                provider="openai-compatible",
                supports_text_insights=True,
            ),
        }

        options = model_option_payloads(
            ["core", "llm"],
            model_keys=["core", "llm"],
            model_capabilities=capabilities,
            runtime_status={
                "core-runtime": {"downloaded": True, "partial": False, "model_size_label": "123 MB"},
                "llm-runtime": {"downloaded": False, "partial": False, "model_size_label": "需配置"},
            },
            llm_status={"configured": False, "model": "qwen-plus", "inputMode": "image"},
            llm_model_key="llm",
        )

        self.assertTrue(options[0]["selected"])
        self.assertEqual(options[0]["size"], "123 MB")
        self.assertFalse(options[1]["selected"])
        self.assertTrue(options[1]["disabled"])
        self.assertEqual(options[1]["state"], "需配置")

    def test_model_payload_reports_partial_and_proxy_state(self) -> None:
        payload = model_payload(
            model_id="main-model",
            selected_models=["core"],
            options=[
                {"selected": True, "requiresDownload": True, "downloaded": False, "partial": True},
                {"selected": False, "requiresDownload": False, "downloaded": True, "partial": False},
            ],
            core_status={"model_size_label": "333 MB"},
            clip_status={"model_size_label": "900 MB"},
            network_status={"mode": "system", "label": "跟随系统设置", "systemProxyAvailable": True},
            runtime_loaded=False,
            runtime_device_label="Apple 芯片加速",
        )

        self.assertEqual(payload["tone"], "partial")
        self.assertEqual(payload["label"], "模型准备中")
        self.assertFalse(payload["downloaded"])
        self.assertTrue(payload["proxyEnabled"])
        self.assertEqual(payload["runtimeDevice"], "Apple 芯片加速")

    def test_model_selection_helpers(self) -> None:
        capabilities = {
            "core": FakeCapability("core", "核心", "", "core-model", "core-runtime", True),
            "local": FakeCapability("local", "本地", "", "local-model", "local-runtime", False),
            "llm": FakeCapability("llm", "大模型", "", "llm-model", "llm-runtime", False),
        }

        self.assertEqual(
            available_selected_models(["core", "llm"], llm_configured=False, llm_model_key="llm"), ["core"]
        )
        self.assertEqual(device_label("mps"), "Apple 芯片加速")
        self.assertEqual(device_label("cpu"), "通用处理器")
        self.assertEqual(
            model_runtime_keys(
                ["core", "local", "llm"],
                model_capabilities=capabilities,
                excluded_runtime_keys={"local-runtime", "llm-runtime"},
            ),
            {"core-runtime"},
        )


if __name__ == "__main__":
    unittest.main()
