from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from tools import build_windows_zip, check_portable_package_preflight


ROOT = Path(__file__).resolve().parents[1]
WINDOWS_TARGET = "x86_64-pc-windows-msvc"


def write_fake_pe(path: Path, *, machine: int = 0x8664) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pe_offset = 0x80
    payload = bytearray(pe_offset + 24)
    payload[:2] = b"MZ"
    payload[0x3C:0x40] = pe_offset.to_bytes(4, "little")
    payload[pe_offset : pe_offset + 4] = b"PE\0\0"
    payload[pe_offset + 4 : pe_offset + 6] = machine.to_bytes(2, "little")
    path.write_bytes(bytes(payload))
    return path


def fake_backend_path(temp: Path, target: str = WINDOWS_TARGET) -> Path:
    return temp / "runtime" / "backend" / target / "culvia-server" / "culvia-server.exe"


class WindowsZipReleaseTests(unittest.TestCase):
    def test_default_backend_binary_uses_windows_backend_naming_rule(self) -> None:
        path = build_windows_zip.default_backend_binary(WINDOWS_TARGET)

        self.assertTrue(
            path.as_posix().endswith("runtime/backend/x86_64-pc-windows-msvc/culvia-server/culvia-server.exe")
        )

    def test_default_desktop_binary_uses_windows_exe_name(self) -> None:
        path = build_windows_zip.default_desktop_binary("x86_64-pc-windows-msvc")

        self.assertTrue(str(path).endswith("target/release/culvia-desktop.exe"))

    def test_plan_requires_windows_pe_executables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            desktop = write_fake_pe(temp / "culvia-desktop.exe")
            backend = fake_backend_path(temp)
            backend.parent.mkdir(parents=True, exist_ok=True)
            backend.write_text("#!/bin/sh\n", encoding="utf-8")

            issues = build_windows_zip.validate_inputs(
                target=WINDOWS_TARGET,
                desktop_binary=desktop,
                backend_binary=backend,
                root=ROOT,
            )

        self.assertEqual(
            issues,
            [f"Windows backend binary must be a Windows PE executable: {backend}"],
        )

    def test_plan_rejects_wrong_machine_type_for_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            desktop = write_fake_pe(temp / "culvia-desktop.exe", machine=0xAA64)
            backend = write_fake_pe(fake_backend_path(temp))

            issues = build_windows_zip.validate_inputs(
                target=WINDOWS_TARGET,
                desktop_binary=desktop,
                backend_binary=backend,
                root=ROOT,
            )

        self.assertEqual(
            issues,
            ["Windows desktop shell binary machine must match x86_64-pc-windows-msvc: expected 0x8664, got 0xaa64"],
        )

    def test_stage_package_writes_exes_manifest_and_web_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            desktop = write_fake_pe(temp / "culvia-desktop.exe")
            backend = write_fake_pe(fake_backend_path(temp))
            package_root, manifest = build_windows_zip.stage_package(
                desktop_binary=desktop,
                backend_binary=backend,
                target=WINDOWS_TARGET,
                output_dir=temp / "dist",
                root=ROOT,
                config={"productName": "Culvia", "version": "0.1.0"},
            )

            launcher = package_root / "culvia-desktop.exe"
            bundled_backend = package_root / build_windows_zip.backend_package_binary(WINDOWS_TARGET)
            manifest_path = package_root / "share" / "culvia" / "manifest.json"

            self.assertTrue(launcher.exists())
            self.assertTrue(build_windows_zip.is_pe(launcher))
            self.assertTrue(bundled_backend.exists())
            self.assertTrue(build_windows_zip.is_pe(bundled_backend))
            self.assertTrue((package_root / "share" / "culvia" / "web" / "index.html").exists())
            self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8")), manifest)
            self.assertEqual(manifest["kind"], "culvia-windows-zip")
            self.assertEqual(manifest["launcher"], "culvia-desktop.exe")
            self.assertEqual(
                manifest["backend"]["path"],
                "runtime/backend/x86_64-pc-windows-msvc/culvia-server/culvia-server.exe",
            )
            self.assertEqual(manifest["backend"]["runtimeDir"], "runtime/backend/x86_64-pc-windows-msvc/culvia-server")
            self.assertTrue(manifest["backend"]["mustNotRequireUserPython"])
            self.assertNotIn(str(temp), json.dumps(manifest, ensure_ascii=False))

    def test_build_archive_contains_green_windows_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            desktop = write_fake_pe(temp / "culvia-desktop.exe")
            backend = write_fake_pe(fake_backend_path(temp))
            package_root, _manifest = build_windows_zip.stage_package(
                desktop_binary=desktop,
                backend_binary=backend,
                target=WINDOWS_TARGET,
                output_dir=temp / "dist",
                root=ROOT,
                config={"productName": "Culvia", "version": "0.1.0"},
            )
            archive = build_windows_zip.build_archive(
                package_root=package_root,
                output_dir=temp / "dist",
                version="0.1.0",
                target=WINDOWS_TARGET,
            )

            with zipfile.ZipFile(archive) as handle:
                names = set(handle.namelist())

        prefix = "culvia-0.1.0-windows-x86_64-pc-windows-msvc"
        self.assertIn(f"{prefix}/culvia-desktop.exe", names)
        self.assertIn(f"{prefix}/runtime/backend/x86_64-pc-windows-msvc/culvia-server/culvia-server.exe", names)
        self.assertIn(f"{prefix}/share/culvia/web/index.html", names)
        self.assertIn(f"{prefix}/share/culvia/manifest.json", names)
        self.assertIn(f"{prefix}/README.md", names)

    def test_lite_stage_package_omits_backend_and_web_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            desktop = write_fake_pe(temp / "culvia-desktop.exe")
            backend = write_fake_pe(fake_backend_path(temp))
            package_root, manifest = build_windows_zip.stage_package(
                desktop_binary=desktop,
                backend_binary=backend,
                target=WINDOWS_TARGET,
                output_dir=temp / "dist",
                root=ROOT,
                config={"productName": "Culvia", "version": "0.1.0"},
                runtime_profile="lite",
            )
            archive = build_windows_zip.build_archive(
                package_root=package_root,
                output_dir=temp / "dist",
                version="0.1.0",
                target=WINDOWS_TARGET,
                runtime_profile="lite",
            )

            with zipfile.ZipFile(archive) as handle:
                names = set(handle.namelist())

        prefix = "culvia-0.1.0-windows-lite-x86_64-pc-windows-msvc"
        self.assertEqual(manifest["kind"], "culvia-windows-lite-zip")
        self.assertEqual(manifest["runtimeProfile"], "lite")
        self.assertFalse(manifest["backend"]["bundled"])
        self.assertIn(f"{prefix}/culvia-desktop.exe", names)
        self.assertIn(f"{prefix}/share/culvia/manifest.json", names)
        self.assertNotIn(f"{prefix}/runtime/backend/x86_64-pc-windows-msvc/culvia-server/culvia-server.exe", names)
        self.assertNotIn(f"{prefix}/share/culvia/web/index.html", names)

    def test_lite_preflight_accepts_lite_archive_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            desktop = write_fake_pe(temp / "culvia-desktop.exe")
            backend = write_fake_pe(fake_backend_path(temp))
            package_root, _manifest = build_windows_zip.stage_package(
                desktop_binary=desktop,
                backend_binary=backend,
                target=WINDOWS_TARGET,
                output_dir=temp / "dist",
                root=ROOT,
                config={"productName": "Culvia", "version": "0.1.0"},
                runtime_profile="lite",
            )
            archive = build_windows_zip.build_archive(
                package_root=package_root,
                output_dir=temp / "dist",
                version="0.1.0",
                target=WINDOWS_TARGET,
                runtime_profile="lite",
            )

            payload = check_portable_package_preflight.result_payload(
                check_portable_package_preflight.collect_checks(windows_lite_zip=archive)
            )

        self.assertTrue(payload["ok"], payload["failed"])

    def test_main_check_plan_outputs_json_for_valid_fake_exes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            desktop = write_fake_pe(temp / "culvia-desktop.exe")
            backend = write_fake_pe(fake_backend_path(temp))
            stdout = StringIO()

            with redirect_stdout(stdout):
                result = build_windows_zip.main(
                    [
                        "--check-plan",
                        "--target",
                        WINDOWS_TARGET,
                        "--desktop-binary",
                        str(desktop),
                        "--backend-binary",
                        str(backend),
                        "--output-dir",
                        str(temp / "dist"),
                        "--json",
                    ]
                )

        self.assertEqual(result, 0)
        self.assertTrue(json.loads(stdout.getvalue())["ok"])


if __name__ == "__main__":
    unittest.main()
