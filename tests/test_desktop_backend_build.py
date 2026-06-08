from __future__ import annotations

import io
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "desktop" / "tauri" / "scripts" / "build-backend.py"


def load_tool_module():
    spec = importlib.util.spec_from_file_location("build_backend", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load build-backend.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DesktopBackendBuildTests(unittest.TestCase):
    def test_backend_binary_name_uses_target_suffix(self) -> None:
        tool = load_tool_module()

        self.assertEqual(
            tool.backend_binary_name("aarch64-apple-darwin", os_name="Darwin"),
            "culvia-server",
        )
        self.assertEqual(
            tool.backend_binary_name("x86_64-pc-windows-msvc", os_name="Windows"),
            "culvia-server.exe",
        )
        self.assertEqual(
            tool.backend_binary_name("x86_64-pc-windows-msvc", os_name="Darwin"),
            "culvia-server.exe",
        )
        self.assertEqual(
            tool.pyinstaller_name("x86_64-pc-windows-msvc"),
            "culvia-server",
        )

    def test_build_plan_uses_pyinstaller_entry_and_web_data(self) -> None:
        tool = load_tool_module()
        payload = tool.plan_payload(
            python=Path("/python"),
            target="aarch64-apple-darwin",
            workpath=Path("/tmp/work"),
            specpath=Path("/tmp/spec"),
            codesign_identity="-",
        )
        command = " ".join(payload["command"])

        self.assertEqual(payload["desktopResourceRoot"], "runtime/backend")
        self.assertEqual(payload["desktopResourcePath"], "runtime/backend/aarch64-apple-darwin/culvia-server")
        self.assertTrue(
            payload["binaryPath"].endswith("runtime/backend/aarch64-apple-darwin/culvia-server/culvia-server")
        )
        self.assertTrue(payload["runtimeDir"].endswith("runtime/backend/aarch64-apple-darwin/culvia-server"))
        self.assertEqual(payload["macosCodesignIdentity"], "-")
        self.assertTrue(str(payload["macosEntitlements"]).endswith("entitlements.mac.plist"))
        self.assertIn("PyInstaller", command)
        self.assertIn("--onedir", command)
        self.assertIn("--codesign-identity -", command)
        self.assertIn("--osx-entitlements-file", command)
        self.assertIn("entitlements.mac.plist", command)
        self.assertIn("server_entry.py", command)
        self.assertIn("share/culvia/web", command)
        self.assertIn("culvia_app", command)

    def test_macos_codesign_identity_defaults_to_ad_hoc_for_macos_targets(self) -> None:
        tool = load_tool_module()

        self.assertEqual(
            tool.resolve_macos_codesign_identity(target="aarch64-apple-darwin", env={}),
            "-",
        )
        self.assertEqual(
            tool.resolve_macos_codesign_identity(
                target="aarch64-apple-darwin",
                env={"CULVIA_MACOS_BACKEND_CODESIGN_IDENTITY": "Developer ID Application: Example"},
            ),
            "Developer ID Application: Example",
        )
        self.assertIsNone(tool.resolve_macos_codesign_identity(target="x86_64-pc-windows-msvc", env={}))

    def test_current_backend_plan_is_valid(self) -> None:
        tool = load_tool_module()

        self.assertEqual(tool.validate_plan(), [])

    def test_main_check_plan_outputs_json_without_building(self) -> None:
        tool = load_tool_module()

        result = tool.main(["--check-plan", "--target", "aarch64-apple-darwin", "--json"])

        self.assertEqual(result, 0)

    def test_main_build_prints_progress_to_stderr(self) -> None:
        tool = load_tool_module()
        with tempfile.TemporaryDirectory() as tmp:
            runtime_dir = Path(tmp) / "runtime" / "backend" / "aarch64-apple-darwin" / "culvia-server"
            binary_path = runtime_dir / "culvia-server"
            payload = {
                "binaryName": "culvia-server-test",
                "binaryPath": str(binary_path),
                "runtimeDir": str(runtime_dir),
                "target": "aarch64-apple-darwin",
                "webDataSource": str(ROOT / "web"),
                "webDataDestination": "share/culvia/web",
                "macosCodesignIdentity": "-",
                "command": ["pyinstaller"],
            }

            def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
                binary_path.parent.mkdir(parents=True, exist_ok=True)
                binary_path.write_text("binary", encoding="utf-8")
                return subprocess.CompletedProcess(["pyinstaller"], 0)

            stderr = io.StringIO()
            with (
                patch.object(tool, "validate_plan", return_value=[]),
                patch.object(tool, "plan_payload", return_value=payload),
                patch.object(tool.subprocess, "run", side_effect=fake_run),
                patch("sys.stderr", stderr),
            ):
                result = tool.main(["--build", "--target", "aarch64-apple-darwin", "--json"])

        self.assertEqual(result, 0)
        self.assertIn("[backend-build] 1/4 validate build plan", stderr.getvalue())
        self.assertIn("[backend-build] 3/4 run PyInstaller; live output follows", stderr.getvalue())
        self.assertIn("[backend-build] OK build culvia-server-test", stderr.getvalue())

    def test_ensure_placeholder_creates_compilation_stub(self) -> None:
        tool = load_tool_module()
        with self.subTest("payload"):
            with tempfile.TemporaryDirectory() as tmp:
                payload = {
                    "binaryPath": str(
                        Path(tmp) / "runtime" / "backend" / "test-target" / "culvia-server" / "culvia-server"
                    ),
                }
                path = Path(payload["binaryPath"])
                if path.exists():
                    path.unlink()
                self.assertEqual(tool.ensure_placeholder(payload), "created")
                self.assertTrue(path.exists())
                self.assertIn("backend placeholder", path.read_text(encoding="utf-8"))
                self.assertEqual(tool.ensure_placeholder(payload), "existing")


if __name__ == "__main__":
    unittest.main()
