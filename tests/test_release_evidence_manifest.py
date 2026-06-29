from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import desktop_release_contract, write_release_checksum, write_release_evidence_manifest


def successful_contract_payload(root: Path) -> dict[str, object]:
    artifact = root / "dist" / "linux" / "culvia-0.1.0-linux-x86_64-unknown-linux-gnu.tar.gz"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"release artifact")
    checksum = Path(str(artifact) + ".sha256")
    checksum.write_text(
        write_release_checksum.checksum_text(
            digest=write_release_checksum.sha256_file(artifact),
            artifact=artifact,
        ),
        encoding="utf-8",
    )
    return {
        "ok": True,
        "platform": "linux",
        "runner": "ubuntu-latest",
        "target": "x86_64-unknown-linux-gnu",
        "archive": str(artifact),
        "checksum": str(checksum),
        "artifactName": "culvia-linux-x64",
        "artifactGlob": "dist/linux/*.tar.gz",
        "results": [
            {"name": name, "ok": True, "returncode": 0, "seconds": 0.01, "command": ["echo", name]}
            for name in write_release_evidence_manifest.REQUIRED_RESULT_STEPS
        ],
    }


def successful_lite_contract_payload(root: Path) -> dict[str, object]:
    artifact = root / "dist" / "linux-lite" / "culvia-0.1.0-linux-lite-x86_64-unknown-linux-gnu.tar.gz"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"lite release artifact")
    checksum = Path(str(artifact) + ".sha256")
    checksum.write_text(
        write_release_checksum.checksum_text(
            digest=write_release_checksum.sha256_file(artifact),
            artifact=artifact,
        ),
        encoding="utf-8",
    )
    return {
        "ok": True,
        "platform": "linux",
        "profile": "lite",
        "runner": "ubuntu-latest",
        "target": "x86_64-unknown-linux-gnu",
        "archive": str(artifact),
        "checksum": str(checksum),
        "artifactName": "culvia-linux-lite-x64",
        "artifactGlob": "dist/linux-lite/*.tar.gz",
        "results": [
            {"name": name, "ok": True, "returncode": 0, "seconds": 0.01, "command": ["echo", name]}
            for name in write_release_evidence_manifest.LITE_REQUIRED_RESULT_STEPS
        ],
    }


def successful_macos_app_payload(root: Path) -> dict[str, object]:
    app = root / "desktop" / "tauri" / "src-tauri" / "target" / "release" / "bundle" / "macos" / "Culvia.app"
    dmg = (
        root / "desktop" / "tauri" / "src-tauri" / "target" / "release" / "bundle" / "dmg" / "Culvia_0.1.0_aarch64.dmg"
    )
    app.mkdir(parents=True)
    dmg.parent.mkdir(parents=True, exist_ok=True)
    dmg.write_bytes(b"macos dmg")
    checksum = Path(str(dmg) + ".sha256")
    checksum.write_text(
        write_release_checksum.checksum_text(
            digest=write_release_checksum.sha256_file(dmg),
            artifact=dmg,
        ),
        encoding="utf-8",
    )
    return {
        "ok": True,
        "platform": "macos",
        "runner": "local-macos",
        "target": "arm64-apple-darwin",
        "app": str(app),
        "dmg": str(dmg),
        "archive": str(dmg),
        "checksum": str(checksum),
        "selectedIdentity": "-",
        "results": [
            {"name": name, "ok": True, "returncode": 0, "seconds": 0.01, "command": ["echo", name]}
            for name in write_release_evidence_manifest.MACOS_APP_REQUIRED_STEPS
        ],
    }


