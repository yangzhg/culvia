from __future__ import annotations

import argparse
import json
import re
import stat
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import build_linux_tgz, build_windows_zip


WINDOWS_ZIP_LABEL = "windows portable zip"
LINUX_TGZ_LABEL = "linux portable tgz"
WINDOWS_LITE_ZIP_LABEL = "windows lite zip"
LINUX_LITE_TGZ_LABEL = "linux lite tgz"
WINDOWS_PACKAGE_KIND = "culvia-windows-zip"
LINUX_PACKAGE_KIND = "culvia-linux-tgz"
WINDOWS_LITE_PACKAGE_KIND = "culvia-windows-lite-zip"
LINUX_LITE_PACKAGE_KIND = "culvia-linux-lite-tgz"

FORBIDDEN_PARTS = {
    ".agents",
    ".codex",
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "analysis_cache",
    "build",
    "dist",
    "model_cache",
    "node_modules",
    "culvia_uploads",
    "target",
    "thumbnail_cache",
    "upload_cache",
}
FORBIDDEN_FILENAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".pypirc.toml",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}
FORBIDDEN_SUFFIXES = (
    ".csv",
    ".db",
    ".env",
    ".key",
    ".p12",
    ".p8",
    ".pem",
    ".pyc",
    ".pyo",
    ".sqlite-shm",
    ".sqlite-wal",
    ".sqlite",
    ".sqlite3",
    ".token",
)
FORBIDDEN_NAME_PATTERNS = (
    re.compile(r"authkey_[a-z0-9]+\.p8$", re.IGNORECASE),
    re.compile(r".*private.*key.*", re.IGNORECASE),
)
WINDOWS_ABSOLUTE_PATTERN = re.compile(r"^[A-Za-z]:[\\/]")
SECRET_TEXT_PATTERNS = (
    re.compile(rb"sk-[A-Za-z0-9]{12,}"),
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(rb"APPLE_(CERTIFICATE|PASSWORD|API_KEY|API_ISSUER|ID|TEAM_ID)"),
    re.compile(rb"(ALIYUN|DASHSCOPE|DEEPSEEK|OPENAI)[A-Z0-9_]{0,32}(API)?_?KEY", re.IGNORECASE),
)
ALLOWED_FORBIDDEN_SUFFIX_PATTERNS = (re.compile(r"/_internal/certifi/cacert\.pem$", re.IGNORECASE),)
SECRET_SCAN_SKIP_PATTERNS = (re.compile(r"/[^/]+\.dist-info/record$", re.IGNORECASE),)
TEXT_SCAN_MAX_BYTES = 2_000_000


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class ArchiveMember:
    name: str
    is_file: bool
    is_dir: bool
    mode: int = 0
    link: bool = False
    special: bool = False


def result_payload(checks: Sequence[CheckResult]) -> dict[str, Any]:
    failed = [check.name for check in checks if not check.ok]
    return {
        "ok": not failed,
        "failed": failed,
        "checks": [
            {
                "name": check.name,
                "ok": check.ok,
                "detail": check.detail,
            }
            for check in checks
        ],
    }


def check(name: str, ok: bool, detail: str) -> CheckResult:
    return CheckResult(name=name, ok=bool(ok), detail=detail)


def safe_archive_name(name: str) -> bool:
    if not name or "\\" in name:
        return False
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts and "." not in path.parts


def top_level_dir(names: Iterable[str]) -> tuple[str | None, list[str]]:
    issues: list[str] = []
    roots: set[str] = set()
    for name in names:
        if not safe_archive_name(name):
            issues.append(f"unsafe path: {name}")
            continue
        parts = PurePosixPath(name).parts
        if parts:
            roots.add(parts[0])
    if len(roots) != 1:
        issues.append("archive must contain exactly one top-level directory")
    return (next(iter(roots)) if len(roots) == 1 else None), issues


