from __future__ import annotations

import plistlib
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Sequence

from tools import check_macos_artifact_preflight


def write_macho_executable(path: Path) -> None:
    path.write_bytes(b"\xcf\xfa\xed\xfe" + b"\x00" * 32)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def create_app_bundle(root: Path, *, name: str = "Culvia.app") -> Path:
    app = root / "macos" / name
    executable = app / "Contents" / "MacOS" / "culvia-desktop"
    backend = (
        app
        / "Contents"
        / "Resources"
        / "runtime"
        / "backend"
        / "aarch64-apple-darwin"
        / "culvia-server"
        / "culvia-server"
    )
    plist = app / "Contents" / "Info.plist"
    executable.parent.mkdir(parents=True, exist_ok=True)
    backend.parent.mkdir(parents=True, exist_ok=True)
    plist.parent.mkdir(parents=True, exist_ok=True)
    write_macho_executable(executable)
    write_macho_executable(backend)
    plist.write_bytes(
        plistlib.dumps(
            {
                "CFBundleExecutable": "culvia-desktop",
                "CFBundleIdentifier": "io.github.culvia.culvia",
                "CFBundleShortVersionString": "0.1.0",
                "CFBundlePackageType": "APPL",
            }
        )
    )
    return app


def create_dmg(root: Path) -> Path:
    dmg = root / "dmg" / "Culvia_0.1.0_aarch64.dmg"
    dmg.parent.mkdir(parents=True, exist_ok=True)
    dmg.write_bytes(b"not-a-real-dmg")
    return dmg


