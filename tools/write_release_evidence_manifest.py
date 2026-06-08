from __future__ import annotations

import argparse
import fnmatch
import json
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import write_release_checksum


SCHEMA = "culvia-release-evidence-v1"
MACOS_APP_SCHEMA = "culvia-macos-evidence-v1"
PLATFORM_RULES = {
    "windows": {
        "runner": "windows-latest",
        "target": "x86_64-pc-windows-msvc",
        "artifactName": "culvia-windows-x64",
        "artifactGlob": "dist/windows/*.zip",
        "archivePattern": "*/dist/windows/culvia-*-windows-x86_64-pc-windows-msvc.zip",
    },
    "linux": {
        "runner": "ubuntu-latest",
        "target": "x86_64-unknown-linux-gnu",
        "artifactName": "culvia-linux-x64",
        "artifactGlob": "dist/linux/*.tar.gz",
        "archivePattern": "*/dist/linux/culvia-*-linux-x86_64-unknown-linux-gnu.tar.gz",
    },
}
LITE_PLATFORM_RULES = {
    "windows": {
        "runner": "windows-latest",
        "target": "x86_64-pc-windows-msvc",
        "artifactName": "culvia-windows-lite-x64",
        "artifactGlob": "dist/windows-lite/*.zip",
        "archivePattern": "*/dist/windows-lite/culvia-*-windows-lite-x86_64-pc-windows-msvc.zip",
    },
    "linux": {
        "runner": "ubuntu-latest",
        "target": "x86_64-unknown-linux-gnu",
        "artifactName": "culvia-linux-lite-x64",
        "artifactGlob": "dist/linux-lite/*.tar.gz",
        "archivePattern": "*/dist/linux-lite/culvia-*-linux-lite-x86_64-unknown-linux-gnu.tar.gz",
    },
}
REQUIRED_RESULT_STEPS = (
    "install python desktop extras",
    "install desktop npm dependencies",
    "backend build plan",
    "backend build",
    "backend smoke",
    "desktop shell build",
    "portable package plan",
    "portable package build",
    "portable package artifact preflight",
    "portable package runtime verification",
    "formal package gate",
    "write release checksum",
)
LITE_REQUIRED_RESULT_STEPS = (
    "install python release extras",
    "install desktop npm dependencies",
    "desktop shell lite build",
    "lite package plan",
    "lite package build",
    "lite package artifact preflight",
    "write release checksum",
)
MACOS_APP_REQUIRED_STEPS = (
    "macos app preflight",
    "build macos backend",
    "build macos app and dmg",
    "macos artifact preflight",
    "macos app launch smoke",
    "write release checksum",
)
MACOS_APP_LITE_REQUIRED_STEPS = (
    "macos app preflight",
    "build macos lite app and dmg",
    "macos artifact preflight",
    "write release checksum",
)


def default_manifest_path(artifact: Path) -> Path:
    return Path(str(artifact) + ".evidence.json")


def read_contract_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("release contract JSON must contain an object")
    return payload


