from __future__ import annotations

import unittest

from culvia.api_errors import api_error_payload


class ApiErrorTests(unittest.TestCase):
    def test_api_error_payload_includes_message_code_params_and_flags(self) -> None:
        payload = api_error_payload(
            "exportDestinationRequired", "请选择导出目录。", {"path": "/tmp/out"}, retryable=False
        )

        self.assertEqual(payload["error"], "请选择导出目录。")
        self.assertEqual(payload["errorCode"], "exportDestinationRequired")
        self.assertEqual(payload["errorParams"], {"path": "/tmp/out"})
        self.assertFalse(payload["retryable"])


if __name__ == "__main__":
    unittest.main()
