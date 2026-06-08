from __future__ import annotations

import unittest
from pathlib import Path
from typing import Mapping

from culvia.llm_config_service import (
    LLMConfigServiceDependencies,
    apply_llm_config_action,
    refresh_persisted_llm_config_action,
)
from culvia.secret_store import SecretStoreError, SecretStoreUnavailable


PROMPT_PRESETS = {
    "balanced": {"label": "综合评审"},
    "technical": {"label": "技术质检"},
}


class FakeLLMConfigEnvironment:
    def __init__(self) -> None:
        self.session: dict[str, str] = {}
        self.secure: dict[str, str] = {}
        self.persisted: dict[str, str] = {}
        self.loaded_persisted: dict[str, str] = {}
        self.loaded_api_key = ""
        self.saved_api_key = ""
        self.deleted_api_key = False
        self.saved_persisted_config: dict[str, object] = {}
        self.load_persisted_error: Exception | None = None
        self.load_api_key_error: Exception | None = None
        self.save_api_key_error: Exception | None = None
        self.delete_api_key_error: Exception | None = None
        self.cleared_session_keys: list[tuple[str, ...]] = []
        self.cleared_secure_keys: list[tuple[str, ...]] = []

    def dependencies(self) -> LLMConfigServiceDependencies:
        return LLMConfigServiceDependencies(
            prompt_presets=PROMPT_PRESETS,
            default_prompt_preset="balanced",
            load_persisted_config=self.load_persisted_config,
            save_persisted_config=self.save_persisted_config,
            set_persisted_config=self.set_persisted_config,
            set_session_config=self.set_session_config,
            clear_session_config=self.clear_session_config,
            set_secure_config=self.set_secure_config,
            clear_secure_config=self.clear_secure_config,
            load_api_key=self.load_api_key,
            save_api_key=self.save_api_key,
            delete_api_key=self.delete_api_key,
        )

    def load_persisted_config(self, _: str | Path) -> Mapping[str, object]:
        if self.load_persisted_error is not None:
            raise self.load_persisted_error
        return self.loaded_persisted

    def save_persisted_config(self, config: Mapping[str, object], _: str | Path) -> Mapping[str, str]:
        self.saved_persisted_config = dict(config)
        return {
            key: str(value).strip() for key, value in config.items() if key != "api_key" and str(value or "").strip()
        }

    def set_persisted_config(self, config: Mapping[str, object] | None) -> Mapping[str, str]:
        self.persisted = {
            key: str(value).strip()
            for key, value in (config or {}).items()
            if key != "api_key" and str(value or "").strip()
        }
        return dict(self.persisted)

    def set_session_config(self, config: Mapping[str, object] | None) -> Mapping[str, str]:
        for key, value in (config or {}).items():
            cleaned = str(value or "").strip()
            if cleaned:
                self.session[key] = cleaned
        return dict(self.session)

    def clear_session_config(self, *keys: str) -> None:
        self.cleared_session_keys.append(tuple(keys))
        if keys:
            for key in keys:
                self.session.pop(key, None)
        else:
            self.session.clear()

    def set_secure_config(self, config: Mapping[str, object] | None) -> Mapping[str, str]:
        key = str((config or {}).get("api_key") or "").strip()
        self.secure = {"api_key": key} if key else {}
        return dict(self.secure)

    def clear_secure_config(self, *keys: str) -> None:
        self.cleared_secure_keys.append(tuple(keys))
        if keys:
            for key in keys:
                self.secure.pop(key, None)
        else:
            self.secure.clear()

    def load_api_key(self) -> str:
        if self.load_api_key_error is not None:
            raise self.load_api_key_error
        return self.loaded_api_key

    def save_api_key(self, api_key: str) -> None:
        if self.save_api_key_error is not None:
            raise self.save_api_key_error
        self.saved_api_key = api_key

    def delete_api_key(self) -> None:
        if self.delete_api_key_error is not None:
            raise self.delete_api_key_error
        self.deleted_api_key = True