def result_by_name(payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    results = payload.get("results")
    if not isinstance(results, list):
        return {}
    by_name: dict[str, Mapping[str, Any]] = {}
    for item in results:
        if isinstance(item, Mapping):
            name = str(item.get("name") or "")
            if name:
                by_name[name] = item
    return by_name


def normalized_path(path: Path) -> str:
    return path.resolve().as_posix()


def same_path(left: Path, right: Path) -> bool:
    return left.resolve() == right.resolve()


def validate_contract_payload(payload: Mapping[str, Any], *, output: Path | None = None) -> list[str]:
    issues: list[str] = []
    platform = str(payload.get("platform") or "")
    profile = str(payload.get("profile") or "full")
    if platform not in {"windows", "linux"}:
        issues.append("release evidence platform must be windows or linux")
    rules = (LITE_PLATFORM_RULES if profile == "lite" else PLATFORM_RULES).get(platform)
    if rules is not None:
        for key in ("runner", "target", "artifactName", "artifactGlob"):
            if str(payload.get(key) or "") != str(rules[key]):
                issues.append(f"release evidence {key} must be {rules[key]}")
    if not payload.get("ok"):
        issues.append("release contract payload is not ok")

    results = result_by_name(payload)
    if not results:
        issues.append("release contract payload must include step results")
    required_steps = LITE_REQUIRED_RESULT_STEPS if profile == "lite" else REQUIRED_RESULT_STEPS
    missing_steps = [name for name in required_steps if name not in results]
    issues.extend(f"missing release contract step result: {name}" for name in missing_steps)
    failed_steps = [name for name, result in results.items() if not bool(result.get("ok"))]
    issues.extend(f"release contract step failed: {name}" for name in failed_steps)

    artifact = Path(str(payload.get("archive") or ""))
    checksum = Path(str(payload.get("checksum") or ""))
    expected_checksum = Path(str(artifact) + ".sha256")
    expected_manifest = default_manifest_path(artifact)
    declared_manifest = payload.get("evidenceManifest")
    if rules is not None and not fnmatch.fnmatch(normalized_path(artifact), str(rules["archivePattern"])):
        issues.append(f"release artifact path does not match {rules['archivePattern']}: {artifact}")
    if not same_path(checksum, expected_checksum):
        issues.append(f"release checksum path must be {expected_checksum}")
    if declared_manifest and not same_path(Path(str(declared_manifest)), expected_manifest):
        issues.append(f"release evidence manifest path must be {expected_manifest}")
    if output is not None and not same_path(output, expected_manifest):
        issues.append(f"release evidence output must be {expected_manifest}")
    manifest_path = expected_manifest if output is None else output
    if same_path(manifest_path, artifact) or same_path(manifest_path, checksum):
        issues.append("release evidence output must not overwrite the artifact or checksum")
    if not artifact.is_file():
        issues.append(f"missing release artifact: {artifact}")
    if not checksum.is_file():
        issues.append(f"missing release checksum: {checksum}")
    if artifact.is_file() and checksum.is_file():
        digest = write_release_checksum.sha256_file(artifact)
        expected = write_release_checksum.checksum_text(digest=digest, artifact=artifact)
        try:
            actual = checksum.read_text(encoding="utf-8")
        except OSError as exc:
            issues.append(f"cannot read release checksum: {exc}")
        else:
            if actual != expected:
                issues.append(f"release checksum mismatch: {checksum}")
    return issues


def manifest_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    artifact = Path(str(payload.get("archive") or "")).resolve()
    checksum = Path(str(payload.get("checksum") or "")).resolve()
    digest = write_release_checksum.sha256_file(artifact)
    results = result_by_name(payload)
    profile = str(payload.get("profile") or "full")
    required_steps = LITE_REQUIRED_RESULT_STEPS if profile == "lite" else REQUIRED_RESULT_STEPS
    return {
        "schema": SCHEMA,
        "createdAt": int(time.time()),
        "platform": str(payload.get("platform") or ""),
        "profile": profile,
        "runner": str(payload.get("runner") or ""),
        "target": str(payload.get("target") or ""),
        "artifact": str(artifact),
        "artifactName": artifact.name,
        "checksum": str(checksum),
        "checksumName": checksum.name,
        "sha256": digest,
        "sizeBytes": artifact.stat().st_size,
        "contractOk": bool(payload.get("ok")),
        "artifactNameForUpload": str(payload.get("artifactName") or ""),
        "artifactGlob": str(payload.get("artifactGlob") or ""),
        "requiredSteps": list(required_steps),
        "steps": [
            {
                "name": name,
                "ok": bool(results[name].get("ok")),
                "returncode": int(results[name].get("returncode") or 0),
                "seconds": float(results[name].get("seconds") or 0),
                "command": list(results[name].get("command") or []),
            }
            for name in required_steps
        ],
    }


def validate_macos_app_payload(payload: Mapping[str, Any], *, output: Path | None = None) -> list[str]:
    issues: list[str] = []
    if payload.get("platform") != "macos":
        issues.append("macos evidence platform must be macos")
    if not payload.get("ok"):
        issues.append("macos app payload is not ok")
    runtime_profile = str(payload.get("runtimeProfile") or "full")

    app = Path(str(payload.get("app") or ""))
    dmg = Path(str(payload.get("dmg") or payload.get("archive") or ""))
    checksum = Path(str(payload.get("checksum") or ""))
    expected_checksum = Path(str(dmg) + ".sha256")
    expected_manifest = default_manifest_path(dmg)
    if not app.is_dir() or app.suffix != ".app":
        issues.append(f"missing macos app bundle: {app}")
    if not dmg.is_file() or dmg.suffix.lower() != ".dmg":
        issues.append(f"missing macos dmg artifact: {dmg}")
    if not same_path(checksum, expected_checksum):
        issues.append(f"macos checksum path must be {expected_checksum}")
    if output is not None and not same_path(output, expected_manifest):
        issues.append(f"macos evidence output must be {expected_manifest}")
    manifest_path = expected_manifest if output is None else output
    if same_path(manifest_path, dmg) or same_path(manifest_path, checksum):
        issues.append("macos evidence output must not overwrite the artifact or checksum")
    if not checksum.is_file():
        issues.append(f"missing macos checksum: {checksum}")
    if dmg.is_file() and checksum.is_file():
        digest = write_release_checksum.sha256_file(dmg)
        expected = write_release_checksum.checksum_text(digest=digest, artifact=dmg)
        try:
            actual = checksum.read_text(encoding="utf-8")
        except OSError as exc:
            issues.append(f"cannot read macos checksum: {exc}")
        else:
            if actual != expected:
                issues.append(f"macos checksum mismatch: {checksum}")

    required_steps = MACOS_APP_LITE_REQUIRED_STEPS if runtime_profile == "lite" else MACOS_APP_REQUIRED_STEPS
    results = result_by_name(payload)
    missing_steps = [name for name in required_steps if name not in results]
    issues.extend(f"missing macos app step result: {name}" for name in missing_steps)
    failed_steps = [name for name, result in results.items() if name in required_steps and not bool(result.get("ok"))]
    issues.extend(f"macos app step failed: {name}" for name in failed_steps)
    return issues


def macos_app_manifest_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    app = Path(str(payload.get("app") or "")).resolve()
    dmg = Path(str(payload.get("dmg") or payload.get("archive") or "")).resolve()
    checksum = Path(str(payload.get("checksum") or "")).resolve()
    digest = write_release_checksum.sha256_file(dmg)
    results = result_by_name(payload)
    runtime_profile = str(payload.get("runtimeProfile") or "full")
    required_steps = MACOS_APP_LITE_REQUIRED_STEPS if runtime_profile == "lite" else MACOS_APP_REQUIRED_STEPS
    return {
        "schema": MACOS_APP_SCHEMA,
        "createdAt": int(time.time()),
        "platform": "macos",
        "runtimeProfile": runtime_profile,
        "runner": str(payload.get("runner") or "local-macos"),
        "target": str(payload.get("target") or "aarch64-apple-darwin"),
        "app": str(app),
        "appName": app.name,
        "artifact": str(dmg),
        "artifactName": dmg.name,
        "checksum": str(checksum),
        "checksumName": checksum.name,
        "sha256": digest,
        "sizeBytes": dmg.stat().st_size,
        "contractOk": bool(payload.get("ok")),
        "selectedIdentity": str(payload.get("selectedIdentity") or ""),
        "requiredSteps": list(required_steps),
        "steps": [
            {
                "name": name,
                "ok": bool(results[name].get("ok")),
                "returncode": int(results[name].get("returncode") or 0),
                "seconds": float(results[name].get("seconds") or 0),
                "command": list(results[name].get("command") or []),
            }
            for name in required_steps
        ],
    }


def write_macos_app_manifest(payload: Mapping[str, Any], *, output: Path | None = None) -> dict[str, Any]:
    dmg = Path(str(payload.get("dmg") or payload.get("archive") or ""))
    manifest_path = default_manifest_path(dmg) if output is None else output
    issues = validate_macos_app_payload(payload, output=output)
    if issues:
        return {
            "ok": False,
            "issues": issues,
            "manifestPath": str(manifest_path),
        }

    manifest = macos_app_manifest_payload(payload)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "issues": [],
        "manifestPath": str(manifest_path),
        "manifestName": manifest_path.name,
        "schema": MACOS_APP_SCHEMA,
        "platform": manifest["platform"],
        "artifact": manifest["artifact"],
        "checksum": manifest["checksum"],
        "sha256": manifest["sha256"],
        "stepCount": len(manifest["steps"]),
    }


