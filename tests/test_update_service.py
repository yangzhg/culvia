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
        "assets": [],
    }


def release_asset(name: str, version: str = "0.2.0") -> dict[str, object]:
    return {
        "name": name,
        "state": "uploaded",
        "size": 1024,
        "browser_download_url": f"https://github.com/yangzhg/culvia/releases/download/v{version}/{name}",
    }


class UpdateServiceTests(unittest.TestCase):
    def test_desktop_target_is_reported_separately_from_the_python_process(self) -> None:
        desktop = application_info(
            environ={
                DESKTOP_APP_ENV: "1",
                DESKTOP_SHELL_VERSION_ENV: "0.1.0",
                DESKTOP_RUNTIME_PROFILE_ENV: "lite",
                "CULVIA_DESKTOP_BUILD_TARGET": "aarch64-apple-darwin",
            },
            service_version="0.1.0",
            platform_name="darwin",
            architecture="x86_64",
        )
        self.assertEqual(desktop["architecture"], "x86_64")
        self.assertEqual(desktop.get("desktopTarget"), "aarch64-apple-darwin")
        self.assertEqual(desktop.get("desktopPlatform"), "darwin")
        self.assertEqual(desktop.get("desktopArchitecture"), "arm64")
        web = application_info(environ={"CULVIA_DESKTOP_BUILD_TARGET": "aarch64-apple-darwin"})
        self.assertEqual(web.get("desktopTarget"), "")

    def test_release_packages_match_the_exact_desktop_target_and_runtime(self) -> None:
        for target, platform_slug, suffix in (
            ("aarch64-apple-darwin", "darwin", "aarch64"),
            ("x86_64-apple-darwin", "darwin", "x64"),
            ("x86_64-pc-windows-msvc", "windows", "zip"),
            ("aarch64-pc-windows-msvc", "windows", "zip"),
            ("x86_64-unknown-linux-gnu", "linux", "tar.gz"),
            ("aarch64-unknown-linux-gnu", "linux", "tar.gz"),
        ):
            for profile in ("full", "lite"):
                with self.subTest(target=target, profile=profile):
                    marker = "-lite" if profile == "lite" else ""
                    package_name = (
                        f"Culvia_0.2.0_{suffix}{marker}.dmg"
                        if platform_slug == "darwin"
                        else f"culvia-0.2.0-{platform_slug}{marker}-{target}.{suffix}"
                    )
                    release = release_payload()
                    release["assets"] = [release_asset(package_name), release_asset("culvia-0.2.0-py3-none-any.whl")]
                    result = UpdateChecker().check(
                        app_info={
                            "version": "0.1.0",
                            "distribution": "desktop",
                            "runtimeProfile": profile,
                            "desktopTarget": target,
                        },
                        get=lambda *_args, **_kwargs: FakeResponse(payload=release),
                    )
                    self.assertTrue(result["updateAvailable"])
                    self.assertEqual(result.get("package", {}).get("status"), "available")
                    self.assertEqual(result["package"]["name"], package_name)

    def test_new_version_without_a_matching_package_is_not_a_download_offer(self) -> None:
        release = release_payload()
        release["assets"] = [
            release_asset("Culvia_0.2.0_x64.dmg"),
            release_asset("culvia-0.2.0-linux-lite-x86_64-unknown-linux-gnu.tar.gz"),
            release_asset("culvia-0.2.0-py3-none-any.whl"),
        ]
        for target, profile in (("aarch64-apple-darwin", "full"), ("x86_64-unknown-linux-gnu", "full")):
            with self.subTest(target=target):
                result = UpdateChecker().check(
                    app_info={
                        "version": "0.1.0",
                        "distribution": "desktop",
                        "runtimeProfile": profile,
                        "desktopTarget": target,
                    },
                    get=lambda *_args, **_kwargs: FakeResponse(payload=release),
                )
                self.assertEqual(result["status"], "updateAvailable")
                self.assertEqual(result.get("package", {}).get("status"), "unavailable")
                self.assertEqual(result["package"]["reason"], "packageMissing")

    def test_lite_requires_the_same_release_runtime_wheel(self) -> None:
        release = release_payload()
        release["assets"] = [
            release_asset("Culvia_0.2.0_aarch64-lite.dmg"),
            release_asset("culvia-0.1.0-py3-none-any.whl"),
        ]
        result = UpdateChecker().check(
            app_info={
                "version": "0.1.0",
                "distribution": "desktop",
                "runtimeProfile": "lite",
                "desktopTarget": "aarch64-apple-darwin",
            },
            get=lambda *_args, **_kwargs: FakeResponse(payload=release),
        )
        self.assertEqual(result.get("package", {}).get("status"), "unavailable")
        self.assertEqual(result["package"]["reason"], "runtimeWheelMissing")

    def test_unknown_desktop_identity_does_not_infer_a_package_from_python(self) -> None:
        release = release_payload()
        release["assets"] = [release_asset("Culvia_0.2.0_x64.dmg")]
        base = {
            "version": "0.1.0",
            "distribution": "desktop",
            "runtimeProfile": "full",
            "platform": "darwin",
            "architecture": "x86_64",
        }
        for extra, reason in (
            ({}, "targetUnknown"),
            ({"desktopTarget": "x86_64-unknown-linux-musl"}, "targetUnknown"),
            ({"desktopTarget": "x86_64-apple-darwin", "runtimeProfile": "auto"}, "profileUnknown"),
        ):
            with self.subTest(extra=extra):
                result = UpdateChecker().check(
                    app_info={**base, **extra},
                    get=lambda *_args, **_kwargs: FakeResponse(payload=release),
                )
                self.assertEqual(result["package"]["status"], "unknown")
                self.assertEqual(result["package"]["reason"], reason)

    def test_package_matching_is_recomputed_for_each_installation_even_from_cached_release(self) -> None:
        calls = []
        release = release_payload()
        wheel = "culvia-0.2.0-py3-none-any.whl"
        release["assets"] = [release_asset(wheel), release_asset("Culvia_0.2.0_aarch64-lite.dmg")]

        def get(*_args: object, **_kwargs: object) -> FakeResponse:
            calls.append(1)
            return FakeResponse(payload=release)

        checker = UpdateChecker()
        base = {"version": "0.1.0", "distribution": "desktop", "desktopTarget": "aarch64-apple-darwin"}
        lite = checker.check(app_info={**base, "runtimeProfile": "lite"}, get=get)
        full = checker.check(app_info={**base, "runtimeProfile": "full"}, get=get)
        python = checker.check(app_info={"version": "0.1.0", "distribution": "python"}, get=get)
        self.assertEqual(len(calls), 1)
        self.assertTrue(full["cached"])
        self.assertTrue(python["cached"])
        self.assertEqual(lite["package"]["status"], "available")
        self.assertEqual(full["package"]["status"], "unavailable")
        self.assertEqual(python["package"]["status"], "available")
        self.assertEqual(python["package"]["name"], wheel)

    def test_incomplete_or_untrusted_assets_do_not_count_as_available_packages(self) -> None:
        wheel = "culvia-0.2.0-py3-none-any.whl"
        for change in (
            {"size": 0},
            {"size": True},
            {"state": "starter"},
            {"browser_download_url": f"https://example.com/{wheel}"},
            {"browser_download_url": f"https://github.com/another/repo/releases/download/v0.2.0/{wheel}"},
            {"browser_download_url": f"https://github.com/yangzhg/culvia/releases/download/v0.1.0/{wheel}"},
            {"browser_download_url": f"https://user:secret@github.com/yangzhg/culvia/releases/download/v0.2.0/{wheel}"},
            {"browser_download_url": "https://[invalid"},
        ):
            with self.subTest(change=change):
                release = release_payload()
                release["assets"] = [{**release_asset(wheel), **change}]
                result = UpdateChecker().check(
                    app_info={"version": "0.1.0", "distribution": "python"},
                    get=lambda *_args, **_kwargs: FakeResponse(payload=release),
                )
                self.assertEqual(result["package"]["status"], "unavailable")
                self.assertNotIn("secret", str(result))

    def test_missing_asset_metadata_is_unknown_but_an_empty_asset_list_is_unavailable(self) -> None:
        release = release_payload()
        del release["assets"]
        missing = UpdateChecker().check(
            app_info={"version": "0.1.0", "distribution": "python"},
            get=lambda *_args, **_kwargs: FakeResponse(payload=release),
        )
        self.assertEqual(missing["package"]["status"], "unknown")
        self.assertEqual(missing["package"]["reason"], "releaseAssetsUnknown")
        release["assets"] = []
        empty = UpdateChecker().check(
            app_info={"version": "0.1.0", "distribution": "python"},
            get=lambda *_args, **_kwargs: FakeResponse(payload=release),
        )
        self.assertEqual(empty["package"]["status"], "unavailable")
        release["assets"] = {"name": "not-an-asset-list"}
        with self.assertRaises(UpdateCheckError) as raised:
            parse_latest_release(release)
        self.assertEqual(raised.exception.code, "updateCheckInvalidResponse")

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
        malformed = {**release_payload(), "html_url": "https://[invalid"}

        for payload in (prerelease, evil, malformed):
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
