from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import build_macos_app


class MacosAppBuildTests(unittest.TestCase):
    def test_plan_includes_reproducible_app_steps(self) -> None:
        payload = build_macos_app.plan_payload(
            root=Path("/repo"),
            python=Path("/python"),
            clean_first=True,
            require_apple_development=True,
        )
        names = [step["name"] for step in payload["steps"]]

        self.assertEqual(names[0], "clean macos app artifacts")
        self.assertEqual(names[1], "macos app preflight")
        self.assertIn("clean_macos_app_artifacts.py", payload["steps"][0]["command"][1])
        self.assertIn("--require-apple-development", payload["steps"][1]["command"])
        self.assertIn(["npm", "--prefix", "desktop/tauri", "ci"], [step["command"] for step in payload["steps"]])
        self.assertIn("macos app launch smoke", names)
        self.assertEqual(payload["outputDir"], "/repo/dist/macos")

    def test_strict_plan_adds_notarized_release_checks(self) -> None:
        payload = build_macos_app.plan_payload(
            root=Path("/repo"),
            python=Path("/python"),
            clean_first=True,
            strict_release_signing=True,
            strict_artifacts=True,
        )
        by_name = {step["name"]: step["command"] for step in payload["steps"]}

        self.assertIn("macos release signing preflight", by_name)
        self.assertIn("--strict-signing", by_name["macos release signing preflight"])
        self.assertIn("--strict", by_name["macos artifact preflight"])

    def test_plan_can_skip_npm_and_launch_smoke(self) -> None:
        payload = build_macos_app.plan_payload(
            root=Path("/repo"),
            python=Path("/python"),
            npm_action="skip",
            skip_launch_smoke=True,
        )
        names = [step["name"] for step in payload["steps"]]

        self.assertNotIn("install desktop npm dependencies", names)
        self.assertNotIn("macos app launch smoke", names)

    def test_lite_plan_skips_backend_and_uses_lite_output(self) -> None:
        payload = build_macos_app.plan_payload(
            root=Path("/repo"),
            python=Path("/python"),
            clean_first=True,
            runtime_profile="lite",
        )
        names = [step["name"] for step in payload["steps"]]
        commands = "\n".join(" ".join(step["command"]) for step in payload["steps"])

        self.assertEqual(payload["runtimeProfile"], "lite")
        self.assertEqual(payload["outputDir"], "/repo/dist/macos-lite")
        self.assertIn("build macos lite app and dmg", names)
        self.assertIn("build-lite-headless.py", commands)
        self.assertIn("--runtime-profile lite", commands)
        self.assertNotIn("build macos backend", names)
        self.assertNotIn("macos app launch smoke", names)

    def test_build_environment_prepends_known_toolchain_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cargo_bin = Path(tmp) / ".cargo" / "bin"
            cargo_bin.mkdir(parents=True)

            with patch("tools.build_macos_app.EXTRA_TOOLCHAIN_DIRECTORIES", (cargo_bin,)):
                env = build_macos_app.toolchain_environment({"PATH": "/usr/bin"})

        self.assertEqual(env["PATH"].split(os.pathsep)[0], str(cargo_bin))
        self.assertIn("/usr/bin", env["PATH"].split(os.pathsep))

    def test_run_uses_selected_identity_for_subsequent_build_steps(self) -> None:
        calls: list[tuple[list[str], dict[str, str]]] = []
        identity = "Apple Development: Example (TEAMID)"

        def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            env = kwargs.get("env")
            self.assertIsInstance(env, dict)
            calls.append((command, dict(env)))  # type: ignore[arg-type]
            if "check_macos_app_preflight.py" in command[1]:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps({"ok": True, "selectedIdentity": identity}),
                    stderr="",
                )
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("tools.build_macos_app.subprocess.run", side_effect=fake_run),
        ):
            payload = build_macos_app.run_macos_build(
                root=Path(tmp),
                python=Path("/python"),
                npm_action="skip",
                skip_launch_smoke=True,
                env={},
            )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["selectedIdentity"], identity)
        backend_call = next(item for item in calls if "build-backend.py" in item[0][1])
        self.assertEqual(backend_call[1]["APPLE_SIGNING_IDENTITY"], identity)
        self.assertEqual(backend_call[1]["CULVIA_MACOS_BACKEND_CODESIGN_IDENTITY"], identity)

    def test_run_stops_on_first_failed_step(self) -> None:
        def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(command, 1, stdout="bad", stderr="worse")

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("tools.build_macos_app.subprocess.run", side_effect=fake_run),
        ):
            payload = build_macos_app.run_macos_build(
                root=Path(tmp),
                python=Path("/python"),
                npm_action="skip",
                skip_launch_smoke=True,
                env={},
            )

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["failedStep"], "macos app preflight")
        self.assertEqual(len(payload["steps"]), 1)

    def test_progress_mode_streams_expensive_child_output(self) -> None:
        class FakePipe:
            def __init__(self, lines: list[str]) -> None:
                self.lines = iter(lines)

            def readline(self) -> str:
                return next(self.lines, "")

            def close(self) -> None:
                pass

        class FakeProcess:
            def __init__(self) -> None:
                self.stdout = FakePipe(["child stdout\n"])
                self.stderr = FakePipe(["child stderr\n"])

            def wait(self) -> int:
                return 0

        run_calls: list[list[str]] = []
        popen_calls: list[list[str]] = []

        def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            run_calls.append(command)
            if "check_macos_app_preflight.py" in command[1]:
                return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"ok": True}), stderr="")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        def fake_popen(command: list[str], **_kwargs: object) -> FakeProcess:
            popen_calls.append(command)
            return FakeProcess()

        stderr = io.StringIO()
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("tools.build_macos_app.subprocess.run", side_effect=fake_run),
            patch("tools.build_macos_app.subprocess.Popen", side_effect=fake_popen),
            patch("sys.stderr", stderr),
        ):
            payload = build_macos_app.run_macos_build(
                root=Path(tmp),
                python=Path("/python"),
                npm_action="skip",
                skip_launch_smoke=True,
                env={},
                progress=True,
            )

        self.assertTrue(payload["ok"])
        self.assertTrue(any("build-backend.py" in command[1] for command in popen_calls))
        self.assertTrue(any("tauri:build:headless" in command for command in popen_calls))
        self.assertTrue(any("check_macos_app_preflight.py" in command[1] for command in run_calls))
        self.assertIn("[macos-release] 2/4 build macos backend with live output", stderr.getvalue())
        self.assertIn("[macos-release:stdout] child stdout", stderr.getvalue())
        self.assertIn("[macos-release:stderr] child stderr", stderr.getvalue())

    def test_run_writes_checksum_and_evidence_after_full_app_smoke(self) -> None:
        def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            if "check_macos_app_preflight.py" in command[1]:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps({"ok": True, "selectedIdentity": "-"}),
                    stderr="",
                )
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("tools.build_macos_app.subprocess.run", side_effect=fake_run),
        ):
            root = Path(tmp)
            bundle = root / "desktop" / "tauri" / "src-tauri" / "target" / "release" / "bundle"
            app = bundle / "macos" / "Culvia.app"
            dmg = bundle / "dmg" / "Culvia_0.1.0_aarch64.dmg"
            app.mkdir(parents=True)
            (app / "Contents").mkdir()
            dmg.parent.mkdir(parents=True)
            dmg.write_bytes(b"preview dmg")
            staged_app = root / "dist" / "macos" / "Culvia.app"
            staged_dmg = root / "dist" / "macos" / "Culvia_0.1.0_aarch64.dmg"

            payload = build_macos_app.run_macos_build(
                root=root,
                python=Path("/python"),
                npm_action="skip",
                env={},
            )

            self.assertTrue(payload["ok"], payload.get("evidenceManifestResult"))
            self.assertEqual(Path(str(payload["app"])), staged_app.resolve())
            self.assertEqual(Path(str(payload["dmg"])), staged_dmg.resolve())
            self.assertTrue((staged_app / "Contents").is_dir())
            self.assertEqual(staged_dmg.read_bytes(), b"preview dmg")
            self.assertTrue(Path(str(payload["checksum"])).is_file())
            manifest_path = Path(str(payload["evidenceManifest"]))
            self.assertTrue(manifest_path.is_file())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema"], "culvia-macos-evidence-v1")
            self.assertEqual(manifest["artifact"], str(staged_dmg.resolve()))
            self.assertEqual(manifest["steps"][-1]["name"], "write release checksum")

    def test_run_writes_lite_evidence_with_step_results(self) -> None:
        def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            if "check_macos_app_preflight.py" in command[1]:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps({"ok": True, "selectedIdentity": "-"}),
                    stderr="",
                )
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("tools.build_macos_app.subprocess.run", side_effect=fake_run),
        ):
            root = Path(tmp)
            bundle = root / "desktop" / "tauri" / "src-tauri" / "target" / "release" / "bundle"
            app = bundle / "macos" / "Culvia.app"
            dmg = bundle / "dmg" / "Culvia_0.1.0_aarch64.dmg"
            app.mkdir(parents=True)
            (app / "Contents").mkdir()
            dmg.parent.mkdir(parents=True)
            dmg.write_bytes(b"lite dmg")

            payload = build_macos_app.run_macos_build(
                root=root,
                python=Path("/python"),
                npm_action="skip",
                runtime_profile="lite",
                env={},
            )

            self.assertTrue(payload["ok"], payload.get("evidenceManifestResult"))
            self.assertEqual(payload["runtimeProfile"], "lite")
            manifest_path = Path(str(payload["evidenceManifest"]))
            self.assertTrue(manifest_path.is_file())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            step_names = [step["name"] for step in manifest["steps"]]
            self.assertEqual(manifest["runtimeProfile"], "lite")
            self.assertIn("build macos lite app and dmg", step_names)
            self.assertIn("write release checksum", step_names)
            self.assertNotIn("build macos backend", step_names)

    def test_text_output_prints_release_artifact_locations(self) -> None:
        payload = {
            "ok": True,
            "runtimeProfile": "lite",
            "steps": [],
            "outputDir": "/repo/dist/macos-lite",
            "app": "/repo/dist/macos-lite/Culvia.app",
            "dmg": "/repo/dist/macos-lite/Culvia_0.1.0_aarch64.dmg",
            "checksum": "/repo/dist/macos-lite/Culvia_0.1.0_aarch64.dmg.sha256",
            "evidenceManifest": "/repo/dist/macos-lite/Culvia_0.1.0_aarch64.dmg.evidence.json",
        }
        stdout = io.StringIO()

        with patch("sys.stdout", stdout):
            build_macos_app.print_text(payload)

        output = stdout.getvalue()
        self.assertIn("Artifacts:", output)
        self.assertIn("dist: /repo/dist/macos-lite", output)
        self.assertIn("dmg: /repo/dist/macos-lite/Culvia_0.1.0_aarch64.dmg", output)


if __name__ == "__main__":
    unittest.main()
