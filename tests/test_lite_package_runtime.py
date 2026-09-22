from __future__ import annotations

import io
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tests.test_portable_package_preflight import write_fake_elf, write_fake_pe
from tools import build_linux_tgz, build_windows_zip, check_lite_package_runtime as smoke, write_release_checksum


def make_wheel(root: Path, *, version: str = "0.2.0", name: str = "culvia") -> Path:
    wheel = root / f"culvia-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(f"culvia-{version}.dist-info/METADATA", f"Name: {name}\nVersion: {version}\n")
    return wheel


def make_package(root: Path, package_platform: str, *, version: str = "0.2.0", profile: str = "lite") -> Path:
    windows = package_platform == "windows"
    builder = build_windows_zip if windows else build_linux_tgz
    binary = write_fake_pe(root / "culvia-desktop.exe") if windows else write_fake_elf(root / "culvia-desktop")
    target = "x86_64-pc-windows-msvc" if windows else "x86_64-unknown-linux-gnu"
    package, _ = builder.stage_package(
        desktop_binary=binary,
        backend_binary=None,
        target=target,
        output_dir=root / "dist",
        config={"productName": "Culvia", "version": version},
        runtime_profile=profile,
    )
    artifact = builder.build_archive(
        package_root=package, output_dir=root / "dist", version=version, target=target, runtime_profile=profile
    )
    write_release_checksum.write_checksum(artifact=artifact)
    return artifact


