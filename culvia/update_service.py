from __future__ import annotations

import os
import platform
import re
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import unquote, urlparse

import requests

from culvia import __version__
from culvia.capabilities import DESKTOP_APP_ENV
from culvia.config_payloads import normalize_network_mode


APP_NAME = "Culvia"
GITHUB_REPOSITORY = "yangzhg/culvia"
GITHUB_LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
DESKTOP_SHELL_VERSION_ENV = "CULVIA_DESKTOP_SHELL_VERSION"
DESKTOP_RUNTIME_PROFILE_ENV = "CULVIA_DESKTOP_RUNTIME_PROFILE"
DESKTOP_BUILD_TARGET_ENV = "CULVIA_DESKTOP_BUILD_TARGET"
DEFAULT_UPDATE_CACHE_SECONDS = 15 * 60
DEFAULT_UPDATE_TIMEOUT_SECONDS = 5.0


class ResponseLike(Protocol):
    status_code: int
    reason: str
    headers: Mapping[str, str]

    def json(self) -> Any: ...


HttpGet = Callable[..., ResponseLike]


class UpdateCheckError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 502, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.retryable = retryable


@dataclass(frozen=True)
class ParsedVersion:
    release: tuple[int, int, int]
    prerelease: tuple[tuple[int, int | str], ...]


_VERSION_PATTERN = re.compile(
    r"^[vV]?(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$"
)


def _prerelease_parts(value: str | None) -> tuple[tuple[int, int | str], ...]:
    if not value:
        return ()
    parts: list[tuple[int, int | str]] = []
    for part in value.split("."):
        parts.append((0, int(part)) if part.isdigit() else (1, part.casefold()))
    return tuple(parts)


def parse_version(value: object) -> ParsedVersion | None:
    match = _VERSION_PATTERN.fullmatch(str(value or "").strip())
    if not match:
        return None
    return ParsedVersion(
        release=(int(match["major"]), int(match["minor"]), int(match["patch"])),
        prerelease=_prerelease_parts(match["prerelease"]),
    )


def normalized_version(value: object) -> str | None:
    parsed = parse_version(value)
    if parsed is None:
        return None
    version = ".".join(str(part) for part in parsed.release)
    raw = str(value or "").strip().removeprefix("v").removeprefix("V")
    prerelease = raw.split("+", 1)[0].split("-", 1)
    return f"{version}-{prerelease[1]}" if len(prerelease) == 2 else version


def compare_versions(left: object, right: object) -> int:
    left_version = parse_version(left)
    right_version = parse_version(right)
    if left_version is None or right_version is None:
        raise ValueError("versions must use semantic X.Y.Z form")
    if left_version.release != right_version.release:
        return 1 if left_version.release > right_version.release else -1
    if not left_version.prerelease and not right_version.prerelease:
        return 0
    if not left_version.prerelease:
        return 1
    if not right_version.prerelease:
        return -1
    if left_version.prerelease == right_version.prerelease:
        return 0
    return 1 if left_version.prerelease > right_version.prerelease else -1


def installed_service_version() -> str:
    # The imported package is the code serving this process. Distribution
    # metadata can be stale in editable/source installs after a version bump.
    return str(__version__).strip()


def _desktop_target_info(value: object) -> tuple[str, str]:
    match = re.fullmatch(r"(aarch64|x86_64)-(apple-darwin|pc-windows-msvc|unknown-linux-gnu)", str(value or ""))
    if match is None:
        return "", ""
    platform_name = {"apple-darwin": "darwin", "pc-windows-msvc": "win32", "unknown-linux-gnu": "linux"}[match[2]]
    return platform_name, "arm64" if match[1] == "aarch64" else "x86_64"


