from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ".github/workflows/desktop-release.yml"
CONTRACT_TOOL_PATH = "tools/desktop_release_contract.py"
ALLOWED_ARTIFACT_PATHS = (
    "dist/macos/*.dmg",
    "dist/macos-lite/*.dmg",
    "dist/windows/culvia-*-windows-x86_64-pc-windows-msvc.zip",
    "dist/windows-lite/culvia-*-windows-lite-x86_64-pc-windows-msvc.zip",
    "dist/linux/culvia-*-linux-x86_64-unknown-linux-gnu.tar.gz",
    "dist/linux-lite/culvia-*-linux-lite-x86_64-unknown-linux-gnu.tar.gz",
)
ALLOWED_CHECKSUM_PATHS = (
    "dist/macos/*.dmg.sha256",
    "dist/macos-lite/*.dmg.sha256",
    "dist/windows/culvia-*-windows-x86_64-pc-windows-msvc.zip.sha256",
    "dist/windows-lite/culvia-*-windows-lite-x86_64-pc-windows-msvc.zip.sha256",
    "dist/linux/culvia-*-linux-x86_64-unknown-linux-gnu.tar.gz.sha256",
    "dist/linux-lite/culvia-*-linux-lite-x86_64-unknown-linux-gnu.tar.gz.sha256",
)
ALLOWED_EVIDENCE_PATHS = (
    "dist/macos/*.dmg.evidence.json",
    "dist/macos-lite/*.dmg.evidence.json",
    "dist/windows/culvia-*-windows-x86_64-pc-windows-msvc.zip.evidence.json",
    "dist/windows-lite/culvia-*-windows-lite-x86_64-pc-windows-msvc.zip.evidence.json",
    "dist/linux/culvia-*-linux-x86_64-unknown-linux-gnu.tar.gz.evidence.json",
    "dist/linux-lite/culvia-*-linux-lite-x86_64-unknown-linux-gnu.tar.gz.evidence.json",
)
FORBIDDEN_WORKFLOW_PATTERNS = (
    (r"\$\{\{\s*secrets\.", "secrets context"),
    (r"continue-on-error\s*:\s*(true|\$\{\{)", "continue-on-error bypass"),
    (r"\|\|\s*true\b", "shell success bypass"),
    (r"\bif\s*:\s*always\(\)", "always upload/run bypass"),
    (r"\bset\s+\+e\b", "disabled shell error exit"),
)
FORBIDDEN_UPLOAD_PATHS = (
    ".",
    "./**",
    "dist/**",
    "target/**",
    "desktop/tauri/src-tauri/runtime/**",
    "desktop/tauri/src-tauri/target/**",
    "model_cache/**",
    "analysis_cache/**",
    "thumbnail_cache/**",
    "upload_cache/**",
    "culvia_uploads/**",
    "*.sqlite",
    "*.db",
    "*.csv",
    ".env*",
    "*.pem",
    "*.key",
    "*.token",
    "~/**",
    "$HOME/**",
)
REQUIRED_UPLOAD_PATH_REFERENCE = "${{ matrix.artifact_path }}"
REQUIRED_UPLOAD_CHECKSUM_REFERENCE = "${{ matrix.checksum_path }}"
REQUIRED_UPLOAD_EVIDENCE_REFERENCE = "${{ matrix.evidence_path }}"
SOURCE_UPLOAD_PATHS = ("dist/python/culvia-*.whl", "dist/python/culvia-*.tar.gz")
RAW_CACHE_ACTION = "actions/cache"
ATTEST_ACTION = "actions/attest"


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def read_optional(root: Path, relative: str) -> str:
    path = root / relative
    return path.read_text(encoding="utf-8") if path.exists() else ""


def check(name: str, ok: bool, detail: str) -> CheckResult:
    return CheckResult(name=name, ok=bool(ok), detail=detail)


def result_payload(checks: Sequence[CheckResult]) -> dict:
    failed = [item.name for item in checks if not item.ok]
    return {
        "ok": not failed,
        "failed": failed,
        "checks": [{"name": item.name, "ok": item.ok, "detail": item.detail} for item in checks],
    }


def clean_yaml_value(value: str) -> str:
    return value.strip().strip("'\"")