def forbidden_artifact_issues(names: Iterable[str]) -> list[str]:
    issues: list[str] = []
    for name in names:
        path = PurePosixPath(name)
        lower_parts = {part.lower() for part in path.parts}
        lower_filename = path.name.lower()
        lower_name = name.lower()
        forbidden_parts = sorted(lower_parts & FORBIDDEN_PARTS)
        if forbidden_parts:
            issues.append(f"{name} contains forbidden directory {forbidden_parts[0]}")
        if lower_filename in FORBIDDEN_FILENAMES:
            issues.append(f"{name} contains forbidden credential filename")
        if any(pattern.fullmatch(lower_filename) for pattern in FORBIDDEN_NAME_PATTERNS):
            issues.append(f"{name} contains forbidden credential-like filename")
        if lower_name.endswith(FORBIDDEN_SUFFIXES) and not allowed_forbidden_suffix_name(name):
            issues.append(f"{name} contains forbidden runtime artifact suffix")
    return issues


def allowed_forbidden_suffix_name(name: str) -> bool:
    normalized = name.replace("\\", "/")
    return any(pattern.search(normalized) for pattern in ALLOWED_FORBIDDEN_SUFFIX_PATTERNS)


def zip_member_mode(info: zipfile.ZipInfo) -> int:
    return (info.external_attr >> 16) & 0xFFFF


def looks_binary(payload: bytes) -> bool:
    return b"\0" in payload[:4096]


def secret_content_issues(payload_by_name: Iterable[tuple[str, bytes]]) -> list[str]:
    issues: list[str] = []
    for name, payload in payload_by_name:
        if secret_scan_skip_name(name):
            continue
        if not payload or looks_binary(payload):
            continue
        sample = payload[:TEXT_SCAN_MAX_BYTES]
        if any(pattern.search(sample) for pattern in SECRET_TEXT_PATTERNS):
            issues.append(f"{name} contains credential-like text")
    return issues


def secret_scan_skip_name(name: str) -> bool:
    normalized = name.replace("\\", "/")
    return any(pattern.search(normalized) for pattern in SECRET_SCAN_SKIP_PATTERNS)


def member_lookup(members: Sequence[ArchiveMember]) -> dict[str, ArchiveMember]:
    return {member.name: member for member in members}


def file_exists(lookup: dict[str, ArchiveMember], name: str) -> bool:
    member = lookup.get(name)
    return bool(member and member.is_file)


def user_executable(member: ArchiveMember | None) -> bool:
    return bool(member and member.is_file and (member.mode & stat.S_IXUSR))


def pe_machine_from_bytes(payload: bytes) -> int | None:
    if len(payload) < 0x40 or payload[:2] != b"MZ":
        return None
    pe_offset = int.from_bytes(payload[0x3C:0x40], "little")
    if len(payload) < pe_offset + 6 or payload[pe_offset : pe_offset + 4] != b"PE\0\0":
        return None
    return int.from_bytes(payload[pe_offset + 4 : pe_offset + 6], "little")


def is_elf_payload(payload: bytes) -> bool:
    return payload[:4] == b"\x7fELF"


def read_json_payload(payload: bytes) -> tuple[dict[str, Any] | None, str]:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"invalid JSON: {exc}"
    if not isinstance(data, dict):
        return None, "manifest must contain a JSON object"
    return data, ""