def application_info(
    *,
    environ: Mapping[str, str] | None = None,
    service_version: str | None = None,
    platform_name: str | None = None,
    architecture: str | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    backend_version = str(service_version or installed_service_version()).strip() or __version__
    desktop_app = env.get(DESKTOP_APP_ENV) == "1"
    shell_version = str(env.get(DESKTOP_SHELL_VERSION_ENV) or "").strip() if desktop_app else ""
    current_version = shell_version or backend_version
    runtime_profile = str(env.get(DESKTOP_RUNTIME_PROFILE_ENV) or "").strip() if desktop_app else "web"
    desktop_target = str(env.get(DESKTOP_BUILD_TARGET_ENV) or "").strip() if desktop_app else ""
    desktop_platform, desktop_architecture = _desktop_target_info(desktop_target)
    return {
        "version": current_version,
        "serviceVersion": backend_version,
        "shellVersion": shell_version,
        "distribution": "desktop" if desktop_app else "python",
        "runtimeProfile": runtime_profile or "desktop",
        "platform": platform_name or sys.platform,
        "architecture": architecture or platform.machine() or "unknown",
        "desktopTarget": desktop_target,
        "desktopPlatform": desktop_platform,
        "desktopArchitecture": desktop_architecture,
        "versionMismatch": bool(desktop_app and shell_version and shell_version != backend_version),
    }


def _validated_release_url(value: object, tag: str) -> str:
    url = str(value or "").strip()
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise UpdateCheckError(
            "updateCheckInvalidResponse",
            "The release response contained an unexpected URL.",
        ) from exc
    expected_path = f"/{GITHUB_REPOSITORY}/releases/tag/{tag}"
    if (
        parsed.scheme != "https"
        or parsed.netloc != "github.com"
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != expected_path
    ):
        raise UpdateCheckError(
            "updateCheckInvalidResponse",
            "The release response contained an unexpected URL.",
        )
    return url


def _release_asset_names(payload: Mapping[str, Any], tag: str) -> tuple[str, ...] | None:
    if "assets" not in payload:
        return None
    assets = payload["assets"]
    if not isinstance(assets, list):
        raise UpdateCheckError("updateCheckInvalidResponse", "The release response contained an invalid asset list.")
    names: set[str] = set()
    for asset in assets:
        if not isinstance(asset, Mapping):
            continue
        name = asset.get("name")
        size = asset.get("size")
        if (
            not isinstance(name, str)
            or not name
            or "/" in name
            or "\\" in name
            or asset.get("state") != "uploaded"
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
        ):
            continue
        try:
            parsed = urlparse(str(asset.get("browser_download_url") or ""))
        except ValueError:
            continue
        if (
            parsed.scheme == "https"
            and parsed.netloc == "github.com"
            and not parsed.query
            and not parsed.fragment
            and unquote(parsed.path) == f"/{GITHUB_REPOSITORY}/releases/download/{tag}/{name}"
        ):
            names.add(name)
    return tuple(sorted(names))


def parse_latest_release(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or payload.get("draft") is True or payload.get("prerelease") is True:
        raise UpdateCheckError("updateCheckInvalidResponse", "GitHub did not return a stable release.")
    tag = str(payload.get("tag_name") or "").strip()
    version = normalized_version(tag)
    parsed_version = parse_version(version)
    if parsed_version is None or parsed_version.prerelease:
        raise UpdateCheckError("updateCheckInvalidResponse", "The release tag is not a stable semantic version.")
    return {
        "version": version,
        "tag": tag,
        "name": str(payload.get("name") or tag).strip() or tag,
        "publishedAt": str(payload.get("published_at") or "").strip(),
        "releaseUrl": _validated_release_url(payload.get("html_url"), tag),
        "assetNames": _release_asset_names(payload, tag),
    }


def _expected_package_name(version: str, app_info: Mapping[str, Any]) -> tuple[str, str]:
    distribution = app_info.get("distribution")
    if distribution == "python":
        return f"culvia-{version}-py3-none-any.whl", ""
    if distribution != "desktop":
        return "", "distributionUnknown"
    target = str(app_info.get("desktopTarget") or "")
    target_platform, target_architecture = _desktop_target_info(target)
    if not target_platform:
        return "", "targetUnknown"
    profile = app_info.get("runtimeProfile")
    if profile not in {"full", "lite"}:
        return "", "profileUnknown"
    marker = "-lite" if profile == "lite" else ""
    if target_platform == "darwin":
        suffix = "aarch64" if target_architecture == "arm64" else "x64"
        return f"Culvia_{version}_{suffix}{marker}.dmg", ""
    platform_slug, extension = ("windows", "zip") if target_platform == "win32" else ("linux", "tar.gz")
    return f"culvia-{version}-{platform_slug}{marker}-{target}.{extension}", ""


def _release_package(release: Mapping[str, Any], app_info: Mapping[str, Any]) -> dict[str, str]:
    name, reason = _expected_package_name(release["version"], app_info)
    if reason:
        return {"status": "unknown", "reason": reason, "name": name}
    asset_names = release["assetNames"]
    if asset_names is None:
        return {"status": "unknown", "reason": "releaseAssetsUnknown", "name": name}
    if name not in asset_names:
        return {"status": "unavailable", "reason": "packageMissing", "name": name}
    if app_info.get("distribution") == "desktop" and app_info.get("runtimeProfile") == "lite":
        if f"culvia-{release['version']}-py3-none-any.whl" not in asset_names:
            return {"status": "unavailable", "reason": "runtimeWheelMissing", "name": name}
    return {"status": "available", "reason": "", "name": name}


def _github_get(url: str, *, headers: Mapping[str, str], timeout: float, network_mode: str) -> ResponseLike:
    with requests.Session() as session:
        session.trust_env = normalize_network_mode(network_mode) == "system"
        return session.get(url, headers=dict(headers), timeout=timeout)


def fetch_latest_release(
    *,
    service_version: str,
    network_mode: str = "direct",
    timeout: float = DEFAULT_UPDATE_TIMEOUT_SECONDS,
    get: HttpGet | None = None,
) -> dict[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"{APP_NAME}/{service_version}",
    }
    try:
        response = (
            get(GITHUB_LATEST_RELEASE_API, headers=headers, timeout=timeout)
            if get is not None
            else _github_get(
                GITHUB_LATEST_RELEASE_API,
                headers=headers,
                timeout=timeout,
                network_mode=network_mode,
            )
        )
    except requests.RequestException as exc:
        raise UpdateCheckError(
            "updateCheckRequestFailed",
            "The GitHub release request failed.",
            retryable=True,
        ) from exc

    if response.status_code == 403 and str(response.headers.get("X-RateLimit-Remaining", "")) == "0":
        raise UpdateCheckError(
            "updateCheckRateLimited",
            "GitHub rate-limited the update check.",
            status_code=503,
            retryable=True,
        )
    if response.status_code == 404:
        raise UpdateCheckError("updateCheckNoRelease", "No stable GitHub release was found.")
    if response.status_code >= 400:
        raise UpdateCheckError(
            "updateCheckUpstreamFailed",
            f"GitHub returned HTTP {response.status_code}.",
            retryable=response.status_code >= 500,
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise UpdateCheckError("updateCheckInvalidResponse", "GitHub returned invalid JSON.") from exc
    return parse_latest_release(payload)


class UpdateChecker:
    def __init__(
        self,
        *,
        cache_seconds: float = DEFAULT_UPDATE_CACHE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.cache_seconds = max(0.0, cache_seconds)
        self.clock = clock
        self.now = now
        self._lock = threading.Lock()
        self._cached_release: dict[str, Any] | None = None
        self._cached_at = 0.0
        self._checked_at = ""

    def _latest_release(
        self,
        *,
        service_version: str,
        network_mode: str,
        get: HttpGet | None,
    ) -> tuple[dict[str, Any], bool, str]:
        with self._lock:
            if self._cached_release is not None and self.clock() - self._cached_at < self.cache_seconds:
                return dict(self._cached_release), True, self._checked_at

        release = fetch_latest_release(
            service_version=service_version,
            network_mode=network_mode,
            get=get,
        )
        checked_at = self.now().isoformat().replace("+00:00", "Z")
        with self._lock:
            self._cached_release = dict(release)
            self._cached_at = self.clock()
            self._checked_at = checked_at
        return release, False, checked_at

    def check(
        self,
        *,
        network_mode: str = "direct",
        app_info: Mapping[str, Any] | None = None,
        get: HttpGet | None = None,
    ) -> dict[str, Any]:
        current = dict(app_info or application_info())
        current_version = normalized_version(current.get("version"))
        if current_version is None:
            raise UpdateCheckError(
                "updateCheckCurrentVersionInvalid",
                "The installed Culvia version is not comparable.",
            )
        release, cached, checked_at = self._latest_release(
            service_version=str(current.get("serviceVersion") or current_version),
            network_mode=network_mode,
            get=get,
        )
        comparison = compare_versions(current_version, release["version"])
        status = "updateAvailable" if comparison < 0 else "ahead" if comparison > 0 else "current"
        return {
            "status": status,
            "updateAvailable": comparison < 0,
            "currentVersion": current_version,
            "latestVersion": release["version"],
            "releaseTag": release["tag"],
            "releaseName": release["name"],
            "releaseUrl": release["releaseUrl"],
            "publishedAt": release["publishedAt"],
            "package": _release_package(release, current),
            "channel": "stable",
            "checkedAt": checked_at,
            "cached": cached,
        }


UPDATE_CHECKER = UpdateChecker()
