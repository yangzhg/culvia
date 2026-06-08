from __future__ import annotations

import json
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from tools import build_linux_tgz, check_portable_package_preflight


ROOT = Path(__file__).resolve().parents[1]
LINUX_TARGET = "x86_64-unknown-linux-gnu"


def write_fake_elf(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x7fELF" + b"\x02\x01\x01" + b"\0" * 64)
    path.chmod(0o755)
    return path


def fake_backend_path(temp: Path, target: str = LINUX_TARGET) -> Path:
    return temp / "runtime" / "backend" / target / "culvia-server" / "culvia-server"


class LinuxTgzReleaseTests(unittest.TestCase):
    def test_default_backend_binary_uses_backend_build_naming_rule(self) -> None:
        path = build_linux_tgz.default_backend_binary(LINUX_TARGET)

        self.assertTrue(
            path.as_posix().endswith("runtime/backend/x86_64-unknown-linux-gnu/culvia-server/culvia-server")
        )

    def test_default_desktop_binary_prefers_target_release_path(self) -> None:
        path = build_linux_tgz.default_desktop_binary("x86_64-unknown-linux-gnu")

        self.assertTrue(str(path).endswith("target/release/culvia-desktop"))

    def test_plan_requires_executable_linux_elf_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            desktop = write_fake_elf(temp / "culvia-desktop")
            backend = fake_backend_path(temp)
            backend.parent.mkdir(parents=True, exist_ok=True)
            backend.write_text("#!/bin/sh\n", encoding="utf-8")
            backend.chmod(0o755)

            issues = build_linux_tgz.validate_inputs(desktop_binary=desktop, backend_binary=backend, root=ROOT)

        self.assertEqual(
            issues,
            [f"Linux backend binary must be a Linux ELF executable: {backend}"],
        )

    def test_stage_package_writes_launcher_manifest_and_web_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            desktop = write_fake_elf(temp / "culvia-desktop")
            backend = write_fake_elf(fake_backend_path(temp))
            package_root, manifest = build_linux_tgz.stage_package(
                desktop_binary=desktop,
                backend_binary=backend,
                target=LINUX_TARGET,
                output_dir=temp / "dist",
                root=ROOT,
                config={"productName": "Culvia", "version": "0.1.0"},
            )

            launcher = package_root / "bin" / "culvia"
            bundled_desktop = package_root / "bin" / "culvia-desktop"
            bundled_backend = package_root / build_linux_tgz.backend_package_binary(LINUX_TARGET)
            manifest_path = package_root / "share" / "culvia" / "manifest.json"

            self.assertTrue(launcher.exists())
            self.assertIn("CULVIA_WEB_DIR", launcher.read_text(encoding="utf-8"))
            self.assertIn("CULVIA_BACKEND_PATH", launcher.read_text(encoding="utf-8"))
            self.assertIn("culvia-desktop", launcher.read_text(encoding="utf-8"))
            self.assertTrue(bundled_desktop.exists())
            self.assertTrue(build_linux_tgz.is_executable(bundled_desktop))
            self.assertTrue(bundled_backend.exists())
            self.assertTrue(build_linux_tgz.is_executable(bundled_backend))
            self.assertTrue((package_root / "share" / "culvia" / "web" / "index.html").exists())
            self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8")), manifest)
            self.assertEqual(manifest["kind"], "culvia-linux-tgz")
            self.assertEqual(manifest["desktop"]["path"], "bin/culvia-desktop")
            self.assertEqual(
                manifest["backend"]["path"],
                "runtime/backend/x86_64-unknown-linux-gnu/culvia-server/culvia-server",
            )
            self.assertEqual(
                manifest["backend"]["runtimeDir"], "runtime/backend/x86_64-unknown-linux-gnu/culvia-server"
            )
            self.assertTrue(manifest["backend"]["mustNotRequireUserPython"])
            self.assertEqual(manifest["web"]["env"], "CULVIA_WEB_DIR")
            self.assertNotIn(str(temp), json.dumps(manifest, ensure_ascii=False))

    def test_build_archive_contains_stable_release_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            desktop = write_fake_elf(temp / "culvia-desktop")
            backend = write_fake_elf(fake_backend_path(temp))
            package_root, _manifest = build_linux_tgz.stage_package(
                desktop_binary=desktop,
                backend_binary=backend,
                target=LINUX_TARGET,
                output_dir=temp / "dist",
                root=ROOT,
                config={"productName": "Culvia", "version": "0.1.0"},
            )
            archive = build_linux_tgz.build_archive(
                package_root=package_root,
                output_dir=temp / "dist",
                version="0.1.0",
                target=LINUX_TARGET,
            )

            with tarfile.open(archive, "r:gz") as handle:
                names = set(handle.getnames())

        prefix = "culvia-0.1.0-linux-x86_64-unknown-linux-gnu"
        self.assertIn(f"{prefix}/bin/culvia", names)
        self.assertIn(f"{prefix}/bin/culvia-desktop", names)
        self.assertIn(f"{prefix}/runtime/backend/x86_64-unknown-linux-gnu/culvia-server/culvia-server", names)
        self.assertIn(f"{prefix}/share/culvia/web/index.html", names)
        self.assertIn(f"{prefix}/share/culvia/manifest.json", names)
        self.assertIn(f"{prefix}/README.md", names)

    def test_lite_stage_package_omits_backend_and_web_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            desktop = write_fake_elf(temp / "culvia-desktop")
            backend = write_fake_elf(fake_backend_path(temp))
            package_root, manifest = build_linux_tgz.stage_package(
                desktop_binary=desktop,
                backend_binary=backend,
                target=LINUX_TARGET,
                output_dir=temp / "dist",
                root=ROOT,
                config={"productName": "Culvia", "version": "0.1.0"},
                runtime_profile="lite",
            )
            archive = build_linux_tgz.build_archive(
                package_root=package_root,
                output_dir=temp / "dist",
                version="0.1.0",
                target=LINUX_TARGET,
                runtime_profile="lite",
            )

            with tarfile.open(archive, "r:gz") as handle:
                names = set(handle.getnames())
            launcher = (package_root / "bin" / "culvia").read_text(encoding="utf-8")

        prefix = "culvia-0.1.0-linux-lite-x86_64-unknown-linux-gnu"
        self.assertEqual(manifest["kind"], "culvia-linux-lite-tgz")
        self.assertEqual(manifest["runtimeProfile"], "lite")
        self.assertFalse(manifest["backend"]["bundled"])
        self.assertIn("CULVIA_DESKTOP_RUNTIME_MODE", launcher)
        self.assertNotIn("CULVIA_BACKEND_PATH", launcher)
        self.assertIn(f"{prefix}/bin/culvia", names)
        self.assertIn(f"{prefix}/bin/culvia-desktop", names)
        self.assertIn(f"{prefix}/share/culvia/manifest.json", names)
        self.assertNotIn(f"{prefix}/runtime/backend/x86_64-unknown-linux-gnu/culvia-server/culvia-server", names)
        self.assertNotIn(f"{prefix}/share/culvia/web/index.html", names)

    def test_lite_preflight_accepts_lite_archive_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            desktop = write_fake_elf(temp / "culvia-desktop")
            backend = write_fake_elf(fake_backend_path(temp))
            package_root, _manifest = build_linux_tgz.stage_package(
                desktop_binary=desktop,
                backend_binary=backend,
                target=LINUX_TARGET,
                output_dir=temp / "dist",
                root=ROOT,
                config={"productName": "Culvia", "version": "0.1.0"},
                runtime_profile="lite",
            )
            archive = build_linux_tgz.build_archive(
                package_root=package_root,
                output_dir=temp / "dist",
                version="0.1.0",
                target=LINUX_TARGET,
                runtime_profile="lite",
            )

            payload = check_portable_package_preflight.result_payload(
                check_portable_package_preflight.collect_checks(linux_lite_tgz=archive)
            )

        self.assertTrue(payload["ok"], payload["failed"])

    def test_main_check_plan_outputs_json_for_valid_fake_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            desktop = write_fake_elf(temp / "culvia-desktop")
            backend = write_fake_elf(fake_backend_path(temp))
            stdout = StringIO()

            with redirect_stdout(stdout):
                result = build_linux_tgz.main(
                    [
                        "--check-plan",
                        "--target",
                        LINUX_TARGET,
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