def relative_manifest_path(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    return safe_archive_name(value) and not WINDOWS_ABSOLUTE_PATTERN.match(value)


def expected_manifest_strings(manifest: dict[str, Any], expectations: dict[tuple[str, ...], Any]) -> list[str]:
    issues: list[str] = []
    for keys, expected in expectations.items():
        current: Any = manifest
        for key in keys:
            current = current.get(key) if isinstance(current, dict) else None
        if current != expected:
            issues.append(".".join(keys) + f" expected {expected!r}, got {current!r}")
    return issues


def manifest_path_issues(manifest: dict[str, Any], paths: Sequence[tuple[str, ...]]) -> list[str]:
    issues: list[str] = []
    for keys in paths:
        current: Any = manifest
        for key in keys:
            current = current.get(key) if isinstance(current, dict) else None
        if not relative_manifest_path(current):
            issues.append(".".join(keys) + " must be a safe relative path")
    return issues


def zip_members(path: Path) -> tuple[list[ArchiveMember], list[str]]:
    issues: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                issues.append("archive contains duplicate entries")
            members = []
            for info in infos:
                mode = zip_member_mode(info)
                members.append(
                    ArchiveMember(
                        name=info.filename.rstrip("/") if info.is_dir() else info.filename,
                        is_file=not info.is_dir(),
                        is_dir=info.is_dir(),
                        mode=mode,
                        link=stat.S_ISLNK(mode),
                    )
                )
    except (OSError, zipfile.BadZipFile) as exc:
        return [], [f"cannot read zip: {exc}"]
    return members, issues


def tar_members(path: Path) -> tuple[list[ArchiveMember], list[str]]:
    issues: list[str] = []
    try:
        with tarfile.open(path, "r:gz") as archive:
            infos = archive.getmembers()
            names = [info.name for info in infos]
            if len(names) != len(set(names)):
                issues.append("archive contains duplicate entries")
            members = [
                ArchiveMember(
                    name=info.name.rstrip("/") if info.isdir() else info.name,
                    is_file=info.isfile(),
                    is_dir=info.isdir(),
                    mode=info.mode,
                    link=info.issym() or info.islnk(),
                    special=info.isdev(),
                )
                for info in infos
            ]
    except (OSError, tarfile.TarError) as exc:
        return [], [f"cannot read tar.gz: {exc}"]
    return members, issues


def read_zip_file(path: Path, member: str) -> bytes:
    with zipfile.ZipFile(path) as archive:
        return archive.read(member)


def zip_text_payloads(path: Path, members: Sequence[ArchiveMember]) -> list[tuple[str, bytes]]:
    payloads: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(path) as archive:
        for member in members:
            if member.is_file and not member.link:
                with archive.open(member.name) as handle:
                    sample = handle.read(TEXT_SCAN_MAX_BYTES)
                if not looks_binary(sample):
                    payloads.append((member.name, sample))
    return payloads


def read_tar_file(path: Path, member: str) -> bytes:
    with tarfile.open(path, "r:gz") as archive:
        extracted = archive.extractfile(member)
        if extracted is None:
            return b""
        return extracted.read()


def tar_text_payloads(path: Path, members: Sequence[ArchiveMember]) -> list[tuple[str, bytes]]:
    payloads: list[tuple[str, bytes]] = []
    with tarfile.open(path, "r:gz") as archive:
        for member in members:
            if member.is_file and not member.link and not member.special:
                extracted = archive.extractfile(member.name)
                if extracted is not None:
                    sample = extracted.read(TEXT_SCAN_MAX_BYTES)
                    if not looks_binary(sample):
                        payloads.append((member.name, sample))
    return payloads


def collect_windows_zip_checks(path: Path) -> list[CheckResult]:
    checks: list[CheckResult] = []
    checks.append(check(f"{WINDOWS_ZIP_LABEL} artifact exists", path.is_file(), f"{path}"))
    if not path.is_file():
        return checks

    members, member_issues = zip_members(path)
    names = [member.name for member in members]
    prefix, path_issues = top_level_dir(names)
    pollution_issues = forbidden_artifact_issues(names)
    link_issues = [member.name for member in members if member.link or member.special]
    secret_issues = secret_content_issues(zip_text_payloads(path, members)) if members else []
    lookup = member_lookup(members)
    checks.append(
        check(f"{WINDOWS_ZIP_LABEL} archive can be read", not member_issues, "; ".join(member_issues) or "zip opened")
    )
    checks.append(
        check(
            f"{WINDOWS_ZIP_LABEL} archive paths are safe",
            not path_issues,
            "; ".join(path_issues) or "one safe top-level directory",
        )
    )
    checks.append(
        check(
            f"{WINDOWS_ZIP_LABEL} archive has no links or special entries",
            not link_issues,
            ", ".join(link_issues[:5]) or "regular files and directories only",
        )
    )
    checks.append(
        check(
            f"{WINDOWS_ZIP_LABEL} excludes runtime artifacts",
            not pollution_issues,
            "; ".join(pollution_issues[:5]) or "no cache/database/export artifacts",
        )
    )
    checks.append(
        check(
            f"{WINDOWS_ZIP_LABEL} excludes secrets and credentials",
            not secret_issues,
            "; ".join(secret_issues[:5]) or "no credential-like text",
        )
    )
    if not prefix:
        return checks

    required = {
        f"{prefix}/culvia-desktop.exe": "launcher",
        f"{prefix}/share/culvia/web/index.html": "web entry",
        f"{prefix}/share/culvia/manifest.json": "manifest",
        f"{prefix}/README.md": "readme",
    }
    missing = [label for member, label in required.items() if not file_exists(lookup, member)]
    checks.append(
        check(
            f"{WINDOWS_ZIP_LABEL} layout is complete", not missing, ", ".join(missing) or "required files are present"
        )
    )
    if missing:
        return checks

    manifest_path = f"{prefix}/share/culvia/manifest.json"
    manifest, manifest_error = read_json_payload(read_zip_file(path, manifest_path))
    checks.append(
        check(f"{WINDOWS_ZIP_LABEL} manifest is valid", manifest is not None, manifest_error or "manifest JSON object")
    )
    if manifest is None:
        return checks

    target = str(manifest.get("target") or "")
    backend_path = build_windows_zip.backend_package_binary(target).as_posix()
    backend_runtime_dir = build_windows_zip.backend_package_dir(target).as_posix()
    manifest_issues = expected_manifest_strings(
        manifest,
        {
            ("kind",): WINDOWS_PACKAGE_KIND,
            ("launcher",): build_windows_zip.PACKAGE_DESKTOP_NAME,
            ("desktop", "path"): build_windows_zip.PACKAGE_DESKTOP_NAME,
            ("desktop", "expectedFormat"): "PE",
            ("backend", "path"): backend_path,
            ("backend", "runtimeDir"): backend_runtime_dir,
            ("backend", "expectedFormat"): "PE",
            ("backend", "mustNotRequireUserPython"): True,
            ("web", "entry"): "share/culvia/web/index.html",
        },
    )
    manifest_issues.extend(
        manifest_path_issues(
            manifest,
            (
                ("launcher",),
                ("desktop", "path"),
                ("backend", "path"),
                ("backend", "runtimeDir"),
                ("web", "path"),
                ("web", "entry"),
            ),
        )
    )
    checks.append(
        check(
            f"{WINDOWS_ZIP_LABEL} manifest contract",
            not manifest_issues,
            "; ".join(manifest_issues) or "manifest matches Windows portable package contract",
        )
    )

    expected_machine = build_windows_zip.PE_MACHINE_BY_TARGET.get(target)
    binary_issues: list[str] = []
    if not file_exists(lookup, f"{prefix}/{backend_path}"):
        binary_issues.append("backend runtime executable is missing")
    for package_member, label in (
        (f"{prefix}/culvia-desktop.exe", "launcher"),
        (f"{prefix}/{backend_path}", "backend"),
    ):
        if not file_exists(lookup, package_member):
            continue
        machine = pe_machine_from_bytes(read_zip_file(path, package_member))
        if machine is None:
            binary_issues.append(f"{label} is not a PE executable")
        elif expected_machine is not None and machine != expected_machine:
            binary_issues.append(f"{label} PE machine expected 0x{expected_machine:04x}, got 0x{machine:04x}")
    if expected_machine is None:
        binary_issues.append(f"unknown Windows target: {target}")
    checks.append(
        check(
            f"{WINDOWS_ZIP_LABEL} binaries match target",
            not binary_issues,
            "; ".join(binary_issues) or f"PE machine matches {target}",
        )
    )
    return checks


def collect_windows_lite_zip_checks(path: Path) -> list[CheckResult]:
    checks: list[CheckResult] = []
    checks.append(check(f"{WINDOWS_LITE_ZIP_LABEL} artifact exists", path.is_file(), f"{path}"))
    if not path.is_file():
        return checks

    members, member_issues = zip_members(path)
    names = [member.name for member in members]
    prefix, path_issues = top_level_dir(names)
    pollution_issues = forbidden_artifact_issues(names)
    link_issues = [member.name for member in members if member.link or member.special]
    secret_issues = secret_content_issues(zip_text_payloads(path, members)) if members else []
    lookup = member_lookup(members)
    checks.append(
        check(
            f"{WINDOWS_LITE_ZIP_LABEL} archive can be read",
            not member_issues,
            "; ".join(member_issues) or "zip opened",
        )
    )
    checks.append(
        check(
            f"{WINDOWS_LITE_ZIP_LABEL} archive paths are safe",
            not path_issues,
            "; ".join(path_issues) or "one safe top-level directory",
        )
    )
    checks.append(
        check(
            f"{WINDOWS_LITE_ZIP_LABEL} archive has no links or special entries",
            not link_issues,
            ", ".join(link_issues[:5]) or "regular files and directories only",
        )
    )
    checks.append(
        check(
            f"{WINDOWS_LITE_ZIP_LABEL} excludes runtime artifacts",
            not pollution_issues,
            "; ".join(pollution_issues[:5]) or "no cache/database/export artifacts",
        )
    )
    checks.append(
        check(
            f"{WINDOWS_LITE_ZIP_LABEL} excludes secrets and credentials",
            not secret_issues,
            "; ".join(secret_issues[:5]) or "no credential-like text",
        )
    )
    if not prefix:
        return checks

    required = {
        f"{prefix}/culvia-desktop.exe": "launcher",
        f"{prefix}/share/culvia/manifest.json": "manifest",
        f"{prefix}/README.md": "readme",
    }
    missing = [label for member, label in required.items() if not file_exists(lookup, member)]
    checks.append(
        check(
            f"{WINDOWS_LITE_ZIP_LABEL} layout is complete",
            not missing,
            ", ".join(missing) or "required files are present",
        )
    )
    if missing:
        return checks

    forbidden_runtime = [name for name in names if "/runtime/backend/" in name or "/share/culvia/web/" in name]
    checks.append(
        check(
            f"{WINDOWS_LITE_ZIP_LABEL} does not bundle backend or web assets",
            not forbidden_runtime,
            ", ".join(forbidden_runtime[:5]) or "lite archive contains desktop shell only",
        )
    )

    manifest_path = f"{prefix}/share/culvia/manifest.json"
    manifest, manifest_error = read_json_payload(read_zip_file(path, manifest_path))
    checks.append(
        check(
            f"{WINDOWS_LITE_ZIP_LABEL} manifest is valid",
            manifest is not None,
            manifest_error or "manifest JSON object",
        )
    )
    if manifest is None:
        return checks

    manifest_issues = expected_manifest_strings(
        manifest,
        {
            ("kind",): WINDOWS_LITE_PACKAGE_KIND,
            ("runtimeProfile",): "lite",
            ("launcher",): build_windows_zip.PACKAGE_DESKTOP_NAME,
            ("desktop", "path"): build_windows_zip.PACKAGE_DESKTOP_NAME,
            ("desktop", "expectedFormat"): "PE",
            ("desktop", "defaultRuntimeMode"): "lite",
            ("backend", "mode"): "lite",
            ("backend", "bundled"): False,
            ("backend", "mustNotRequireUserPython"): False,
            ("backend", "managedVenv"): True,
        },
    )
    manifest_issues.extend(manifest_path_issues(manifest, (("launcher",), ("desktop", "path"))))
    checks.append(
        check(
            f"{WINDOWS_LITE_ZIP_LABEL} manifest contract",
            not manifest_issues,
            "; ".join(manifest_issues) or "manifest matches Windows Lite package contract",
        )
    )

    target = str(manifest.get("target") or "")
    expected_machine = build_windows_zip.PE_MACHINE_BY_TARGET.get(target)
    machine = pe_machine_from_bytes(read_zip_file(path, f"{prefix}/culvia-desktop.exe"))
    binary_issues: list[str] = []
    if machine is None:
        binary_issues.append("desktop shell is not a PE executable")
    elif expected_machine is not None and machine != expected_machine:
        binary_issues.append(f"desktop shell PE machine expected 0x{expected_machine:04x}, got 0x{machine:04x}")
    if expected_machine is None:
        binary_issues.append(f"unknown Windows target: {target}")
    checks.append(
        check(
            f"{WINDOWS_LITE_ZIP_LABEL} desktop binary matches target",
            not binary_issues,
            "; ".join(binary_issues) or f"PE machine matches {target}",
        )
    )
    return checks


def collect_linux_tgz_checks(path: Path) -> list[CheckResult]:
    checks: list[CheckResult] = []
    checks.append(check(f"{LINUX_TGZ_LABEL} artifact exists", path.is_file(), f"{path}"))
    if not path.is_file():
        return checks

    members, member_issues = tar_members(path)
    names = [member.name for member in members]
    prefix, path_issues = top_level_dir(names)
    pollution_issues = forbidden_artifact_issues(names)
    tar_special_issues = [member.name for member in members if member.link or member.special]
    secret_issues = secret_content_issues(tar_text_payloads(path, members)) if members else []
    lookup = member_lookup(members)
    checks.append(
        check(f"{LINUX_TGZ_LABEL} archive can be read", not member_issues, "; ".join(member_issues) or "tar.gz opened")
    )
    checks.append(
        check(
            f"{LINUX_TGZ_LABEL} archive paths are safe",
            not path_issues,
            "; ".join(path_issues) or "one safe top-level directory",
        )
    )
    checks.append(
        check(
            f"{LINUX_TGZ_LABEL} archive has no links or devices",
            not tar_special_issues,
            ", ".join(tar_special_issues[:5]) or "regular files and directories only",
        )
    )
    checks.append(
        check(
            f"{LINUX_TGZ_LABEL} excludes runtime artifacts",
            not pollution_issues,
            "; ".join(pollution_issues[:5]) or "no cache/database/export artifacts",
        )
    )
    checks.append(
        check(
            f"{LINUX_TGZ_LABEL} excludes secrets and credentials",
            not secret_issues,
            "; ".join(secret_issues[:5]) or "no credential-like text",
        )
    )
    if not prefix:
        return checks

    required = {
        f"{prefix}/bin/culvia": "launcher",
        f"{prefix}/bin/culvia-desktop": "desktop",
        f"{prefix}/share/culvia/web/index.html": "web entry",
        f"{prefix}/share/culvia/manifest.json": "manifest",
        f"{prefix}/README.md": "readme",
    }
    missing = [label for member, label in required.items() if not file_exists(lookup, member)]
    checks.append(
        check(f"{LINUX_TGZ_LABEL} layout is complete", not missing, ", ".join(missing) or "required files are present")
    )
    if missing:
        return checks

    executable_issues = [
        label
        for member, label in (
            (lookup.get(f"{prefix}/bin/culvia"), "launcher"),
            (lookup.get(f"{prefix}/bin/culvia-desktop"), "desktop"),
        )
        if not user_executable(member)
    ]
    checks.append(
        check(
            f"{LINUX_TGZ_LABEL} executables have user execute bit",
            not executable_issues,
            ", ".join(executable_issues) or "launcher and binaries are executable",
        )
    )

    launcher_text = read_tar_file(path, f"{prefix}/bin/culvia").decode("utf-8", errors="replace")
    launcher_issues = [
        text
        for text in ("CULVIA_WEB_DIR", "CULVIA_BACKEND_PATH", "CULVIA_DESKTOP_FORCE_BACKEND", "culvia-desktop")
        if text not in launcher_text
    ]
    checks.append(
        check(
            f"{LINUX_TGZ_LABEL} launcher wires bundled runtime",
            not launcher_issues,
            ", ".join(launcher_issues) or "launcher points at bundled web, backend, and desktop shell binary",
        )
    )

    manifest_path = f"{prefix}/share/culvia/manifest.json"
    manifest, manifest_error = read_json_payload(read_tar_file(path, manifest_path))
    checks.append(
        check(f"{LINUX_TGZ_LABEL} manifest is valid", manifest is not None, manifest_error or "manifest JSON object")
    )
    if manifest is None:
        return checks

    target = str(manifest.get("target") or "")
    backend_path = build_linux_tgz.backend_package_binary(target).as_posix()
    backend_runtime_dir = build_linux_tgz.backend_package_dir(target).as_posix()
    manifest_issues = expected_manifest_strings(
        manifest,
        {
            ("kind",): LINUX_PACKAGE_KIND,
            ("launcher",): "bin/culvia",
            ("desktop", "path"): "bin/culvia-desktop",
            ("desktop", "expectedFormat"): "ELF",
            ("backend", "path"): backend_path,
            ("backend", "runtimeDir"): backend_runtime_dir,
            ("backend", "expectedFormat"): "ELF",
            ("backend", "mustNotRequireUserPython"): True,
            ("web", "entry"): "share/culvia/web/index.html",
            ("web", "env"): "CULVIA_WEB_DIR",
        },
    )
    manifest_issues.extend(
        manifest_path_issues(
            manifest,
            (
                ("launcher",),
                ("desktop", "path"),
                ("backend", "path"),
                ("backend", "runtimeDir"),
                ("web", "path"),
                ("web", "entry"),
            ),
        )
    )
    checks.append(
        check(
            f"{LINUX_TGZ_LABEL} manifest contract",
            not manifest_issues,
            "; ".join(manifest_issues) or "manifest matches Linux portable package contract",
        )
    )

    binary_issues: list[str] = []
    backend_member = f"{prefix}/{backend_path}"
    if not file_exists(lookup, backend_member):
        binary_issues.append("backend runtime executable is missing")
    elif not user_executable(lookup.get(backend_member)):
        binary_issues.append("backend runtime executable is not user-executable")
    for package_member, label in (
        (f"{prefix}/bin/culvia-desktop", "desktop"),
        (backend_member, "backend"),
    ):
        if not file_exists(lookup, package_member):
            continue
        if not is_elf_payload(read_tar_file(path, package_member)):
            binary_issues.append(f"{label} is not an ELF executable")
    checks.append(
        check(
            f"{LINUX_TGZ_LABEL} binaries are ELF and executable",
            not binary_issues,
            "; ".join(binary_issues) or "desktop shell and backend are ELF",
        )
    )
    return checks


def collect_linux_lite_tgz_checks(path: Path) -> list[CheckResult]:
    checks: list[CheckResult] = []
    checks.append(check(f"{LINUX_LITE_TGZ_LABEL} artifact exists", path.is_file(), f"{path}"))
    if not path.is_file():
        return checks

    members, member_issues = tar_members(path)
    names = [member.name for member in members]
    prefix, path_issues = top_level_dir(names)
    pollution_issues = forbidden_artifact_issues(names)
    tar_special_issues = [member.name for member in members if member.link or member.special]
    secret_issues = secret_content_issues(tar_text_payloads(path, members)) if members else []
    lookup = member_lookup(members)
    checks.append(
        check(
            f"{LINUX_LITE_TGZ_LABEL} archive can be read",
            not member_issues,
            "; ".join(member_issues) or "tar.gz opened",
        )
    )
    checks.append(
        check(
            f"{LINUX_LITE_TGZ_LABEL} archive paths are safe",
            not path_issues,
            "; ".join(path_issues) or "one safe top-level directory",
        )
    )
    checks.append(
        check(
            f"{LINUX_LITE_TGZ_LABEL} archive has no links or devices",
            not tar_special_issues,
            ", ".join(tar_special_issues[:5]) or "regular files and directories only",
        )
    )
    checks.append(
        check(
            f"{LINUX_LITE_TGZ_LABEL} excludes runtime artifacts",
            not pollution_issues,
            "; ".join(pollution_issues[:5]) or "no cache/database/export artifacts",
        )
    )
    checks.append(
        check(
            f"{LINUX_LITE_TGZ_LABEL} excludes secrets and credentials",
            not secret_issues,
            "; ".join(secret_issues[:5]) or "no credential-like text",
        )
    )
    if not prefix:
        return checks

    required = {
        f"{prefix}/bin/culvia": "launcher",
        f"{prefix}/bin/culvia-desktop": "desktop",
        f"{prefix}/share/culvia/manifest.json": "manifest",
        f"{prefix}/README.md": "readme",
    }
    missing = [label for member, label in required.items() if not file_exists(lookup, member)]
    checks.append(
        check(
            f"{LINUX_LITE_TGZ_LABEL} layout is complete",
            not missing,
            ", ".join(missing) or "required files are present",
        )
    )
    if missing:
        return checks

    executable_issues = [
        label
        for member, label in (
            (lookup.get(f"{prefix}/bin/culvia"), "launcher"),
            (lookup.get(f"{prefix}/bin/culvia-desktop"), "desktop"),
        )
        if not user_executable(member)
    ]
    checks.append(
        check(
            f"{LINUX_LITE_TGZ_LABEL} executables have user execute bit",
            not executable_issues,
            ", ".join(executable_issues) or "launcher and desktop shell are executable",
        )
    )

    forbidden_runtime = [name for name in names if "/runtime/backend/" in name or "/share/culvia/web/" in name]
    checks.append(
        check(
            f"{LINUX_LITE_TGZ_LABEL} does not bundle backend or web assets",
            not forbidden_runtime,
            ", ".join(forbidden_runtime[:5]) or "lite archive contains desktop shell only",
        )
    )

    launcher_text = read_tar_file(path, f"{prefix}/bin/culvia").decode("utf-8", errors="replace")
    launcher_issues = [
        text for text in ("CULVIA_DESKTOP_RUNTIME_MODE", "lite", "culvia-desktop") if text not in launcher_text
    ]
    full_runtime_leaks = [
        text for text in ("CULVIA_BACKEND_PATH", "CULVIA_DESKTOP_FORCE_BACKEND") if text in launcher_text
    ]
    checks.append(
        check(
            f"{LINUX_LITE_TGZ_LABEL} launcher wires lite runtime",
            not launcher_issues and not full_runtime_leaks,
            "; ".join([*launcher_issues, *full_runtime_leaks]) or "launcher defaults to Lite runtime",
        )
    )

    manifest_path = f"{prefix}/share/culvia/manifest.json"
    manifest, manifest_error = read_json_payload(read_tar_file(path, manifest_path))
    checks.append(
        check(
            f"{LINUX_LITE_TGZ_LABEL} manifest is valid", manifest is not None, manifest_error or "manifest JSON object"
        )
    )
    if manifest is None:
        return checks

    manifest_issues = expected_manifest_strings(
        manifest,
        {
            ("kind",): LINUX_LITE_PACKAGE_KIND,
            ("runtimeProfile",): "lite",
            ("launcher",): "bin/culvia",
            ("desktop", "path"): "bin/culvia-desktop",
            ("desktop", "expectedFormat"): "ELF",
            ("desktop", "defaultRuntimeMode"): "lite",
            ("backend", "mode"): "lite",
            ("backend", "bundled"): False,
            ("backend", "mustNotRequireUserPython"): False,
            ("backend", "managedVenv"): True,
        },
    )
    manifest_issues.extend(manifest_path_issues(manifest, (("launcher",), ("desktop", "path"))))
    checks.append(
        check(
            f"{LINUX_LITE_TGZ_LABEL} manifest contract",
            not manifest_issues,
            "; ".join(manifest_issues) or "manifest matches Linux Lite package contract",
        )
    )

    binary_issues: list[str] = []
    desktop_member = f"{prefix}/bin/culvia-desktop"
    if file_exists(lookup, desktop_member) and not is_elf_payload(read_tar_file(path, desktop_member)):
        binary_issues.append("desktop shell is not an ELF executable")
    checks.append(
        check(
            f"{LINUX_LITE_TGZ_LABEL} desktop binary is ELF",
            not binary_issues,
            "; ".join(binary_issues) or "desktop shell is ELF",
        )
    )
    return checks


def collect_checks(
    *,
    windows_zip: Path | None = None,
    linux_tgz: Path | None = None,
    windows_lite_zip: Path | None = None,
    linux_lite_tgz: Path | None = None,
) -> list[CheckResult]:
    checks: list[CheckResult] = []
    if windows_zip is not None:
        checks.extend(collect_windows_zip_checks(windows_zip))
    if linux_tgz is not None:
        checks.extend(collect_linux_tgz_checks(linux_tgz))
    if windows_lite_zip is not None:
        checks.extend(collect_windows_lite_zip_checks(windows_lite_zip))
    if linux_lite_tgz is not None:
        checks.extend(collect_linux_lite_tgz_checks(linux_lite_tgz))
    if windows_zip is None and linux_tgz is None and windows_lite_zip is None and linux_lite_tgz is None:
        checks.append(
            check(
                "portable package artifact selected",
                False,
                "pass --windows-zip, --linux-tgz, --windows-lite-zip, or --linux-lite-tgz",
            )
        )
    return checks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate built Windows/Linux self-contained desktop packages.")
    parser.add_argument("--windows-zip", type=Path, default=None, help="Path to a built Windows portable zip artifact.")
    parser.add_argument("--linux-tgz", type=Path, default=None, help="Path to a built Linux tar.gz artifact.")
    parser.add_argument(
        "--windows-lite-zip", type=Path, default=None, help="Path to a built Windows Lite zip artifact."
    )
    parser.add_argument("--linux-lite-tgz", type=Path, default=None, help="Path to a built Linux Lite tar.gz artifact.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable results.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    checks = collect_checks(
        windows_zip=args.windows_zip,
        linux_tgz=args.linux_tgz,
        windows_lite_zip=args.windows_lite_zip,
        linux_lite_tgz=args.linux_lite_tgz,
    )
    payload = result_payload(checks)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for item in checks:
            print(("OK" if item.ok else "FAIL") + f" {item.name}: {item.detail}")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