class LitePackageRuntimeTests(unittest.TestCase):
    def test_wheel_metadata_must_identify_the_exact_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wheel = make_wheel(root)
            self.assertEqual(smoke.wheel_version(wheel), "0.2.0")
            make_wheel(root, name="unrelated")
            with self.assertRaisesRegex(ValueError, "Culvia universal wheel"):
                smoke.wheel_version(wheel)
            make_wheel(root)
            renamed = wheel.with_name("culvia-9.0.0-py3-none-any.whl")
            wheel.rename(renamed)
            with self.assertRaisesRegex(ValueError, "Culvia universal wheel"):
                smoke.wheel_version(renamed)
            wheel = make_wheel(root)
            with zipfile.ZipFile(wheel, "a") as archive:
                archive.writestr("other.dist-info/METADATA", "Name: other\nVersion: 1\n")
            with self.assertRaisesRegex(ValueError, "exactly one"):
                smoke.wheel_version(wheel)

    def test_native_portable_packages_pass_exact_launcher_wheel_and_target_to_smoke(self) -> None:
        for package_platform, system in (("windows", "Windows"), ("linux", "Linux")):
            with self.subTest(platform=package_platform), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                wheel = make_wheel(root)
                artifact = make_package(root, package_platform)

                def verify(**kwargs):
                    self.assertTrue(kwargs["launcher"].is_file())
                    self.assertEqual(kwargs["wheel"], wheel)
                    self.assertEqual(kwargs["python"], Path(sys.executable))
                    self.assertEqual(kwargs["expected_version"], "0.2.0")
                    self.assertEqual(kwargs["expected_target"], f"x86_64-{smoke.TARGET_SUFFIXES[package_platform]}")
                    self.assertNotEqual(kwargs["work_dir"], smoke.ROOT)
                    self.assertEqual(list(kwargs["work_dir"].iterdir()), [])
                    return {"ok": True, "checks": [], "firstLaunch": {"ok": True}, "reuseLaunch": {"ok": True}}

                with (
                    patch.object(smoke.platform, "system", return_value=system),
                    patch.object(smoke.check_portable_package_runtime, "native_arch_key", return_value="x86_64"),
                    patch("tools.lite_runtime_smoke.run_lite_smoke", side_effect=verify) as launch,
                ):
                    report = smoke.verify_package(
                        artifact=artifact, package_platform=package_platform, wheel=wheel, python=Path(sys.executable)
                    )
                self.assertTrue(report["ok"], report)
                self.assertEqual(launch.call_count, 1)
                self.assertEqual(report["artifact"], smoke.file_evidence(artifact))
                self.assertEqual(report["wheel"], smoke.file_evidence(wheel))

    def test_wrong_version_architecture_or_checksum_never_launches(self) -> None:
        for problem in ("version", "architecture", "checksum", "missing checksum", "platform"):
            with self.subTest(problem=problem), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                wheel = make_wheel(root)
                artifact = make_package(root, "linux", version="0.3.0" if problem == "version" else "0.2.0")
                sidecar = Path(str(artifact) + ".sha256")
                if problem == "checksum":
                    sidecar.write_text("bad checksum\n", encoding="utf-8")
                elif problem == "missing checksum":
                    sidecar.unlink()
                with (
                    patch.object(
                        smoke.platform, "system", return_value="Windows" if problem == "platform" else "Linux"
                    ),
                    patch.object(
                        smoke.check_portable_package_runtime,
                        "native_arch_key",
                        return_value="aarch64" if problem == "architecture" else "x86_64",
                    ),
                    patch("tools.lite_runtime_smoke.run_lite_smoke") as launch,
                ):
                    report = smoke.verify_package(
                        artifact=artifact, package_platform="linux", wheel=wheel, python=Path(sys.executable)
                    )
                self.assertFalse(report["ok"], report)
                self.assertFalse(report["firstLaunch"]["ok"])
                launch.assert_not_called()

    def test_incomplete_or_failed_launch_cannot_be_successful_evidence(self) -> None:
        for result in (
            {"ok": False, "checks": [], "firstLaunch": {"ok": False}, "reuseLaunch": {"ok": False}},
            {"ok": True, "checks": [], "firstLaunch": {"ok": True}},
            {
                "ok": True,
                "checks": [{"name": "bad provenance", "ok": False}],
                "firstLaunch": {"ok": True},
                "reuseLaunch": {"ok": True},
            },
        ):
            with self.subTest(result=result), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                wheel = make_wheel(root)
                artifact = make_package(root, "linux")
                with (
                    patch.object(smoke.platform, "system", return_value="Linux"),
                    patch.object(smoke.check_portable_package_runtime, "native_arch_key", return_value="x86_64"),
                    patch("tools.lite_runtime_smoke.run_lite_smoke", return_value=result),
                ):
                    report = smoke.verify_package(
                        artifact=artifact, package_platform="linux", wheel=wheel, python=Path(sys.executable)
                    )
                self.assertFalse(report["ok"], report)

    def test_dmg_is_read_only_and_detached_when_copy_or_launch_fails(self) -> None:
        for failure in ("copy", "launch"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                commands = []

                def command(argv):
                    commands.append(argv)
                    if argv[:2] == ["hdiutil", "attach"]:
                        (root / "mount" / "Culvia.app").mkdir()
                        self.assertIn("-readonly", argv)
                    if argv[0] == "ditto" and failure == "copy":
                        raise subprocess.CalledProcessError(1, argv)
                    return subprocess.CompletedProcess(argv, 0, "", "")

                with patch.object(smoke, "run_command", side_effect=command):
                    with self.assertRaises((RuntimeError, subprocess.CalledProcessError)):
                        with smoke.unpack_macos_dmg(root / "candidate.dmg", root):
                            raise RuntimeError("launch failed")
                self.assertEqual(commands[-1], ["hdiutil", "detach", str(root / "mount")])

    def test_dmg_rejects_ambiguous_apps_and_detaches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def command(argv):
                if argv[:2] == ["hdiutil", "attach"]:
                    for name in ("One.app", "Two.app"):
                        (root / "mount" / name).mkdir()
                return subprocess.CompletedProcess(argv, 0, "", "")

            with patch.object(smoke, "run_command", side_effect=command) as run:
                with self.assertRaisesRegex(ValueError, "exactly one"):
                    with smoke.unpack_macos_dmg(root / "candidate.dmg", root):
                        self.fail("ambiguous DMG must not launch")
                self.assertEqual(run.call_args.args[0][:2], ["hdiutil", "detach"])

    def test_busy_dmg_detach_retries_then_forces_only_owned_mount(self) -> None:
        mount = Path("/tmp/culvia-smoke-test/mount")
        busy = subprocess.CalledProcessError(16, ["hdiutil", "detach", str(mount)])
        with (
            patch.object(smoke, "run_command", side_effect=[busy, busy, busy, None]) as run,
            patch.object(smoke.time, "sleep"),
        ):
            smoke.detach_dmg(mount)
        self.assertEqual(run.call_count, 4)
        self.assertEqual(run.call_args.args[0], ["hdiutil", "detach", "-force", str(mount)])

    def test_workspace_does_not_delete_a_still_mounted_dmg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp)
            checks = []
            with (
                patch.object(smoke.tempfile, "mkdtemp", return_value=str(destination)),
                patch.object(smoke.platform, "system", return_value="Darwin"),
                patch.object(Path, "is_mount", return_value=True),
                patch.object(smoke.check_portable_package_runtime, "remove_tree_with_retries") as remove,
            ):
                with smoke.package_workspace(checks):
                    pass
                remove.assert_not_called()
            self.assertFalse(checks[-1]["ok"])
            self.assertIn("retained", checks[-1]["detail"])

    def test_portable_workspace_cleanup_does_not_probe_dmg_mounts(self) -> None:
        for system in ("Windows", "Linux"):
            with self.subTest(system=system), tempfile.TemporaryDirectory() as tmp:
                destination = Path(tmp)
                checks = []
                with (
                    patch.object(smoke.tempfile, "mkdtemp", return_value=str(destination)),
                    patch.object(smoke.platform, "system", return_value=system),
                    patch.object(Path, "is_mount", side_effect=NotImplementedError("unsupported")) as is_mount,
                    patch.object(
                        smoke.check_portable_package_runtime, "remove_tree_with_retries", return_value=""
                    ) as remove,
                ):
                    with smoke.package_workspace(checks) as workspace:
                        self.assertEqual(workspace, destination)
                    is_mount.assert_not_called()
                    remove.assert_called_once_with(destination)
                self.assertTrue(checks[-1]["ok"], checks)

    def test_macos_preflight_uses_candidate_version_not_checkout_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "Culvia.app"
            (app / "Contents").mkdir(parents=True)
            (app / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleExecutable": "culvia-desktop"}))
            executable = app / "Contents/MacOS/culvia-desktop"
            preflight = smoke.check_macos_artifact_preflight
            with (
                patch.object(
                    preflight, "read_desktop_config", return_value={"version": "1.0.0", "identifier": "app.culvia"}
                ),
                patch.object(preflight, "app_bundle_detail", return_value=(True, "valid", executable)),
                patch.object(preflight, "collect_checks", return_value=[]) as collect,
                patch.object(smoke, "run_command", return_value=subprocess.CompletedProcess([], 0, "arm64\n", "")),
            ):
                self.assertEqual(
                    smoke.macos_launcher(
                        app, Path(tmp) / "candidate.dmg", version="0.2.0", target="aarch64-apple-darwin", checks=[]
                    ),
                    executable,
                )
                self.assertEqual(collect.call_args.kwargs["config"]["version"], "0.2.0")

    def test_cli_persists_failure_and_does_not_overwrite_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "candidate.zip"
            wheel = make_wheel(root)
            artifact.write_bytes(b"package")
            args = ["--windows-zip", str(artifact), "--wheel", str(wheel), "--python", sys.executable, "--json"]
            failure = {"ok": False, "checks": [{"name": "first launch", "ok": False}]}
            with patch.object(smoke, "verify_package", return_value=failure), redirect_stdout(io.StringIO()):
                self.assertEqual(smoke.main(args), 1)
                output = Path(str(artifact) + ".lite-runtime.json")
                self.assertEqual(json.loads(output.read_text()), failure)
                for path in (artifact, wheel, Path(str(artifact) + ".evidence.json"), Path(str(artifact) + ".sha256")):
                    with self.assertRaisesRegex(SystemExit, "must not overwrite"):
                        smoke.main([*args, "--output", str(path)])
            self.assertEqual(artifact.read_bytes(), b"package")

    def test_json_stdout_is_lossless_on_cp1252_and_evidence_stays_utf8(self) -> None:
        for ok in (True, False):
            with self.subTest(ok=ok), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                output = root / "验收📷.json"
                payload = {"ok": ok, "checks": [{"name": "运行环境", "ok": ok, "detail": "当前会话 📷"}]}
                buffer = io.BytesIO()
                with io.TextIOWrapper(buffer, encoding="cp1252", errors="strict") as stdout:
                    with patch.object(smoke, "verify_package", return_value=payload), redirect_stdout(stdout):
                        returncode = smoke.main(
                            [
                                "--windows-zip",
                                str(root / "candidate.zip"),
                                "--wheel",
                                str(root / "candidate.whl"),
                                "--python",
                                sys.executable,
                                "--output",
                                str(output),
                                "--json",
                            ]
                        )
                    stdout.flush()
                    console = buffer.getvalue().decode("cp1252")
                self.assertEqual(returncode, 0 if ok else 1)
                self.assertEqual(json.loads(console), payload)
                evidence = output.read_bytes()
                self.assertIn("当前会话 📷".encode("utf-8"), evidence)
                self.assertEqual(json.loads(evidence.decode("utf-8")), payload)

    def test_summary_stdout_escapes_unrepresentable_report_path_on_cp1252(self) -> None:
        for ok in (True, False):
            with self.subTest(ok=ok), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                output = root / "验收📷.json"
                payload = {"ok": ok, "checks": [{"name": "运行环境", "ok": ok, "detail": "当前会话 📷"}]}
                buffer = io.BytesIO()
                with io.TextIOWrapper(buffer, encoding="cp1252", errors="strict") as stdout:
                    with patch.object(smoke, "verify_package", return_value=payload), redirect_stdout(stdout):
                        returncode = smoke.main(
                            [
                                "--windows-zip",
                                str(root / "candidate.zip"),
                                "--wheel",
                                str(root / "candidate.whl"),
                                "--python",
                                sys.executable,
                                "--output",
                                str(output),
                            ]
                        )
                    stdout.flush()
                    console = buffer.getvalue().decode("cp1252")
                self.assertEqual(returncode, 0 if ok else 1)
                escaped_path = str(output).encode("cp1252", errors="backslashreplace").decode("cp1252")
                self.assertEqual(console.strip(), f"{'OK' if ok else 'FAIL'} Lite package runtime: {escaped_path}")
                self.assertEqual(json.loads(output.read_text(encoding="utf-8")), payload)

    def test_evidence_output_hardlink_cannot_truncate_wheel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wheel = make_wheel(root)
            output = root / "report.json"
            os.link(wheel, output)
            original = wheel.read_bytes()
            with self.assertRaisesRegex(SystemExit, "must not overwrite"):
                smoke.main(
                    [
                        "--windows-zip",
                        str(root / "candidate.zip"),
                        "--wheel",
                        str(wheel),
                        "--python",
                        sys.executable,
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(wheel.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