def step_blocks(workflow: str) -> list[str]:
    lines = workflow.splitlines()
    blocks: list[list[str]] = []
    current: list[str] = []
    current_indent: int | None = None
    step_start = re.compile(r"^(?P<indent>\s*)-\s+name\s*:")
    for line in lines:
        match = step_start.match(line)
        if match:
            indent = len(match.group("indent"))
            if current and current_indent is not None and indent <= current_indent:
                blocks.append(current)
                current = []
            current_indent = indent
        if current_indent is not None:
            current.append(line)
    if current:
        blocks.append(current)
    return ["\n".join(block) for block in blocks]


def action_blocks(workflow: str, action: str) -> list[str]:
    return [block for block in step_blocks(workflow) if re.search(rf"uses\s*:\s*{re.escape(action)}(@|\s|$)", block)]


def yaml_key_values(text: str, key: str) -> list[str]:
    values: list[str] = []
    lines = text.splitlines()
    key_pattern = re.compile(rf"^(?P<indent>\s*){re.escape(key)}\s*:\s*(?P<value>.*)$")
    index = 0
    while index < len(lines):
        match = key_pattern.match(lines[index])
        if not match:
            index += 1
            continue
        value = clean_yaml_value(match.group("value"))
        if value in {"|", ">"}:
            indent = len(match.group("indent"))
            nested: list[str] = []
            index += 1
            while index < len(lines):
                next_line = lines[index]
                stripped = next_line.strip()
                if stripped and len(next_line) - len(next_line.lstrip(" ")) <= indent:
                    break
                if stripped:
                    nested.append(clean_yaml_value(stripped))
                index += 1
            values.append("\n".join(nested))
            continue
        values.append(value)
        index += 1
    return values


def embedded_mapping_values(text: str, key: str) -> list[str]:
    pattern = re.compile(rf"['\"]{re.escape(key)}['\"]\s*:\s*['\"]([^'\"]+)['\"]")
    return [clean_yaml_value(match.group(1)) for match in pattern.finditer(text)]


def matrix_artifact_paths(workflow: str) -> list[str]:
    return [*yaml_key_values(workflow, "artifact_path"), *embedded_mapping_values(workflow, "artifact_path")]


def matrix_checksum_paths(workflow: str) -> list[str]:
    return [*yaml_key_values(workflow, "checksum_path"), *embedded_mapping_values(workflow, "checksum_path")]


def matrix_evidence_paths(workflow: str) -> list[str]:
    return [*yaml_key_values(workflow, "evidence_path"), *embedded_mapping_values(workflow, "evidence_path")]


def upload_artifact_paths(workflow: str) -> list[str]:
    values: list[str] = []
    for block in action_blocks(workflow, "actions/upload-artifact"):
        for value in yaml_key_values(block, "path"):
            values.extend(line.strip() for line in value.splitlines() if line.strip())
    return values


def forbidden_bypass_matches(workflow: str) -> list[str]:
    issues: list[str] = []
    for pattern, label in FORBIDDEN_WORKFLOW_PATTERNS:
        if re.search(pattern, workflow):
            issues.append(label)
    return issues


def forbidden_upload_path_values(paths: Sequence[str]) -> list[str]:
    return [path for path in paths if path in FORBIDDEN_UPLOAD_PATHS]


