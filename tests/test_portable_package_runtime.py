from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import build_linux_tgz, build_windows_zip, check_portable_package_runtime


ROOT = Path(__file__).resolve().parents[1]
WINDOWS_TARGET = "x86_64-pc-windows-msvc"
LINUX_TARGET = "x86_64-unknown-linux-gnu"


class FakeCompletedProcess:
    def __init__(self, returncode: int = 0, stdout: str = '{"ok": true}', stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


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


def write_fake_elf(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x7fELF" + b"\x02\x01\x01" + b"\0" * 64)
    path.chmod(0o755)
    return path


def fake_windows_backend_path(temp: Path, target: str = WINDOWS_TARGET) -> Path:
    return temp / "runtime" / "backend" / target / "culvia-server" / "culvia-server.exe"


def fake_linux_backend_path(temp: Path, target: str = LINUX_TARGET) -> Path:
    return temp / "runtime" / "backend" / target / "culvia-server" / "culvia-server"


def build_windows_archive(temp: Path) -> Path:
    desktop = write_fake_pe(temp / "culvia-desktop.exe")
    backend = write_fake_pe(fake_windows_backend_path(temp))
    package_root, _manifest = build_windows_zip.stage_package(
        desktop_binary=desktop,
        backend_binary=backend,
        target=WINDOWS_TARGET,
        output_dir=temp / "dist",
        root=ROOT,
        config={"productName": "Culvia", "version": "0.1.0"},
    )
    return build_windows_zip.build_archive(
        package_root=package_root,
        output_dir=temp / "dist",
        version="0.1.0",
        target=WINDOWS_TARGET,
    )


def build_linux_archive(temp: Path) -> Path:
    desktop = write_fake_elf(temp / "culvia-desktop")
    backend = write_fake_elf(fake_linux_backend_path(temp))
    package_root, _manifest = build_linux_tgz.stage_package(
        desktop_binary=desktop,
        backend_binary=backend,
        target=LINUX_TARGET,
        output_dir=temp / "dist",
        root=ROOT,
        config={"productName": "Culvia", "version": "0.1.0"},
    )
    return build_linux_tgz.build_archive(
        package_root=package_root,
        output_dir=temp / "dist",
        version="0.1.0",
        target=LINUX_TARGET,
    )


class PortablePackageRuntimeTests(unittest.TestCase):
    def test_windows_archive_metadata_smoke_passes_without_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = build_windows_archive(Path(tmp))

            payload = check_portable_package_runtime.result_payload(
                check_portable_package_runtime.collect_checks(windows_zip=archive, launch=False)
            )

        self.assertTrue(payload["ok"], payload["failed"])
        self.assertIn(
            "windows portable zip runtime manifest runtime paths resolve", [item["name"] for item in payload["checks"]]
        )

    def test_linux_archive_metadata_smoke_passes_without_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = build_linux_archive(Path(tmp))

            payload = check_portable_package_runtime.result_payload(
                check_portable_package_runtime.collect_checks(linux_tgz=archive, launch=False)
            )

        self.assertTrue(payload["ok"], payload["failed"])
        self.assertIn(
            "linux portable tgz runtime archive extracts safely", [item["name"] for item in payload["checks"]]
        )

    def test_runtime_smoke_rejects_non_native_runner_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = build_windows_archive(Path(tmp))

            with patch("tools.check_portable_package_runtime.native_platform_key", return_value="linux"):
                payload = check_portable_package_runtime.result_payload(
                    check_portable_package_runtime.collect_checks(windows_zip=archive, launch=True)
                )

        self.assertFalse(payload["ok"])
        self.assertIn("windows portable zip runtime runs on native target platform", payload["failed"])

    def test_runtime_smoke_runs_packaged_launcher_on_native_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = build_linux_archive(Path(tmp))

            with (
                patch("tools.check_portable_package_runtime.native_platform_key", return_value="linux"),
                patch(
                    "tools.check_portable_package_runtime.platform.machine",
                    return_value="x86_64",
                ),
                patch(
                    "tools.check_portable_package_runtime.run_launcher_workflow_smoke",
                    return_value=(True, "launcher smoke passed"),
                ) as run_launcher,
            ):
                payload = check_portable_package_runtime.result_payload(
                    check_portable_package_runtime.collect_checks(
                        linux_tgz=archive,
                        launch=True,
                        timeout=7,
                    )
                )

        self.assertTrue(payload["ok"], payload["failed"])
        self.assertIn(
            "linux portable tgz runtime launcher runs desktop fixture workflow",
            [item["name"] for item in payload["checks"]],
        )
        self.assertEqual(run_launcher.call_args.kwargs["timeout"], 7)
        self.assertTrue(str(run_launcher.call_args.kwargs["launcher"]).endswith("/bin/culvia"))

    def test_runtime_smoke_rejects_arch_mismatch_before_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = build_linux_archive(Path(tmp))

            with (
                patch("tools.check_portable_package_runtime.native_platform_key", return_value="linux"),
                patch(
                    "tools.check_portable_package_runtime.platform.machine",
                    return_value="arm64",
                ),
                patch("tools.check_portable_package_runtime.run_launcher_workflow_smoke") as run_launcher,
            ):
                payload = check_portable_package_runtime.result_payload(
                    check_portable_package_runtime.collect_checks(
                        linux_tgz=archive,
                        launch=True,
                    )
                )

        self.assertFalse(payload["ok"])
        self.assertIn("linux portable tgz runtime package target matches host architecture", payload["failed"])
        run_launcher.assert_not_called()

    def test_linux_launcher_command_uses_xvfb_without_display(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch(
                "tools.check_portable_package_runtime.shutil.which",
                return_value="/usr/bin/xvfb-run",
            ),
        ):
            command, issues = check_portable_package_runtime.launcher_command(
                Path("/pkg/bin/culvia"),
                spec=check_portable_package_runtime.LINUX_SPEC,
            )

        self.assertEqual(issues, [])
        self.assertEqual(command, ["/usr/bin/xvfb-run", "-a", "/pkg/bin/culvia"])

    def test_linux_launcher_command_requires_display_or_xvfb(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch(
                "tools.check_portable_package_runtime.shutil.which",
                return_value=None,
            ),
        ):
            command, issues = check_portable_package_runtime.launcher_command(
                Path("/pkg/bin/culvia"),
                spec=check_portable_package_runtime.LINUX_SPEC,
            )

        self.assertEqual(command, [])
        self.assertIn("requires DISPLAY or xvfb-run", issues[0])

    def test_launcher_environment_scrubs_llm_secrets(self) -> None:
        fixture = {
            "env": {
                "CULVIA_CACHE_PATH": "/fixture/state/culvia_scores.sqlite",
                "CULVIA_PHOTO_DIRS": "/fixture/photos",
            }
        }

        with patch.dict("os.environ", {"OPENAI_API_KEY": "real-key", "CULVIA_LLM_MODEL": "real-model"}):
            env = check_portable_package_runtime.launcher_environment(
                fixture,
                timeout=120,
                exit_after_ms=1500,
            )

        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("CULVIA_LLM_MODEL", env)

    def test_fixture_and_workflow_imports_are_lazy(self) -> None:
        source = (ROOT / "tools" / "check_portable_package_runtime.py").read_text(encoding="utf-8")
        top_level_import_section = source.split("WINDOWS_LABEL", 1)[0]

        self.assertNotIn("check_backend_workflow_smoke", top_level_import_section)
        self.assertNotIn("prepare_runtime_fixture", top_level_import_section)
        self.assertIn("from tools import check_backend_workflow_smoke", source)
        self.assertIn("from tools import prepare_runtime_fixture", source)


if __name__ == "__main__":
    unittest.main()