class LLMConfigServiceTests(unittest.TestCase):
    def test_refresh_loads_sqlite_config_and_keychain_api_key(self) -> None:
        env = FakeLLMConfigEnvironment()
        env.loaded_persisted = {"model": "mock-vlm", "api_key": "must-not-load"}
        env.loaded_api_key = "keychain-key"

        refresh_persisted_llm_config_action("scores.sqlite", env.dependencies())

        self.assertEqual(env.persisted, {"model": "mock-vlm"})
        self.assertEqual(env.secure, {"api_key": "keychain-key"})

    def test_refresh_clears_layers_when_sqlite_or_keychain_load_fails(self) -> None:
        env = FakeLLMConfigEnvironment()
        env.persisted = {"model": "old"}
        env.secure = {"api_key": "old-key"}
        env.load_persisted_error = RuntimeError("broken sqlite")
        env.load_api_key_error = SecretStoreUnavailable("missing")

        refresh_persisted_llm_config_action("scores.sqlite", env.dependencies())

        self.assertEqual(env.persisted, {})
        self.assertEqual(env.secure, {})

    def test_apply_persists_api_key_to_keychain_not_sqlite(self) -> None:
        env = FakeLLMConfigEnvironment()

        apply_llm_config_action(
            {
                "apiKey": "unit-key",
                "baseUrl": "https://example.test/v1",
                "model": "mock-vlm",
                "promptPreset": "technical",
                "persist": True,
            },
            "scores.sqlite",
            env.dependencies(),
        )

        self.assertEqual(env.saved_api_key, "unit-key")
        self.assertEqual(env.secure, {"api_key": "unit-key"})
        self.assertEqual(env.session["api_key"], "unit-key")
        self.assertEqual(env.persisted["model"], "mock-vlm")
        self.assertEqual(env.persisted["prompt_preset"], "technical")
        self.assertIn("api_key", env.saved_persisted_config)
        self.assertNotIn("api_key", env.persisted)

    def test_apply_falls_back_to_session_when_keychain_is_unavailable(self) -> None:
        env = FakeLLMConfigEnvironment()
        env.save_api_key_error = SecretStoreUnavailable("missing")

        apply_llm_config_action(
            {"apiKey": "session-key", "promptPreset": "balanced", "persist": True},
            "scores.sqlite",
            env.dependencies(),
        )

        self.assertEqual(env.session["api_key"], "session-key")
        self.assertEqual(env.secure, {})
        self.assertNotIn("api_key", env.persisted)
        self.assertEqual(env.cleared_secure_keys, [("api_key",)])

    def test_apply_clear_key_deletes_secret_and_clears_runtime_layers(self) -> None:
        env = FakeLLMConfigEnvironment()
        env.session = {"api_key": "session-key"}
        env.secure = {"api_key": "keychain-key"}

        apply_llm_config_action(
            {"clearKey": True, "promptPreset": "balanced", "persist": True},
            "scores.sqlite",
            env.dependencies(),
        )

        self.assertTrue(env.deleted_api_key)
        self.assertNotIn("api_key", env.session)
        self.assertNotIn("api_key", env.secure)
        self.assertEqual(env.cleared_session_keys, [("api_key",)])
        self.assertEqual(env.cleared_secure_keys, [("api_key",)])

    def test_apply_reports_keychain_save_and_delete_errors(self) -> None:
        env = FakeLLMConfigEnvironment()
        env.save_api_key_error = SecretStoreError("save denied")
        with self.assertRaisesRegex(ValueError, "系统钥匙串保存失败"):
            apply_llm_config_action(
                {"apiKey": "unit-key", "promptPreset": "balanced", "persist": True},
                "scores.sqlite",
                env.dependencies(),
            )

        env = FakeLLMConfigEnvironment()
        env.delete_api_key_error = SecretStoreError("delete denied")
        with self.assertRaisesRegex(ValueError, "系统钥匙串清除失败"):
            apply_llm_config_action(
                {"clearKey": True, "promptPreset": "balanced", "persist": True},
                "scores.sqlite",
                env.dependencies(),
            )


if __name__ == "__main__":
    unittest.main()
