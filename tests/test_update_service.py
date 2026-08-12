from __future__ import annotations

import unittest
from datetime import UTC, datetime

import requests

from culvia import __version__
from culvia.capabilities import DESKTOP_APP_ENV
from culvia.update_service import (
    DESKTOP_RUNTIME_PROFILE_ENV,
    DESKTOP_SHELL_VERSION_ENV,
    GITHUB_LATEST_RELEASE_API,
    UpdateCheckError,
    UpdateChecker,
    application_info,
    compare_versions,
    fetch_latest_release,
    normalized_version,
    parse_latest_release,
)


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        payload: object | None = None,
        *,
        headers: dict[str, str] | None = None,
        json_error: ValueError | None = None,
    ) -> None:
        self.status_code = status_code
        self.payload = payload
        self.headers = headers or {}
        self.reason = "fake response"
        self.json_error = json_error

    def json(self) -> object:
        if self.json_error is not None:
            raise self.json_error
        return self.payload


def release_payload(version: str = "0.2.0") -> dict[str, object]:
    tag = f"v{version}"
    return {
        "tag_name": tag,
        "name": f"Culvia {tag}",
        "draft": False,
        "prerelease": False,
        "published_at": "2026-08-12T10:00:00Z",
        "html_url": f"https://github.com/yangzhg/culvia/releases/tag/{tag}",
    }


class UpdateServiceTests(unittest.TestCase):
    def test_versions_are_normalized_and_compared_without_build_metadata(self) -> None:
        self.assertEqual(normalized_version("v1.2.3+desktop.4"), "1.2.3")
        self.assertEqual(normalized_version("1.2.3-rc.1"), "1.2.3-rc.1")
        self.assertEqual(compare_versions("1.2.3", "1.2.4"), -1)
        self.assertEqual(compare_versions("1.2.3", "v1.2.3"), 0)
        self.assertEqual(compare_versions("1.2.3-rc.1", "1.2.3"), -1)
        self.assertIsNone(normalized_version("latest"))

    def test_application_info_distinguishes_python_and_desktop_versions(self) -> None:
        web = application_info(
            environ={},
            service_version="0.1.0",
            platform_name="linux",
            architecture="x86_64",
        )
        desktop = application_info(
            environ={
                DESKTOP_APP_ENV: "1",
                DESKTOP_SHELL_VERSION_ENV: "0.2.0",
                DESKTOP_RUNTIME_PROFILE_ENV: "lite",
            },
            service_version="0.1.0",
            platform_name="darwin",
            architecture="arm64",
        )

        self.assertEqual(web["distribution"], "python")
        self.assertEqual(web["runtimeProfile"], "web")
        self.assertEqual(web["version"], "0.1.0")
        self.assertFalse(web["versionMismatch"])
        self.assertEqual(desktop["distribution"], "desktop")
        self.assertEqual(desktop["runtimeProfile"], "lite")
        self.assertEqual(desktop["version"], "0.2.0")
        self.assertEqual(desktop["serviceVersion"], "0.1.0")
        self.assertTrue(desktop["versionMismatch"])

    def test_service_version_uses_the_running_package_code(self) -> None:
        info = application_info(environ={})

        self.assertEqual(info["serviceVersion"], __version__)

    def test_latest_release_request_uses_fixed_repository_and_versioned_headers(self) -> None:
        calls: list[dict[str, object]] = []

        def get(url: str, **kwargs: object) -> FakeResponse:
            calls.append({"url": url, **kwargs})
            return FakeResponse(payload=release_payload())

        release = fetch_latest_release(service_version="0.1.0", get=get)

        self.assertEqual(release["version"], "0.2.0")
        self.assertEqual(calls[0]["url"], GITHUB_LATEST_RELEASE_API)
        headers = calls[0]["headers"]
        self.assertIsInstance(headers, dict)
        self.assertEqual(headers["User-Agent"], "Culvia/0.1.0")
        self.assertEqual(headers["Accept"], "application/vnd.github+json")

    def test_release_response_rejects_prereleases_and_untrusted_urls(self) -> None:
        prerelease = release_payload("0.2.0-rc.1")
        prerelease["prerelease"] = True
        evil = release_payload()
        evil["html_url"] = "https://example.com/yangzhg/culvia/releases/tag/v0.2.0"

        for payload in (prerelease, evil):
            with self.subTest(payload=payload), self.assertRaises(UpdateCheckError) as raised:
                parse_latest_release(payload)
            self.assertEqual(raised.exception.code, "updateCheckInvalidResponse")

    def test_request_failures_and_rate_limits_use_safe_machine_codes(self) -> None:
        def timeout(*_args: object, **_kwargs: object) -> FakeResponse:
            raise requests.Timeout("https://user:secret@example.test")

        with self.assertRaises(UpdateCheckError) as request_error:
            fetch_latest_release(service_version="0.1.0", get=timeout)
        self.assertEqual(request_error.exception.code, "updateCheckRequestFailed")
        self.assertNotIn("secret", str(request_error.exception))

        with self.assertRaises(UpdateCheckError) as rate_error:
            fetch_latest_release(
                service_version="0.1.0",
                get=lambda *_args, **_kwargs: FakeResponse(
                    403,
                    {},
                    headers={"X-RateLimit-Remaining": "0"},
                ),
            )
        self.assertEqual(rate_error.exception.code, "updateCheckRateLimited")
        self.assertEqual(rate_error.exception.status_code, 503)
        self.assertTrue(rate_error.exception.retryable)

    def test_checker_reports_update_current_and_ahead_and_reuses_release_cache(self) -> None:
        now_value = [0.0]
        requests_made = [0]

        def get(*_args: object, **_kwargs: object) -> FakeResponse:
            requests_made[0] += 1
            return FakeResponse(payload=release_payload())

        checker = UpdateChecker(
            cache_seconds=60,
            clock=lambda: now_value[0],
            now=lambda: datetime(2026, 8, 12, 10, 5, tzinfo=UTC),
        )
        base_info = application_info(environ={}, service_version="0.1.0")

        available = checker.check(app_info=base_info, get=get)
        current = checker.check(app_info={**base_info, "version": "0.2.0"}, get=get)
        ahead = checker.check(app_info={**base_info, "version": "0.3.0"}, get=get)

        self.assertEqual(available["status"], "updateAvailable")
        self.assertTrue(available["updateAvailable"])
        self.assertEqual(current["status"], "current")
        self.assertEqual(ahead["status"], "ahead")
        self.assertEqual(requests_made[0], 1)
        self.assertFalse(available["cached"])
        self.assertTrue(current["cached"])
        self.assertEqual(available["checkedAt"], "2026-08-12T10:05:00Z")


if __name__ == "__main__":
    unittest.main()