def collect_checks(root: Path = ROOT) -> list[CheckResult]:
    workflow = read_optional(root, WORKFLOW_PATH)
    contract_tool = read_optional(root, CONTRACT_TOOL_PATH)
    upload_paths = upload_artifact_paths(workflow)
    artifact_paths = matrix_artifact_paths(workflow)
    checksum_paths = matrix_checksum_paths(workflow)
    evidence_paths = matrix_evidence_paths(workflow)
    upload_artifact_blocks = action_blocks(workflow, "actions/upload-artifact")
    attest_blocks = action_blocks(workflow, ATTEST_ACTION)
    raw_cache_blocks = action_blocks(workflow, RAW_CACHE_ACTION)
    forbidden_uploads = forbidden_upload_path_values([*upload_paths, *artifact_paths, *checksum_paths, *evidence_paths])
    bypasses = forbidden_bypass_matches(workflow)
    checks = [
        check("desktop release workflow exists", bool(workflow), WORKFLOW_PATH),
        check("desktop release contract tool exists", bool(contract_tool), CONTRACT_TOOL_PATH),
        check(
            "workflow is manually triggered with read-only permissions",
            "workflow_dispatch:" in workflow and "permissions:" in workflow and "contents: read" in workflow,
            "workflow_dispatch and contents: read are required",
        ),
        check(
            "workflow targets real Windows and Linux runners",
            all(
                text in workflow
                for text in (
                    "windows-latest",
                    "ubuntu-latest",
                    "x86_64-pc-windows-msvc",
                    "x86_64-unknown-linux-gnu",
                )
            ),
            "Windows and Linux matrix targets must be explicit",
        ),
        check(
            "workflow installs required toolchains",
            all(
                text in workflow
                for text in (
                    "actions/setup-python@v5",
                    'python-version: "3.11"',
                    "actions/setup-node@v4",
                    'node-version: "20"',
                    "rustup default stable",
                    "libwebkit2gtk-4.1-dev",
                    "patchelf",
                    "xvfb",
                )
            ),
            "Python, Node, Rust, and Linux desktop shell dependencies are required",
        ),
        check(
            "workflow delegates release steps to local contract tool",
            f"{CONTRACT_TOOL_PATH} --platform" in workflow
            and "--check-plan --json" in workflow
            and "--run --json" in workflow,
            "workflow must call the local desktop release contract plan and run modes",
        ),
        check(
            "contract tool runs the real release chain",
            all(
                text in contract_tool
                for text in (
                    "--build",
                    "check_backend_smoke.py",
                    "tauri:build",
                    "build_windows_zip.py",
                    "build_linux_tgz.py",
                    "check_portable_package_preflight.py",
                    "check_portable_package_runtime.py",
                    "write_release_checksum.py",
                    "write_release_evidence_manifest",
                    "write_manifest_from_contract_payload",
                    "evidenceManifestResult",
                    "--exit-after-ms",
                    "formal_gate.py",
                    "--windows-zip-artifact",
                    "--linux-tgz-artifact",
                    ".sha256",
                    "ensure_native_platform",
                )
            )
            and "--ensure-placeholder" not in contract_tool,
            "contract tool must build, smoke, package, preflight, runtime-smoke, and reject non-native runs",
        ),
        check(
            "workflow uploads only verified final archives, checksums, and evidence manifests",
            bool(upload_artifact_blocks)
            and sorted(set(artifact_paths)) == sorted(ALLOWED_ARTIFACT_PATHS)
            and sorted(set(checksum_paths)) == sorted(ALLOWED_CHECKSUM_PATHS)
            and sorted(set(evidence_paths)) == sorted(ALLOWED_EVIDENCE_PATHS)
            and upload_paths
            and sorted(upload_paths)
            == sorted(
                (
                    REQUIRED_UPLOAD_PATH_REFERENCE,
                    REQUIRED_UPLOAD_CHECKSUM_REFERENCE,
                    REQUIRED_UPLOAD_EVIDENCE_REFERENCE,
                    *SOURCE_UPLOAD_PATHS,
                )
            )
            and not forbidden_uploads
            and "actions/upload-artifact@v4" in workflow
            and "if-no-files-found: error" in workflow,
            "upload-artifact must use matrix artifact/checksum/evidence paths and Python distribution paths, and matrix paths must be final zip/tar.gz plus .sha256 and .evidence.json allowlist entries",
        ),
        check(
            "workflow generates GitHub artifact attestations",
            len(attest_blocks) >= 2
            and "actions/attest@v4" in workflow
            and "artifact-metadata: write" in workflow
            and "attestations: write" in workflow
            and "id-token: write" in workflow
            and "subject-path: |" in workflow
            and REQUIRED_UPLOAD_PATH_REFERENCE in workflow
            and REQUIRED_UPLOAD_CHECKSUM_REFERENCE in workflow
            and REQUIRED_UPLOAD_EVIDENCE_REFERENCE in workflow
            and "dist/python/culvia-*.whl" in workflow
            and "dist/python/culvia-*.tar.gz" in workflow,
            "release packages, checksums, evidence manifests, wheels, and sdists must have GitHub Artifact Attestations",
        ),
        check(
            "workflow avoids raw cache artifacts",
            not raw_cache_blocks,
            "use setup-* dependency caches only; raw actions/cache can accidentally cache runtime state or workspace files",
        ),
        check(
            "workflow has no release bypasses or secrets",
            not bypasses,
            "Windows/Linux portable package workflow must not use secrets, continue-on-error, if: always(), set +e, or shell success bypasses",
        ),
    ]
    return checks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate the Windows/Linux desktop release workflow contract.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = result_payload(collect_checks(args.root))
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for item in payload["checks"]:
            print(("OK" if item["ok"] else "FAIL") + f" {item['name']}: {item['detail']}")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