class MacosArtifactPreflightTests(unittest.TestCase):
    def test_missing_artifacts_are_optional_without_strict_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = check_macos_artifact_preflight.result_payload(
                check_macos_artifact_preflight.collect_checks(bundle_dir=Path(tmp), system="Linux")
            )

        self.assertTrue(payload["ok"])
        self.assertIn("macos app artifact exists", payload["skipped"])
        self.assertIn("macos dmg artifact exists", payload["skipped"])

    def test_missing_artifacts_fail_in_strict_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = check_macos_artifact_preflight.result_payload(
                check_macos_artifact_preflight.collect_checks(bundle_dir=Path(tmp), strict=True, system="Darwin")
            )

        self.assertFalse(payload["ok"])
        self.assertIn("macos app artifact exists", payload["failed"])
        self.assertIn("macos dmg artifact exists", payload["failed"])

    def test_app_bundle_structure_requires_info_plist_and_executable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "Broken.app"
            app.mkdir()
            payload = check_macos_artifact_preflight.result_payload(
                check_macos_artifact_preflight.collect_checks(app=app, strict=True, system="Darwin")
            )

        self.assertFalse(payload["ok"])
        self.assertIn("macos app bundle structure", payload["failed"])

    def test_multiple_discovered_artifacts_fail_without_explicit_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp)
            create_app_bundle(bundle_dir, name="One.app")
            create_app_bundle(bundle_dir / "archive", name="Two.app")
            payload = check_macos_artifact_preflight.result_payload(
                check_macos_artifact_preflight.collect_checks(bundle_dir=bundle_dir, system="Darwin")
            )

        self.assertFalse(payload["ok"])
        self.assertIn("macos app artifact is unique", payload["failed"])

    def test_temporary_rw_dmg_is_not_treated_as_final_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp)
            temporary_dmg = bundle_dir / "macos" / "rw.123.Culvia.dmg"
            temporary_dmg.parent.mkdir(parents=True)
            temporary_dmg.write_bytes(b"temporary")
            payload = check_macos_artifact_preflight.result_payload(
                check_macos_artifact_preflight.collect_checks(bundle_dir=bundle_dir, system="Linux")
            )

        self.assertTrue(payload["ok"])
        self.assertIn("macos dmg artifact exists", payload["skipped"])

    def test_darwin_artifact_checks_run_expected_commands(self) -> None:
        commands: list[tuple[str, ...]] = []

        def fake_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
            commands.append(tuple(command))
            if command[:2] == ("codesign", "-dv"):
                return subprocess.CompletedProcess(
                    list(command),
                    0,
                    stdout="",
                    stderr="Authority=Developer ID Application: Example\nTeamIdentifier=TEAMID\nRuntime Version=14.0",
                )
            return subprocess.CompletedProcess(list(command), 0, stdout="accepted", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp)
            app = create_app_bundle(bundle_dir)
            dmg = create_dmg(bundle_dir)
            payload = check_macos_artifact_preflight.result_payload(
                check_macos_artifact_preflight.collect_checks(
                    bundle_dir=bundle_dir,
                    app=app,
                    dmg=dmg,
                    strict=True,
                    runner=fake_runner,
                    system="Darwin",
                )
            )

        self.assertTrue(payload["ok"])
        joined = "\n".join(" ".join(command) for command in commands)
        self.assertIn("codesign --verify --deep --strict", joined)
        self.assertIn("codesign --verify --strict", joined)
        self.assertIn("codesign -dv --verbose=4", joined)
        self.assertIn("spctl --assess --type execute", joined)
        self.assertIn("hdiutil verify", joined)
        self.assertIn("xcrun stapler validate", joined)
        self.assertIn("spctl --assess --type open", joined)
        self.assertIn("lipo -archs", joined)

    def test_command_failure_fails_payload(self) -> None:
        def failing_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(list(command), 1, stdout="", stderr="rejected")

        with tempfile.TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp)
            app = create_app_bundle(bundle_dir)
            payload = check_macos_artifact_preflight.result_payload(
                check_macos_artifact_preflight.collect_checks(
                    bundle_dir=bundle_dir,
                    app=app,
                    strict=True,
                    runner=failing_runner,
                    system="Darwin",
                )
            )

        self.assertFalse(payload["ok"])
        self.assertIn("macos app codesign verification", payload["failed"])

    def test_ad_hoc_signature_details_fail_release_artifact_preflight(self) -> None:
        def fake_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
            if command[:2] == ("codesign", "-dv"):
                return subprocess.CompletedProcess(
                    list(command),
                    0,
                    stdout="",
                    stderr="Signature=adhoc\nTeamIdentifier=not set\nSealed Resources=none",
                )
            return subprocess.CompletedProcess(list(command), 0, stdout="accepted", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp)
            app = create_app_bundle(bundle_dir)
            dmg = create_dmg(bundle_dir)
            payload = check_macos_artifact_preflight.result_payload(
                check_macos_artifact_preflight.collect_checks(
                    bundle_dir=bundle_dir,
                    app=app,
                    dmg=dmg,
                    strict=True,
                    runner=fake_runner,
                    system="Darwin",
                )
            )

        self.assertFalse(payload["ok"])
        self.assertIn("macos app signature details", payload["failed"])
        self.assertIn("macos bundled backend signature details", payload["failed"])

    def test_ad_hoc_signature_details_are_optional_without_strict_mode(self) -> None:
        def fake_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
            if command[:2] == ("codesign", "-dv"):
                return subprocess.CompletedProcess(
                    list(command),
                    0,
                    stdout="",
                    stderr="Signature=adhoc\nTeamIdentifier=not set\nSealed Resources=none",
                )
            if command[:1] == ("spctl",) or command[:2] == ("xcrun", "stapler"):
                return subprocess.CompletedProcess(list(command), 1, stdout="", stderr="rejected")
            return subprocess.CompletedProcess(list(command), 0, stdout="accepted", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp)
            app = create_app_bundle(bundle_dir)
            dmg = create_dmg(bundle_dir)
            payload = check_macos_artifact_preflight.result_payload(
                check_macos_artifact_preflight.collect_checks(
                    bundle_dir=bundle_dir,
                    app=app,
                    dmg=dmg,
                    strict=False,
                    runner=fake_runner,
                    system="Darwin",
                )
            )

        self.assertTrue(payload["ok"])
        self.assertIn("macos app signature details", payload["skipped"])
        self.assertIn("macos bundled backend signature details", payload["skipped"])
        self.assertIn("macos app gatekeeper assessment", payload["skipped"])
        self.assertIn("macos dmg stapler validation", payload["skipped"])
        self.assertIn("macos dmg gatekeeper assessment", payload["skipped"])

    def test_strict_mode_fails_when_only_app_and_temporary_dmg_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle_dir = Path(tmp)
            create_app_bundle(bundle_dir)
            temporary_dmg = bundle_dir / "macos" / "rw.123.Culvia.dmg"
            temporary_dmg.write_bytes(b"temporary")
            payload = check_macos_artifact_preflight.result_payload(
                check_macos_artifact_preflight.collect_checks(bundle_dir=bundle_dir, strict=True, system="Linux")
            )

        self.assertFalse(payload["ok"])
        self.assertIn("macos dmg artifact exists", payload["failed"])


if __name__ == "__main__":
    unittest.main()
