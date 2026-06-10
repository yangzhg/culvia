from __future__ import annotations

import unittest
from dataclasses import dataclass

from culvia.config_payloads import (
    available_selected_models,
    device_text,
    device_text_key,
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
    model_id: str
    runtime_key: str
    requires_download: bool
    provider: str = "local"
    supports_text_insights: bool = False


class ConfigPayloadTests(unittest.TestCase):
    def test_network_payload_uses_text_refs(self) -> None:
        self.assertEqual(normalize_network_mode("weird"), "direct")
        self.assertEqual(
            network_payload({"mode": "direct"}, system_proxy_available=True)["labelText"],
            {"key": "network.directConnection"},
        )

        payload = network_payload({"mode": "system"}, system_proxy_available=True)

        self.assertEqual(payload["mode"], "system")
        self.assertEqual(payload["labelText"], {"key": "network.systemConnection"})
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
            prompt_presets={"balanced": {"label": "综合", "description": "审美优先", "prompt": "默认提示词文本"}},
            mask_api_key=lambda key: f"{key[:4]}****{key[-4:]}",
        )

        self.assertTrue(payload["configured"])
        self.assertEqual(payload["keyLabel"], "unit****3931")
        self.assertNotIn("test-api-key", str(payload))
        self.assertEqual(payload["source"], "session")
        self.assertEqual(payload["inputMode"], "text")
        self.assertEqual(
            payload["promptPresets"],
            [{"value": "balanced", "label": "综合", "description": "审美优先", "prompt": "默认提示词文本"}],
        )

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
        self.assertEqual(payload["keyLabel"], "")
        self.assertEqual(payload["source"], "")

    def test_model_options_disable_llm_until_configured(self) -> None:
        capabilities = {
            "core": FakeCapability("core", "core-model", "core-runtime", True),
            "llm": FakeCapability(
                "llm",
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
                "llm-runtime": {"downloaded": False, "partial": False, "model_size_label": ""},
            },
            llm_status={"configured": False, "model": "qwen-plus", "inputMode": "image"},
            llm_model_key="llm",
        )

        self.assertTrue(options[0]["selected"])
        self.assertEqual(options[0]["size"], "123 MB")
        self.assertIsNone(options[0]["stateText"])
        self.assertIsNone(options[0]["detailText"])
        self.assertFalse(options[1]["selected"])
        self.assertTrue(options[1]["disabled"])
        self.assertEqual(options[1]["stateText"], {"key": "model.needsConfig"})
        self.assertEqual(options[1]["detailText"], {"key": "model.option.llm_review.detailNeedsKey"})

    def test_model_options_describe_configured_llm(self) -> None:
        capabilities = {
            "llm": FakeCapability(
                "llm",
                "default-llm",
                "llm-runtime",
                False,
                provider="openai-compatible",
                supports_text_insights=True,
            ),
        }

        options = model_option_payloads(
            ["llm"],
            model_keys=["llm"],
            model_capabilities=capabilities,
            runtime_status={"llm-runtime": {"downloaded": True, "partial": False, "model_size_label": ""}},
            llm_status={"configured": True, "model": "qwen-plus", "inputMode": "text"},
            llm_model_key="llm",
        )

        self.assertEqual(options[0]["stateText"], {"key": "model.configured"})
        self.assertEqual(
            options[0]["detailText"],
            {
                "key": "model.option.llm_review.detailConfigured",
                "params": {"model": "qwen-plus", "inputMode": {"key": "llm.inputMode.text"}},
            },
        )

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
            network_status={
                "mode": "system",
                "labelText": {"key": "network.systemConnection"},
                "systemProxyAvailable": True,
            },
            runtime_loaded=False,
            runtime_device_text={"key": "device.appleSilicon"},
        )

        self.assertEqual(payload["tone"], "partial")
        self.assertEqual(payload["labelText"], {"key": "model.state.preparing"})
        self.assertEqual(payload["hintText"], {"key": "model.hint.preparing"})
        self.assertFalse(payload["downloaded"])
        self.assertTrue(payload["proxyEnabled"])
        self.assertEqual(payload["proxyLabelText"], {"key": "network.systemConnection"})
        self.assertEqual(payload["runtimeDeviceText"], {"key": "device.appleSilicon"})

    def test_model_selection_helpers(self) -> None:
        capabilities = {
            "core": FakeCapability("core", "core-model", "core-runtime", True),
            "local": FakeCapability("local", "local-model", "local-runtime", False),
            "llm": FakeCapability("llm", "llm-model", "llm-runtime", False),
        }

        self.assertEqual(
            available_selected_models(["core", "llm"], llm_configured=False, llm_model_key="llm"), ["core"]
        )
        self.assertEqual(device_text_key("mps"), "device.appleSilicon")
        self.assertEqual(device_text_key("cpu"), "device.genericCpu")
        self.assertEqual(device_text("mps"), {"key": "device.appleSilicon"})
        self.assertEqual(device_text("cpu"), {"key": "device.genericCpu"})
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
