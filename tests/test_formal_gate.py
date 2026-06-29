from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import formal_gate


ROOT = Path(__file__).resolve().parents[1]


class FakeCompletedProcess:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FormalGateTests(unittest.TestCase):
    def test_default_gate_steps_cover_release_and_desktop_readiness(self) -> None:
        steps = formal_gate.collect_steps(root=ROOT, python=Path("/python"), include_release_smoke=True)
        names = [step.name for step in steps]

        self.assertEqual(
            names,
            [
                "unit tests",
                "compileall",
                "whitespace",
                "sensitive information scan",
                "desktop readiness",
                "desktop release workflow contract",
                "release smoke",
            ],
        )
        self.assertIn("unittest", steps[0].command)
        self.assertEqual(steps[3].ok_returncodes, (1,))
        self.assertIn("sk-[A-Za-z0-9]{12,}", " ".join(steps[3].command))
        self.assertIn("check_desktop_readiness.py", " ".join(steps[4].command))
        self.assertIn("check_desktop_release_workflow.py", " ".join(steps[5].command))
        self.assertIn("release_smoke.py", " ".join(steps[6].command))
        self.assertIn("--strict", steps[6].command)

    def test_sdist_release_smoke_is_explicit_and_strict(self) -> None:
        steps = formal_gate.collect_steps(
            root=ROOT,
            python=Path("/python"),
            include_release_smoke=False,
            include_sdist_smoke=True,
            dist_dir=Path("/release/dist"),
        )
        sdist = next(step for step in steps if step.name == "sdist release smoke")

        self.assertIn("release_smoke.py", " ".join(sdist.command))
        self.assertIn("--build-sdist", sdist.command)
        self.assertIn("--dist-dir", sdist.command)
        self.assertIn("/release/dist", sdist.command)
        self.assertIn("--strict", sdist.command)

    def test_sdist_artifact_release_smoke_is_explicit_and_strict(self) -> None:
        steps = formal_gate.collect_steps(
            root=ROOT,
            python=Path("/python"),
            include_release_smoke=False,
            sdist_artifact=Path("/release/culvia-0.1.0.tar.gz"),
        )
        sdist = next(step for step in steps if step.name == "sdist release smoke")

        self.assertIn("--sdist", sdist.command)
        self.assertIn("/release/culvia-0.1.0.tar.gz", sdist.command)
        self.assertIn("--strict", sdist.command)

    def test_strict_desktop_adds_strict_toolchain_flag(self) -> None:
        steps = formal_gate.collect_steps(root=ROOT, python=Path("/python"), strict_desktop=True)
        readiness = next(step for step in steps if step.name == "desktop readiness")
        names = [step.name for step in steps]

        self.assertIn("--strict-toolchain", readiness.command)
        self.assertIn("desktop release preflight", names)
        self.assertIn("backend placeholder", names)
        self.assertIn("desktop cargo check", names)
        self.assertIn("desktop cargo test", names)
        self.assertIn("desktop shell info", names)
        self.assertIn("backend build plan", names)
        preflight = next(step for step in steps if step.name == "desktop release preflight")
        placeholder = next(step for step in steps if step.name == "backend placeholder")
        cargo_check = next(step for step in steps if step.name == "desktop cargo check")
        cargo_test = next(step for step in steps if step.name == "desktop cargo test")
        desktop_info = next(step for step in steps if step.name == "desktop shell info")
        backend_plan = next(step for step in steps if step.name == "backend build plan")
        self.assertIn("check_desktop_release_preflight.py", " ".join(preflight.command))
        self.assertIn("--json", preflight.command)
        self.assertIn("--ensure-placeholder", placeholder.command)
        self.assertIn("desktop/tauri/src-tauri/Cargo.toml", cargo_check.command)
        self.assertIn("desktop/tauri/src-tauri/Cargo.toml", cargo_test.command)
        self.assertEqual(desktop_info.command[:4], ("npm", "--prefix", "desktop/tauri", "run"))
        self.assertIn("desktop/tauri/scripts/build-backend.py", backend_plan.command)
        self.assertIn("--check-plan", backend_plan.command)

    def test_backend_smoke_gate_is_explicit_and_uses_optional_binary(self) -> None:
        steps = formal_gate.collect_steps(
            root=ROOT,
            python=Path("/python"),
            include_backend_smoke=True,
            backend_binary=Path("/backend"),
        )
        backend_smoke = next(step for step in steps if step.name == "backend smoke")

        self.assertIn("tools/check_backend_smoke.py", " ".join(backend_smoke.command))
        self.assertIn("--binary", backend_smoke.command)
        self.assertIn("/backend", backend_smoke.command)
        self.assertIn("--timeout", backend_smoke.command)
        self.assertIn("90", backend_smoke.command)
        self.assertIn("--json", backend_smoke.command)

    def test_backend_workflow_smoke_gate_is_explicit_and_uses_optional_binary(self) -> None:
        steps = formal_gate.collect_steps(
            root=ROOT,
            python=Path("/python"),
            include_backend_workflow_smoke=True,
            backend_binary=Path("/backend"),
        )
        workflow_smoke = next(step for step in steps if step.name == "backend workflow smoke")

        self.assertIn("tools/check_backend_workflow_smoke.py", " ".join(workflow_smoke.command))
        self.assertIn("--binary", workflow_smoke.command)
        self.assertIn("/backend", workflow_smoke.command)
        self.assertIn("--timeout", workflow_smoke.command)
        self.assertIn("120", workflow_smoke.command)
        self.assertIn("--json", workflow_smoke.command)

    def test_macos_artifact_preflight_is_explicit(self) -> None:
        steps = formal_gate.collect_steps(
            root=ROOT,
            python=Path("/python"),
            include_macos_artifact_preflight=True,
            strict_macos_artifacts=True,
            macos_app=Path("/release/App.app"),
            macos_dmg=Path("/release/App.dmg"),
            macos_bundle_dir=Path("/release/bundle"),
        )
        artifact = next(step for step in steps if step.name == "macos artifact preflight")

        self.assertIn("tools/check_macos_artifact_preflight.py", " ".join(artifact.command))
        self.assertIn("--bundle-dir", artifact.command)
        self.assertIn("/release/bundle", artifact.command)
        self.assertIn("--app", artifact.command)
        self.assertIn("/release/App.app", artifact.command)
        self.assertIn("--dmg", artifact.command)
        self.assertIn("/release/App.dmg", artifact.command)
        self.assertIn("--strict", artifact.command)
        self.assertIn("--json", artifact.command)

    def test_macos_app_launch_smoke_is_explicit(self) -> None:
        steps = formal_gate.collect_steps(
            root=ROOT,
            python=Path("/python"),
            include_macos_app_launch_smoke=True,
            macos_app=Path("/release/App.app"),
            macos_bundle_dir=Path("/release/bundle"),
        )
        launch = next(step for step in steps if step.name == "macos app launch smoke")

        self.assertIn("tools/check_macos_app_launch_smoke.py", " ".join(launch.command))
        self.assertIn("--bundle-dir", launch.command)
        self.assertIn("/release/bundle", launch.command)
        self.assertIn("--app", launch.command)
        self.assertIn("/release/App.app", launch.command)
        self.assertIn("--json", launch.command)

    def test_macos_artifact_steps_default_to_dist_macos(self) -> None:
        steps = formal_gate.collect_steps(
            root=ROOT,
            python=Path("/python"),
            include_macos_artifact_preflight=True,
            include_macos_app_launch_smoke=True,
        )

        commands = "\n".join(" ".join(step.command) for step in steps)
        self.assertIn(str(ROOT / "dist" / "macos"), commands)

    def test_portable_package_artifact_preflights_are_explicit(self) -> None:
        steps = formal_gate.collect_steps(
            root=ROOT,
            python=Path("/python"),
            windows_zip_artifact=Path("/release/culvia-windows.zip"),
            linux_tgz_artifact=Path("/release/culvia-linux.tar.gz"),
        )
        windows = next(step for step in steps if step.name == "windows portable package preflight")
        linux = next(step for step in steps if step.name == "linux portable package preflight")

        self.assertIn("tools/check_portable_package_preflight.py", " ".join(windows.command))
        self.assertIn("--windows-zip", windows.command)
        self.assertIn("/release/culvia-windows.zip", windows.command)
        self.assertIn("--json", windows.command)
        self.assertIn("tools/check_portable_package_preflight.py", " ".join(linux.command))
        self.assertIn("--linux-tgz", linux.command)
        self.assertIn("/release/culvia-linux.tar.gz", linux.command)
        self.assertIn("--json", linux.command)

    def test_release_preflight_can_run_without_strict_desktop(self) -> None:
        steps = formal_gate.collect_steps(
            root=ROOT,
            python=Path("/python"),
            include_release_preflight=True,
            strict_signing=True,
            backend_binary=Path("/backend"),
        )
        preflight = next(step for step in steps if step.name == "desktop release preflight")

        self.assertIn("tools/check_desktop_release_preflight.py", " ".join(preflight.command))
        self.assertIn("--strict-signing", preflight.command)
        self.assertIn("--backend-binary", preflight.command)
        self.assertIn("/backend", preflight.command)

    def test_strict_signing_cli_implies_release_preflight(self) -> None:
        output = io.StringIO()
        with patch("sys.stdout", output):
            result = formal_gate.main(
                [
                    "--root",
                    str(ROOT),
                    "--python",
                    "/python",
                    "--strict-signing",
                    "--skip-release-smoke",
                    "--list",
                ]
            )

        self.assertEqual(result, 0)
        self.assertIn("desktop release preflight:", output.getvalue())
        self.assertIn("--strict-signing", output.getvalue())

    def test_strict_macos_artifacts_cli_implies_artifact_preflight(self) -> None:
        output = io.StringIO()
        with patch("sys.stdout", output):
            result = formal_gate.main(
                [
                    "--root",
                    str(ROOT),
                    "--python",
                    "/python",
                    "--strict-macos-artifacts",
                    "--skip-release-smoke",
                    "--list",
                ]
            )

        self.assertEqual(result, 0)
        self.assertIn("macos artifact preflight:", output.getvalue())
        self.assertIn("--strict", output.getvalue())

    def test_portable_package_artifact_cli_args_enable_preflight_steps(self) -> None:
        output = io.StringIO()
        with patch("sys.stdout", output):
            result = formal_gate.main(
                [
                    "--root",
                    str(ROOT),
                    "--python",
                    "/python",
                    "--windows-zip-artifact",
                    "/release/culvia-windows.zip",
                    "--linux-tgz-artifact",
                    "/release/culvia-linux.tar.gz",
                    "--skip-release-smoke",
                    "--list",
                ]
            )

        self.assertEqual(result, 0)
        self.assertIn("windows portable package preflight:", output.getvalue())
        self.assertIn("--windows-zip /release/culvia-windows.zip", output.getvalue())
        self.assertIn("linux portable package preflight:", output.getvalue())
        self.assertIn("--linux-tgz /release/culvia-linux.tar.gz", output.getvalue())

    def test_build_sdist_cli_enables_sdist_release_smoke_step(self) -> None:
        output = io.StringIO()
        with patch("sys.stdout", output):
            result = formal_gate.main(
                [
                    "--root",
                    str(ROOT),
                    "--python",
                    "/python",
                    "--build-sdist",
                    "--dist-dir",
                    "/release/dist",
                    "--skip-release-smoke",
                    "--list",
                ]
            )

        self.assertEqual(result, 0)
        self.assertIn("sdist release smoke:", output.getvalue())
        self.assertIn("--build-sdist --dist-dir /release/dist --strict", output.getvalue())

    def test_sdist_artifact_cli_enables_sdist_release_smoke_step(self) -> None:
        output = io.StringIO()
        with patch("sys.stdout", output):
            result = formal_gate.main(
                [
                    "--root",
                    str(ROOT),
                    "--python",
                    "/python",
                    "--sdist-artifact",
                    "/release/culvia-0.1.0.tar.gz",
                    "--skip-release-smoke",
                    "--list",
                ]
            )

        self.assertEqual(result, 0)
        self.assertIn("sdist release smoke:", output.getvalue())
        self.assertIn("--sdist /release/culvia-0.1.0.tar.gz --strict", output.getvalue())

    def test_run_steps_accepts_sensitive_scan_no_match_return_code(self) -> None:
        steps = [
            formal_gate.GateStep("normal", ("ok",)),
            formal_gate.GateStep("secret scan", ("rg",), ok_returncodes=(1,)),
        ]

        def fake_run(command: list[str], **_: object) -> FakeCompletedProcess:
            return FakeCompletedProcess(returncode=1 if command == ["rg"] else 0)

        with patch("tools.formal_gate.subprocess.run", side_effect=fake_run):
            results = formal_gate.run_steps(steps, root=ROOT)

        self.assertEqual([result.status for result in results], ["OK", "OK"])
        self.assertTrue(formal_gate.results_payload(results)["ok"])

    def test_run_steps_prints_progress_to_stderr(self) -> None:
        steps = [formal_gate.GateStep("normal", ("ok",))]

        with (
            patch("tools.formal_gate.subprocess.run", return_value=FakeCompletedProcess(returncode=0)),
            patch("sys.stderr", io.StringIO()) as stderr,
        ):
            results = formal_gate.run_steps(steps, root=ROOT, progress=True)

        self.assertEqual(results[0].status, "OK")
        self.assertIn("[formal-gate] 1/1 normal ...", stderr.getvalue())
        self.assertIn("[formal-gate] 1/1 OK normal", stderr.getvalue())

    def test_sensitive_scan_match_fails_gate(self) -> None:
        step = formal_gate.GateStep("secret scan", ("rg",), ok_returncodes=(1,))

        with patch(
            "tools.formal_gate.subprocess.run",
            return_value=FakeCompletedProcess(returncode=0, stdout="README.md:1:sk-secret"),
        ):
            result = formal_gate.run_step(step, root=ROOT)

        self.assertEqual(result.status, "FAIL")
        self.assertIn("sk-secret", result.stdout)

    def test_sensitive_scan_falls_back_when_rg_is_missing(self) -> None:
        step = formal_gate.GateStep("sensitive information scan", ("rg",), ok_returncodes=(1,))
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("ok\n", encoding="utf-8")
            with patch("tools.formal_gate.subprocess.run", side_effect=FileNotFoundError("rg")):
                result = formal_gate.run_step(step, root=root)

        self.assertEqual(result.status, "OK")
        self.assertIn("Python sensitive information fallback found no matches", result.stdout)

    def test_sensitive_scan_fallback_reports_secret_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("token sk-abcdefghijkl\n", encoding="utf-8")
            returncode, stdout = formal_gate.sensitive_scan_fallback_check(root=root)

        self.assertEqual(returncode, 0)
        self.assertIn("README.md:1:sk-abcdefghijkl", stdout)

    def test_missing_gate_command_reports_failure(self) -> None:
        step = formal_gate.GateStep("missing", ("missing-command",))

        with patch("tools.formal_gate.subprocess.run", side_effect=FileNotFoundError("missing-command")):
            result = formal_gate.run_step(step, root=ROOT)

        self.assertEqual(result.status, "FAIL")
        self.assertEqual(result.returncode, 127)
        self.assertIn("missing-command", result.stderr)

    def test_whitespace_step_falls_back_when_git_is_blocked_by_xcode_license(self) -> None:
        step = formal_gate.GateStep("whitespace", ("git", "diff", "--check"))
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("ok\n", encoding="utf-8")
            with patch(
                "tools.formal_gate.subprocess.run",
                return_value=FakeCompletedProcess(returncode=69, stderr=formal_gate.XCODE_LICENSE_ERROR),
            ):
                result = formal_gate.run_step(step, root=root)

        self.assertEqual(result.status, "OK")
        self.assertIn("Python whitespace fallback passed", result.stdout)

    def test_whitespace_fallback_reports_trailing_whitespace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("bad  \n", encoding="utf-8")
            returncode, stdout = formal_gate.whitespace_fallback_check(root=root)

        self.assertEqual(returncode, 1)
        self.assertIn("README.md:1: trailing whitespace", stdout)

    def test_main_list_outputs_planned_steps_without_running_commands(self) -> None:
        output = io.StringIO()
        with patch("sys.stdout", output):
            result = formal_gate.main(["--root", str(ROOT), "--python", "/python", "--list", "--skip-release-smoke"])

        self.assertEqual(result, 0)
        self.assertIn("unit tests:", output.getvalue())
        self.assertIn("desktop readiness:", output.getvalue())
        self.assertIn("desktop release workflow contract:", output.getvalue())
        self.assertNotIn("release smoke:", output.getvalue())

    def test_main_json_reports_failures(self) -> None:
        def fake_run(command: list[str], **_: object) -> FakeCompletedProcess:
            if command[:1] == ["git"]:
                return FakeCompletedProcess(returncode=1, stderr="trailing whitespace")
            if command[:1] == ["rg"]:
                return FakeCompletedProcess(returncode=1)
            return FakeCompletedProcess(returncode=0)

        output = io.StringIO()
        with patch("tools.formal_gate.subprocess.run", side_effect=fake_run), patch("sys.stdout", output):
            result = formal_gate.main(["--root", str(ROOT), "--python", "/python", "--skip-release-smoke", "--json"])

        payload = json.loads(output.getvalue())
        self.assertEqual(result, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["failed"], ["whitespace"])


if __name__ == "__main__":
    unittest.main()
