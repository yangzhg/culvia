from __future__ import annotations

import os
import unittest

from culvia import secret_store


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


class FailingKeyring(FakeKeyring):
    def set_password(self, service: str, username: str, password: str) -> None:
        raise RuntimeError("locked")


class SecretStoreTests(unittest.TestCase):
    def test_keyring_backend_roundtrip_uses_fixed_service_and_username(self) -> None:
        keyring = FakeKeyring()

        secret_store.save_llm_api_key(" unit-key ", keyring_module=keyring)

        self.assertEqual(
            keyring.values[(secret_store.SERVICE_NAME, secret_store.LLM_API_KEY_USERNAME)],
            "unit-key",
        )
        self.assertEqual(secret_store.load_llm_api_key(keyring_module=keyring), "unit-key")

        secret_store.delete_llm_api_key(keyring_module=keyring)

        self.assertEqual(secret_store.load_llm_api_key(keyring_module=keyring), "")

    def test_blank_key_deletes_existing_secret(self) -> None:
        keyring = FakeKeyring()
        secret_store.save_llm_api_key("unit-key", keyring_module=keyring)

        secret_store.save_llm_api_key("", keyring_module=keyring)

        self.assertEqual(keyring.values, {})

    def test_backend_errors_are_wrapped(self) -> None:
        with self.assertRaises(secret_store.SecretStoreError) as ctx:
            secret_store.save_llm_api_key("unit-key", keyring_module=FailingKeyring())

        self.assertIn("locked", str(ctx.exception))

    def test_disable_env_makes_keyring_unavailable(self) -> None:
        original = os.environ.get(secret_store.DISABLE_KEYCHAIN_ENV)
        try:
            os.environ[secret_store.DISABLE_KEYCHAIN_ENV] = "1"
            self.assertFalse(secret_store.keyring_available(FakeKeyring()))
            with self.assertRaises(secret_store.SecretStoreUnavailable):
                secret_store.load_llm_api_key(keyring_module=FakeKeyring())
        finally:
            if original is None:
                os.environ.pop(secret_store.DISABLE_KEYCHAIN_ENV, None)
            else:
                os.environ[secret_store.DISABLE_KEYCHAIN_ENV] = original


if __name__ == "__main__":
    unittest.main()
