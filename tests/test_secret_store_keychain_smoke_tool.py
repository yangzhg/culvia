from __future__ import annotations

import json
import io
import unittest
from unittest.mock import patch

from tools import check_secret_store_keychain_smoke


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.set_calls: list[str] = []
        self.delete_calls = 0

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.set_calls.append(password)
        self.values[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.delete_calls += 1
        self.values.pop((service, username), None)


class IncompleteKeyring:
    def get_password(self, _service: str, _username: str) -> None:
        return None


class ConcurrentModificationKeyring(FakeKeyring):
    def __init__(self) -> None:
        super().__init__()
        self.mutated = False

    def get_password(self, service: str, username: str) -> str | None:
        value = super().get_password(service, username)
        if value == "unit-sentinel" and not self.mutated:
            self.mutated = True
            self.values[(service, username)] = "external-secret"
            return "external-secret"
        return value


class SecretStoreKeychainSmokeToolTests(unittest.TestCase):
    def test_requires_explicit_write_consent(self) -> None:
        keyring = FakeKeyring()

        checks, metadata = check_secret_store_keychain_smoke.collect_checks(
            allow_write=False,
            keyring_module=keyring,
            sentinel="unit-sentinel",
        )

        payload = check_secret_store_keychain_smoke.result_payload(checks, **metadata)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["failed"], ["keychain smoke requires explicit write consent"])
        self.assertEqual(keyring.values, {})

    def test_existing_secret_requires_preserve_existing_mode(self) -> None:
        keyring = FakeKeyring()
        slot = ("culvia", "llm-review-api-key")
        keyring.values[slot] = "original-secret"

        checks, metadata = check_secret_store_keychain_smoke.collect_checks(
            allow_write=True,
            preserve_existing=False,
            keyring_module=keyring,
            sentinel="unit-sentinel",
        )

        payload = check_secret_store_keychain_smoke.result_payload(checks, **metadata)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["failed"], ["existing LLM API key requires preserve-existing mode"])
        self.assertEqual(keyring.values[slot], "original-secret")
        self.assertEqual(keyring.set_calls, [])

    def test_roundtrip_restores_existing_secret_when_preserve_existing_is_set(self) -> None:
        keyring = FakeKeyring()
        slot = ("culvia", "llm-review-api-key")
        keyring.values[slot] = "original-secret"

        checks, metadata = check_secret_store_keychain_smoke.collect_checks(
            allow_write=True,
            preserve_existing=True,
            keyring_module=keyring,
            sentinel="unit-sentinel",
        )

        payload = check_secret_store_keychain_smoke.result_payload(checks, **metadata)
        self.assertTrue(payload["ok"], payload["failed"])
        self.assertEqual(keyring.values[slot], "original-secret")
        self.assertIn("unit-sentinel", keyring.set_calls)
        self.assertEqual(keyring.set_calls[-1], "original-secret")
        self.assertTrue(payload["restored"])
        self.assertEqual(payload["originalLabel"], "orig****cret")

    def test_roundtrip_removes_sentinel_when_no_existing_secret(self) -> None:
        keyring = FakeKeyring()

        checks, metadata = check_secret_store_keychain_smoke.collect_checks(
            allow_write=True,
            keyring_module=keyring,
            sentinel="unit-sentinel",
        )

        payload = check_secret_store_keychain_smoke.result_payload(checks, **metadata)
        self.assertTrue(payload["ok"], payload["failed"])
        self.assertEqual(keyring.values, {})
        self.assertEqual(keyring.delete_calls, 1)
        self.assertTrue(payload["restored"])

    def test_concurrent_modification_is_not_overwritten(self) -> None:
        keyring = ConcurrentModificationKeyring()
        slot = ("culvia", "llm-review-api-key")

        checks, metadata = check_secret_store_keychain_smoke.collect_checks(
            allow_write=True,
            preserve_existing=True,
            keyring_module=keyring,
            sentinel="unit-sentinel",
        )

        payload = check_secret_store_keychain_smoke.result_payload(checks, **metadata)
        self.assertFalse(payload["ok"])
        self.assertIn("keychain slot still belongs to sentinel before cleanup", payload["failed"])
        self.assertIn("original keychain state restored", payload["failed"])
        self.assertEqual(keyring.values[slot], "external-secret")

    def test_unavailable_backend_reports_failure_without_write(self) -> None:
        keyring = IncompleteKeyring()

        checks, metadata = check_secret_store_keychain_smoke.collect_checks(
            allow_write=True,
            keyring_module=keyring,
            sentinel="unit-sentinel",
        )

        payload = check_secret_store_keychain_smoke.result_payload(checks, **metadata)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["failed"], ["system keychain backend is unavailable"])
        self.assertIn("install the desktop extra", payload["checks"][0]["detail"])

    def test_json_payload_does_not_include_full_sentinel_or_original_secret(self) -> None:
        keyring = FakeKeyring()
        keyring.values[("culvia", "llm-review-api-key")] = "original-secret"

        checks, metadata = check_secret_store_keychain_smoke.collect_checks(
            allow_write=True,
            preserve_existing=True,
            keyring_module=keyring,
            sentinel="unit-sentinel",
        )

        payload = check_secret_store_keychain_smoke.result_payload(checks, **metadata)
        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("unit-sentinel", encoded)
        self.assertNotIn("original-secret", encoded)
        self.assertIn("unit****inel", encoded)
        self.assertIn("orig****cret", encoded)

    def test_cli_main_exit_codes(self) -> None:
        stdout = io.StringIO()
        with patch("tools.check_secret_store_keychain_smoke.collect_checks") as collect, patch("sys.stdout", stdout):
            collect.return_value = (
                [check_secret_store_keychain_smoke.check("ok", True, "done")],
                {"backend": "FakeKeyring", "restored": True, "original_label": ""},
            )
            self.assertEqual(check_secret_store_keychain_smoke.main(["--allow-write", "--json"]), 0)

        stdout = io.StringIO()
        with patch("tools.check_secret_store_keychain_smoke.collect_checks") as collect, patch("sys.stdout", stdout):
            collect.return_value = (
                [check_secret_store_keychain_smoke.check("failed", False, "no consent")],
                {"backend": "FakeKeyring", "restored": False, "original_label": ""},
            )
            self.assertEqual(check_secret_store_keychain_smoke.main(["--json"]), 1)


if __name__ == "__main__":
    unittest.main()