class ReleaseEvidenceManifestTests(unittest.TestCase):
    def test_write_manifest_from_successful_contract_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = successful_contract_payload(root)

            result = write_release_evidence_manifest.write_manifest_from_contract_payload(payload)

            self.assertTrue(result["ok"], result["issues"])
            manifest_path = Path(str(result["manifestPath"]))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema"], write_release_evidence_manifest.SCHEMA)
            self.assertEqual(manifest["platform"], "linux")
            self.assertEqual(manifest["artifactNameForUpload"], "culvia-linux-x64")
            self.assertEqual(len(manifest["steps"]), len(write_release_evidence_manifest.REQUIRED_RESULT_STEPS))
            self.assertEqual(manifest["steps"][-1]["name"], "write release checksum")

    def test_write_manifest_from_successful_lite_contract_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = successful_lite_contract_payload(root)

            result = write_release_evidence_manifest.write_manifest_from_contract_payload(payload)

            self.assertTrue(result["ok"], result["issues"])
            manifest_path = Path(str(result["manifestPath"]))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema"], write_release_evidence_manifest.SCHEMA)
            self.assertEqual(manifest["profile"], "lite")
            self.assertEqual(manifest["artifactNameForUpload"], "culvia-linux-lite-x64")
            self.assertEqual(len(manifest["steps"]), len(write_release_evidence_manifest.LITE_REQUIRED_RESULT_STEPS))
            self.assertEqual(manifest["steps"][-1]["name"], "write release checksum")

    def test_write_macos_app_manifest_from_successful_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = successful_macos_app_payload(root)

            result = write_release_evidence_manifest.write_macos_app_manifest(payload)

            self.assertTrue(result["ok"], result["issues"])
            manifest_path = Path(str(result["manifestPath"]))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema"], write_release_evidence_manifest.MACOS_APP_SCHEMA)
            self.assertEqual(manifest["platform"], "macos")
            self.assertEqual(manifest["artifactName"], "Culvia_0.1.0_aarch64.dmg")
            self.assertEqual(manifest["appName"], "Culvia.app")
            self.assertEqual(len(manifest["steps"]), len(write_release_evidence_manifest.MACOS_APP_REQUIRED_STEPS))
            self.assertEqual(manifest["steps"][-1]["name"], "write release checksum")

    def test_macos_app_manifest_rejects_missing_launch_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = successful_macos_app_payload(Path(tmp))
            payload["results"] = [
                item
                for item in payload["results"]  # type: ignore[index]
                if item["name"] != "macos app launch smoke"
            ]

            result = write_release_evidence_manifest.write_macos_app_manifest(payload)

            self.assertFalse(result["ok"])
            self.assertIn("missing macos app step result: macos app launch smoke", result["issues"])

    def test_manifest_rejects_missing_required_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = successful_contract_payload(Path(tmp))
            payload["results"] = list(payload["results"])[:-1]

            result = write_release_evidence_manifest.write_manifest_from_contract_payload(payload)

            self.assertFalse(result["ok"])
            self.assertIn("missing release contract step result: write release checksum", result["issues"])

    def test_manifest_rejects_output_that_would_overwrite_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = successful_contract_payload(Path(tmp))

            result = write_release_evidence_manifest.write_manifest_from_contract_payload(
                payload,
                output=Path(str(payload["archive"])),
            )

            self.assertFalse(result["ok"])
            self.assertTrue(any("must not overwrite" in issue for issue in result["issues"]))

    def test_manifest_rejects_wrong_platform_contract_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = successful_contract_payload(Path(tmp))
            payload["target"] = "x86_64-pc-windows-msvc"

            result = write_release_evidence_manifest.write_manifest_from_contract_payload(payload)

            self.assertFalse(result["ok"])
            self.assertIn("release evidence target must be x86_64-unknown-linux-gnu", result["issues"])

    def test_desktop_release_contract_writes_evidence_manifest_after_successful_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "dist" / "linux" / "culvia-0.1.0-linux-x86_64-unknown-linux-gnu.tar.gz"
            checksum = Path(str(artifact) + ".sha256")
            contract = desktop_release_contract.PlatformContract(
                key="linux",
                profile="full",
                host_system="Linux",
                runner="ubuntu-latest",
                target="x86_64-unknown-linux-gnu",
                archive=artifact,
                checksum=checksum,
                evidence_manifest=Path(str(artifact) + ".evidence.json"),
                artifact_glob="dist/linux/*.tar.gz",
                artifact_name="culvia-linux-x64",
                desktop_binary=root / "culvia-desktop",
                backend_binary=root / "culvia-server",
                artifact_flag="--linux-tgz-artifact",
                preflight_arg="--linux-tgz",
                package_build_tool=root / "tools" / "build_linux_tgz.py",
                runner_dependencies=(),
            )

            def fake_run_step(step: desktop_release_contract.ReleaseStep, *, root: Path = root) -> dict[str, object]:
                if step.name == "write release checksum":
                    artifact.parent.mkdir(parents=True, exist_ok=True)
                    artifact.write_bytes(b"release artifact")
                    checksum.write_text(
                        write_release_checksum.checksum_text(
                            digest=write_release_checksum.sha256_file(artifact),
                            artifact=artifact,
                        ),
                        encoding="utf-8",
                    )
                return {"name": step.name, "command": list(step.command), "returncode": 0, "seconds": 0.01, "ok": True}

            with (
                patch("tools.desktop_release_contract.native_platform_key", return_value="linux"),
                patch(
                    "tools.desktop_release_contract.run_step",
                    side_effect=fake_run_step,
                ),
            ):
                payload = desktop_release_contract.run_contract(contract, python=Path("/python"), root=root)

            self.assertTrue(payload["ok"], payload.get("evidenceManifestResult"))
            self.assertTrue(contract.evidence_manifest.is_file())
            self.assertEqual(payload["evidenceManifestResult"]["schema"], write_release_evidence_manifest.SCHEMA)


if __name__ == "__main__":
    unittest.main()