def write_manifest_from_contract_payload(payload: Mapping[str, Any], *, output: Path | None = None) -> dict[str, Any]:
    artifact = Path(str(payload.get("archive") or ""))
    manifest_path = default_manifest_path(artifact) if output is None else output
    issues = validate_contract_payload(payload, output=output)
    if issues:
        return {
            "ok": False,
            "issues": issues,
            "manifestPath": str(manifest_path),
        }

    manifest = manifest_payload(payload)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "issues": [],
        "manifestPath": str(manifest_path),
        "manifestName": manifest_path.name,
        "schema": SCHEMA,
        "platform": manifest["platform"],
        "artifact": manifest["artifact"],
        "checksum": manifest["checksum"],
        "sha256": manifest["sha256"],
        "stepCount": len(manifest["steps"]),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write a release evidence manifest from a successful desktop release contract JSON payload."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--contract-json", type=Path, default=None, help="JSON output from desktop_release_contract.py --run --json."
    )
    source.add_argument("--macos-json", type=Path, default=None, help="JSON output from build_macos_app.py --json.")
    parser.add_argument(
        "--output", type=Path, default=None, help="Manifest output path. Must be <artifact>.evidence.json."
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.macos_json is not None:
            payload = read_contract_payload(args.macos_json)
            result = write_macos_app_manifest(payload, output=args.output)
        else:
            payload = read_contract_payload(args.contract_json)
            result = write_manifest_from_contract_payload(payload, output=args.output)
    except Exception as exc:  # noqa: BLE001 - CLI reports malformed evidence input.
        result = {"ok": False, "issues": [str(exc)], "manifestPath": str(args.output or "")}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(("OK" if result["ok"] else "FAIL") + f" release evidence manifest: {result.get('manifestPath', '')}")
        for issue in result.get("issues", []):
            print(f"FAIL {issue}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
