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
    "dist/macos-lite/*-lite.dmg",
    "dist/windows/culvia-*-windows-x86_64-pc-windows-msvc.zip",
    "dist/windows-lite/culvia-*-windows-lite-x86_64-pc-windows-msvc.zip",
    "dist/linux/culvia-*-linux-x86_64-unknown-linux-gnu.tar.gz",
    "dist/linux-lite/culvia-*-linux-lite-x86_64-unknown-linux-gnu.tar.gz",
)
ALLOWED_CHECKSUM_PATHS = tuple(f"{path}.sha256" for path in ALLOWED_ARTIFACT_PATHS)
ALLOWED_EVIDENCE_PATHS = tuple(f"{path}.evidence.json" for path in ALLOWED_ARTIFACT_PATHS)
FORBIDDEN_WORKFLOW_PATTERNS = (
    (r"\$\{\{\s*secrets\.", "secrets context"),
    (r"continue-on-error\s*:\s*(true|\$\{\{)", "continue-on-error bypass"),
    (r"\|\|\s*true\b", "shell success bypass"),
    (r"\bif\s*:\s*always\(\)", "always upload/run bypass"),
    (r"\bset\s+\+e\b", "disabled shell error exit"),
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


def workflow_dispatch_input_block(workflow: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^      {re.escape(name)}:\n.*?(?=^      [a-zA-Z_][a-zA-Z0-9_-]*:\n|^  push:\n)",
        workflow,
    )
    return match.group(0) if match else ""


def workflow_step_block(workflow: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^      - name: {re.escape(name)}\n.*?(?=^      - name: |^  [a-zA-Z_][a-zA-Z0-9_-]*:\n|\Z)",
        workflow,
    )
    return match.group(0) if match else ""


def collect_checks(root: Path = ROOT) -> list[CheckResult]:
    workflow = read_optional(root, WORKFLOW_PATH)
    platform_input = workflow_dispatch_input_block(workflow, "platform")
    profile_input = workflow_dispatch_input_block(workflow, "profile")
    lite_runtime_step = workflow_step_block(workflow, "Verify clean Desktop Lite runtime wheel")
    intel_model_runtime_step = workflow_step_block(workflow, "Verify macOS Intel model runtime contract")
    publish_step = workflow_step_block(workflow, "Publish assets to GitHub Release")
    upload_paths = upload_artifact_paths(workflow)
    artifact_paths = matrix_artifact_paths(workflow)
    checksum_paths = matrix_checksum_paths(workflow)
    evidence_paths = matrix_evidence_paths(workflow)
    upload_artifact_blocks = action_blocks(workflow, "actions/upload-artifact")
    attest_blocks = action_blocks(workflow, ATTEST_ACTION)
    raw_cache_blocks = action_blocks(workflow, RAW_CACHE_ACTION)
    bypasses = forbidden_bypass_matches(workflow)
    checks = [
        check("desktop release workflow exists", bool(workflow), WORKFLOW_PATH),
        check(
            "workflow is manually triggered with read-only permissions",
            "workflow_dispatch:" in workflow and "permissions:" in workflow and "contents: read" in workflow,
            "workflow_dispatch and contents: read are required",
        ),
        check(
            "workflow serializes runs by target release tag or ref",
            "group: desktop-release-${{ github.event_name == 'workflow_dispatch' && inputs.release_tag || github.ref_name }}"
            in workflow
            and "cancel-in-progress: false" in workflow,
            "manual release_tag must take priority over ref_name and same-target runs must queue instead of canceling",
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
            "workflow manual publish defaults to complete release selection",
            "default: all" in platform_input
            and "default: release" in profile_input
            and "- release" in profile_input
            and "|| 'release'" in workflow
            and 'selected_profile = os.environ["INPUT_PROFILE"] or "release"' in workflow,
            "manual runs must expose and default to platform=all with profile=release",
        ),
        check(
            "workflow release profile selects complete supported matrix",
            'if selected_profile == "release":' in workflow
            and 'return job["profile"] == "lite" or job["platform"] in {"macos", "windows"}' in workflow,
            "release must include macOS Full/Lite arm64/x64, Windows Full/Lite x64, and Linux Lite x64 while excluding Linux Full",
        ),
        check(
            "workflow manual publish rejects incomplete release selection",
            "manual_publish = (" in workflow
            and 'event_name == "workflow_dispatch" and os.environ["INPUT_PUBLISH_RELEASE"].lower() == "true"'
            in workflow
            and 'if manual_publish and (selected_platform != "all" or selected_profile != "release"):' in workflow
            and "publish_release requires platform=all and profile=release." in workflow,
            "publish_release must reject manual runs unless platform=all and profile=release",
        ),
        check(
            "workflow delegates release steps to local contract tool",
            f"{CONTRACT_TOOL_PATH} --platform" in workflow
            and "--check-plan --json" in workflow
            and "--run --json" in workflow,
            "workflow must call the local desktop release contract plan and run modes",
        ),
        check(
            "workflow verifies a clean dependency-resolved Desktop Lite runtime wheel",
            bool(lite_runtime_step)
            and "python -m venv" in lite_runtime_step
            and 'pip install "${runtime_wheels[0]}[desktop-runtime]"' in lite_runtime_step
            and "-m pip check" in lite_runtime_step
            and "-m culvia.runtime_manager doctor" in lite_runtime_step
            and "--profile desktop-lite" in lite_runtime_step
            and 'report.get("serviceVersion") != expected_version' in lite_runtime_step
            and 'report.get("runtimeContract") != expected_contract' in lite_runtime_step
            and 'report.get("profile", {}).get("required_modules") != expected_modules' in lite_runtime_step
            and 'report.get("missingModules")' in lite_runtime_step
            and "import inspect, keyring, safetensors, torch" in lite_runtime_step
            and "inspect.signature(torch.load).parameters" in lite_runtime_step
            and "--no-deps" not in lite_runtime_step,
            "the source job must install the built wheel[desktop-runtime] with dependencies in a fresh venv and verify service version, shell runtime contract, required modules, safe model loading, and the extra dependency",
        ),
        check(
            "workflow verifies the macOS Intel model runtime contract",
            bool(intel_model_runtime_step)
            and "matrix.platform == 'macos'" in intel_model_runtime_step
            and "matrix.arch == 'x64'" in intel_model_runtime_step
            and "matrix.profile == 'full'" in intel_model_runtime_step
            and "python -m pip check" in intel_model_runtime_step
            and '"torch": "2.2.2"' in intel_model_runtime_step
            and '"torchvision": "0.17.2"' in intel_model_runtime_step
            and '"transformers": "4.38.2"' in intel_model_runtime_step
            and '"safetensors": "0.4.3"' in intel_model_runtime_step
            and "numpy.__version__" in intel_model_runtime_step
            and "inspect.signature(torch.load).parameters" in intel_model_runtime_step
            and 'getattr(vision_model, "vision_model", vision_model)' in intel_model_runtime_step
            and "safe_serialization=True" in intel_model_runtime_step
            and "CLIPModel.from_pretrained" in intel_model_runtime_step
            and "use_safetensors=True" in intel_model_runtime_step,
            "the macOS Intel full-package runner must import the exact supported dependency set and round-trip a CLIP safetensors/config artifact",
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
            and "if-no-files-found: error" in workflow,
            "upload-artifact must use final archive/checksum/evidence allowlists, including an explicit -lite basename for staged macOS Lite DMGs and sidecars",
        ),
        check(
            "workflow rejects duplicate release asset basenames before upload",
            bool(publish_step)
            and "from collections import Counter" in publish_step
            and "basenames = [Path(path).name for path in sys.argv[1:]]" in publish_step
            and "if count > 1" in publish_step
            and "if duplicates:" in publish_step
            and "Release asset basenames must be unique:" in publish_step
            and 0
            <= publish_step.find("Release asset basenames must be unique:")
            < publish_step.find('gh release upload --repo "${GITHUB_REPOSITORY}"'),
            "all downloaded assets must have unique basenames before gh release upload",
        ),
        check(
            "workflow generates GitHub artifact attestations",
            len(attest_blocks) >= 2
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
            "workflow enforces synchronized release tag",
            workflow.count('python tools/check_version_sync.py --tag "${{ needs.select.outputs.release_ref }}"') >= 2,
            "desktop and Python distribution jobs must reject a release tag that differs from synchronized package versions",
        ),
        check(
            "workflow creates immutable release with explicit repository",
            all(
                text in workflow
                for text in (
                    'gh release view --repo "${GITHUB_REPOSITORY}" "${RELEASE_TAG}" --json isDraft',
                    'gh release create --repo "${GITHUB_REPOSITORY}" "${RELEASE_TAG}" --verify-tag --draft',
                    'gh release delete --repo "${GITHUB_REPOSITORY}" "${RELEASE_TAG}" --yes',
                    'gh release upload --repo "${GITHUB_REPOSITORY}" "${RELEASE_TAG}"',
                    'gh release edit --repo "${GITHUB_REPOSITORY}" "${RELEASE_TAG}" --draft=false',
                )
            )
            and "Published Release ${RELEASE_TAG} already exists; refusing to replace" in workflow
            and 'expected_runtime_wheel="culvia-${release_version}-py3-none-any.whl"' in workflow
            and "--clobber" not in workflow,
            "publish job must pass --repo, require the matching Lite runtime wheel, replace only an incomplete draft on retry, reject an existing published release, and never clobber assets",
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
