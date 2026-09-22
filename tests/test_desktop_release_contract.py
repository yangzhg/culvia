from __future__ import annotations

from contextlib import chdir
import io
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import check_desktop_release_workflow, desktop_release_contract


ROOT = Path(__file__).resolve().parents[1]


def copy_workflow_fixture(target: Path) -> None:
    relative = Path(".github/workflows/desktop-release.yml")
    destination = target / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text((ROOT / relative).read_text(encoding="utf-8"), encoding="utf-8")


def run_matrix_selection(**overrides: str) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    workflow = (ROOT / ".github/workflows/desktop-release.yml").read_text(encoding="utf-8")
    step = check_desktop_release_workflow.workflow_step_block(workflow, "Build selected matrix")
    script = textwrap.dedent(step.split("        run: |\n", 1)[1])
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "outputs"
        summary = Path(tmp) / "summary"
        env = {
            **os.environ,
            "EVENT_NAME": "workflow_dispatch",
            "REF_NAME": "main",
            "REF_TYPE": "branch",
            "INPUT_PLATFORM": "all",
            "INPUT_PROFILE": "release",
            "INPUT_UPLOAD_ARTIFACTS": "true",
            "INPUT_PUBLISH_RELEASE": "false",
            "INPUT_RELEASE_TAG": "",
            "GITHUB_OUTPUT": str(output),
            "GITHUB_STEP_SUMMARY": str(summary),
            **overrides,
        }
        result = subprocess.run([sys.executable, "-c", script], env=env, text=True, capture_output=True)
        values = dict(line.split("=", 1) for line in output.read_text().splitlines()) if output.exists() else {}
        if summary.exists():
            values["summary"] = summary.read_text()
        return result, values


def workflow_python_script(step_name: str) -> str:
    workflow = (ROOT / ".github/workflows/desktop-release.yml").read_text(encoding="utf-8")
    step = check_desktop_release_workflow.workflow_step_block(workflow, step_name)
    return textwrap.dedent(step.split("        run: |\n", 1)[1])


def workflow_job_runs(job_name: str, *, needs: dict, cancelled: bool = False) -> bool:
    workflow = (ROOT / ".github/workflows/desktop-release.yml").read_text(encoding="utf-8")
    block = check_desktop_release_workflow.workflow_job_block(workflow, job_name)
    if not block:
        return False
    condition = check_desktop_release_workflow.yaml_key_values(block, "if")[0]
    condition = condition.removeprefix("${{").removesuffix("}}").strip()
    success = all(job["result"] == "success" for job in needs.values())
    has_status = any(token in condition for token in ("always()", "cancelled()", "success()", "failure()"))
    for name, job in needs.items():
        condition = condition.replace(f"needs.{name}.result", repr(job["result"]))
        for key, value in job.get("outputs", {}).items():
            condition = condition.replace(f"needs.{name}.outputs.{key}", repr(value))
    condition = condition.replace("!cancelled()", str(not cancelled)).replace("cancelled()", str(cancelled))
    condition = condition.replace("always()", "True").replace("success()", str(success))
    condition = condition.replace("&&", " and ").replace("||", " or ")
    return (has_status or success) and bool(eval(condition, {"__builtins__": {}}, {}))


def make_lite_release_assets(root: Path, *, platform: str = "linux", arch: str = "x64") -> tuple[dict, Path]:
    version = "0.2.0"
    targets = {
        ("macos", "arm64"): "aarch64-apple-darwin",
        ("macos", "x64"): "x86_64-apple-darwin",
        ("windows", "x64"): "x86_64-pc-windows-msvc",
        ("linux", "x64"): "x86_64-unknown-linux-gnu",
    }
    target = targets[platform, arch]
    artifact_name = f"culvia-{platform}-lite-{arch}"
    if platform == "macos":
        archive_name = f"Culvia_{version}_{'aarch64' if arch == 'arm64' else 'x64'}-lite.dmg"
    else:
        archive_name = f"culvia-{version}-{platform}-lite-{target}.{'zip' if platform == 'windows' else 'tar.gz'}"
    directory = root / artifact_name
    directory.mkdir(parents=True)
    archive = directory / archive_name
    archive.write_bytes(b"candidate desktop archive")
    (directory / f"{archive_name}.sha256").write_text(hashlib.sha256(archive.read_bytes()).hexdigest())
    (directory / f"{archive_name}.evidence.json").write_text("{}")
    source = root / "culvia-python-source"
    source.mkdir(exist_ok=True)
    wheel = source / f"culvia-{version}-py3-none-any.whl"
    wheel.write_bytes(b"candidate wheel")
    (source / f"culvia-{version}.tar.gz").write_bytes(b"source archive")
    report_dir = root / f"{artifact_name}-lite-runtime"
    report_dir.mkdir()
    report = report_dir / f"{archive_name}.lite-runtime.json"
    report.write_text(
        json.dumps(
            {
                "schema": "culvia-lite-runtime-evidence-v1",
                "ok": True,
                "runtimeProfile": "lite",
                "platform": platform,
                "version": version,
                "target": target,
                "artifact": {
                    "name": archive.name,
                    "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                    "sizeBytes": archive.stat().st_size,
                },
                "wheel": {
                    "name": wheel.name,
                    "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                    "sizeBytes": wheel.stat().st_size,
                },
                "firstLaunch": {"ok": True},
                "reuseLaunch": {"ok": True},
            }
        )
    )
    return {
        "include": [{"platform": platform, "arch": arch, "profile": "lite", "artifact_name": artifact_name}]
    }, report


class DesktopReleaseContractTests(unittest.TestCase):
    def test_windows_plan_runs_real_build_smoke_package_and_preflight_chain(self) -> None:
        contract = desktop_release_contract.platform_contract("windows")
        payload = desktop_release_contract.plan_payload(contract, python=Path("/python"))
        commands = "\n".join(" ".join(step["command"]) for step in payload["steps"])
        names = [step["name"] for step in payload["steps"]]

        self.assertEqual(payload["runner"], "windows-latest")
        self.assertEqual(payload["target"], "x86_64-pc-windows-msvc")
        self.assertTrue(payload["archive"].endswith(".zip"))
        self.assertTrue(payload["checksum"].endswith(".zip.sha256"))
        self.assertTrue(payload["evidenceManifest"].endswith(".zip.evidence.json"))
        self.assertIn("release evidence manifest", payload["uploadRule"])
        self.assertIn("backend build", names)
        self.assertIn("backend smoke", names)
        self.assertIn("desktop shell build", names)
        self.assertIn("portable package build", names)
        self.assertIn("portable package artifact preflight", names)
        self.assertIn("portable package runtime verification", names)
        self.assertIn("write release checksum", names)
        self.assertIn("cargo build --release --locked --manifest-path", commands)
        self.assertIn("desktop/tauri/src-tauri/Cargo.toml", commands)
        self.assertNotIn("run tauri:build", commands)
        self.assertIn("tools/build_windows_zip.py --build", commands)
        self.assertIn("tools/check_portable_package_preflight.py --windows-zip", commands)
        self.assertIn("tools/check_portable_package_runtime.py --windows-zip", commands)
        self.assertIn("--exit-after-ms 20000", commands)
        self.assertIn("tools/write_release_checksum.py", commands)
        self.assertIn(".zip.sha256", commands)
        self.assertNotIn("--ensure-placeholder", commands)

    def test_linux_plan_runs_real_build_smoke_package_and_preflight_chain(self) -> None:
        contract = desktop_release_contract.platform_contract("linux")
        payload = desktop_release_contract.plan_payload(contract, python=Path("/python"))
        commands = "\n".join(" ".join(step["command"]) for step in payload["steps"])

        self.assertEqual(payload["runner"], "ubuntu-latest")
        self.assertEqual(payload["target"], "x86_64-unknown-linux-gnu")
        self.assertTrue(payload["archive"].endswith(".tar.gz"))
        self.assertTrue(payload["checksum"].endswith(".tar.gz.sha256"))
        self.assertTrue(payload["evidenceManifest"].endswith(".tar.gz.evidence.json"))
        self.assertIn("release evidence manifest", payload["uploadRule"])
        self.assertIn("libwebkit2gtk-4.1-dev", payload["runnerDependencies"][-1])
        self.assertIn("cargo build --release --locked --manifest-path", commands)
        self.assertIn("desktop/tauri/src-tauri/Cargo.toml", commands)
        self.assertNotIn("run tauri:build", commands)
        self.assertIn("tools/build_linux_tgz.py --build", commands)
        self.assertIn("tools/check_portable_package_preflight.py --linux-tgz", commands)
        self.assertIn("tools/check_portable_package_runtime.py --linux-tgz", commands)
        self.assertIn("--exit-after-ms 20000", commands)
        self.assertIn("tools/write_release_checksum.py", commands)
        self.assertIn(".tar.gz.sha256", commands)
        self.assertNotIn("--ensure-placeholder", commands)

    def test_windows_lite_plan_skips_bundled_backend_chain(self) -> None:
        contract = desktop_release_contract.platform_contract("windows", profile="lite")
        payload = desktop_release_contract.plan_payload(contract, python=Path("/python"))
        commands = "\n".join(" ".join(step["command"]) for step in payload["steps"])
        names = [step["name"] for step in payload["steps"]]

        self.assertEqual(payload["profile"], "lite")
        self.assertTrue(payload["archive"].endswith("-windows-lite-x86_64-pc-windows-msvc.zip"))
        self.assertEqual(payload["artifactGlob"], "dist/windows-lite/*.zip")
        self.assertEqual(payload["artifactName"], "culvia-windows-lite-x64")
        self.assertIn("desktop shell lite build", names)
        self.assertIn("lite package build", names)
        self.assertIn("lite package artifact preflight", names)
        self.assertIn("write release checksum", names)
        self.assertIn("build-lite-headless.py", commands)
        self.assertIn("--runtime-profile lite", commands)
        self.assertIn("tools/check_portable_package_preflight.py --windows-lite-zip", commands)
        self.assertNotIn("backend build", names)
        self.assertNotIn("backend smoke", names)
        self.assertNotIn("portable package runtime verification", names)

    def test_linux_lite_plan_skips_bundled_backend_chain(self) -> None:
        contract = desktop_release_contract.platform_contract("linux", profile="lite")
        payload = desktop_release_contract.plan_payload(contract, python=Path("/python"))
        commands = "\n".join(" ".join(step["command"]) for step in payload["steps"])

        self.assertEqual(payload["profile"], "lite")
        self.assertTrue(payload["archive"].endswith("-linux-lite-x86_64-unknown-linux-gnu.tar.gz"))
        self.assertEqual(payload["artifactGlob"], "dist/linux-lite/*.tar.gz")
        self.assertEqual(payload["artifactName"], "culvia-linux-lite-x64")
        self.assertIn("build-lite-headless.py", commands)
        self.assertIn("tools/build_linux_tgz.py --build --runtime-profile lite", commands)
        self.assertIn("tools/check_portable_package_preflight.py --linux-lite-tgz", commands)
        self.assertNotIn("check_backend_smoke.py", commands)

    def test_run_refuses_non_native_platform(self) -> None:
        contract = desktop_release_contract.platform_contract("windows")

        with patch("tools.desktop_release_contract.native_platform_key", return_value="linux"):
            payload = desktop_release_contract.run_contract(contract, python=Path("/python"))

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["results"], [])
        self.assertIn("must run on Windows", payload["issues"][0])

    def test_run_stops_on_failure_before_writing_release_evidence(self) -> None:
        contract = desktop_release_contract.platform_contract("linux")

        def fake_run_step(step: desktop_release_contract.ReleaseStep, *, root: Path = ROOT) -> dict[str, object]:
            return {"name": step.name, "command": list(step.command), "returncode": 1, "seconds": 0.25, "ok": False}

        with (
            patch("tools.desktop_release_contract.native_platform_key", return_value="linux"),
            patch("tools.desktop_release_contract.run_step", side_effect=fake_run_step) as run_step,
            patch.object(
                desktop_release_contract.write_release_evidence_manifest, "write_manifest_from_contract_payload"
            ) as write_manifest,
        ):
            payload = desktop_release_contract.run_contract(contract, python=Path("/python"))

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["failed"], ["install python desktop extras"])
        self.assertEqual(len(payload["results"]), 1)
        run_step.assert_called_once()
        write_manifest.assert_not_called()

    def test_text_output_summarizes_run_result_and_failure_logs(self) -> None:
        contract = desktop_release_contract.platform_contract("linux")
        payload = desktop_release_contract.plan_payload(contract, python=Path("/python"))
        payload["ok"] = False
        payload["results"] = [
            {
                "name": "install python desktop extras",
                "command": ["/python", "-m", "pip", "install", "-e", ".[desktop]"],
                "returncode": 1,
                "seconds": 0.25,
                "ok": False,
                "stdoutTail": "stdout tail",
                "stderrTail": "stderr tail",
            }
        ]
        stdout = io.StringIO()

        with patch("sys.stdout", stdout):
            desktop_release_contract.print_text(payload, contract=contract)

        output = stdout.getvalue()
        self.assertIn("FAIL linux desktop release contract:", output)
        self.assertIn("FAIL install python desktop extras (0.25s)", output)
        self.assertIn("stdout tail", output)
        self.assertIn("stderr tail", output)
        self.assertIn("Artifacts:", output)
        self.assertIn("dist/linux", output)
        self.assertIn(".tar.gz.sha256", output)
        self.assertIn(".tar.gz.evidence.json", output)

    def test_text_output_for_run_error_does_not_dump_plan(self) -> None:
        contract = desktop_release_contract.platform_contract("windows")
        payload = desktop_release_contract.plan_payload(contract, python=Path("/python"))
        payload["ok"] = False
        payload["issues"] = ["windows release contract must run on Windows; current platform is Darwin."]
        payload["results"] = []
        stdout = io.StringIO()

        with patch("sys.stdout", stdout):
            desktop_release_contract.print_text(payload, contract=contract, plan=False)

        output = stdout.getvalue()
        self.assertIn("FAIL windows desktop release contract:", output)
        self.assertIn("must run on Windows", output)
        self.assertIn("Artifacts:", output)
        self.assertIn("dist/windows", output)
        self.assertNotIn("install python desktop extras:", output)

    def test_current_workflow_contract_passes_static_checker(self) -> None:
        payload = check_desktop_release_workflow.result_payload(check_desktop_release_workflow.collect_checks(ROOT))

        self.assertTrue(payload["ok"], payload["failed"])

    def test_release_selection_produces_all_four_native_lite_validation_targets(self) -> None:
        result, outputs = run_matrix_selection()
        self.assertEqual(result.returncode, 0, result.stderr)
        targets = json.loads(outputs["lite_matrix"])["include"]
        self.assertEqual(
            {(job["platform"], job["arch"], job["os"]) for job in targets},
            {
                ("macos", "arm64", "macos-latest"),
                ("macos", "x64", "macos-15-intel"),
                ("windows", "x64", "windows-latest"),
                ("linux", "x64", "ubuntu-latest"),
            },
        )
        self.assertTrue(all(job["profile"] == "lite" for job in targets))
        self.assertEqual(outputs["validate_lite"], "true")

    def test_lite_validation_selection_honors_platform_profile_and_artifact_upload(self) -> None:
        result, outputs = run_matrix_selection(INPUT_PLATFORM="windows", INPUT_PROFILE="lite")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [job["artifact_name"] for job in json.loads(outputs["lite_matrix"])["include"]], ["culvia-windows-lite-x64"]
        )
        for overrides in ({"INPUT_PROFILE": "full"}, {"INPUT_UPLOAD_ARTIFACTS": "false"}):
            with self.subTest(overrides=overrides):
                result, outputs = run_matrix_selection(**overrides)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(outputs["validate_lite"], "false")
                self.assertIn("not validated", outputs["summary"])

    def test_manual_publish_rejects_disabled_artifact_upload(self) -> None:
        result, _ = run_matrix_selection(
            INPUT_PUBLISH_RELEASE="true",
            INPUT_RELEASE_TAG="v0.2.0",
            INPUT_UPLOAD_ARTIFACTS="false",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("upload_artifacts=true", result.stderr)

    def test_lite_validation_continues_after_full_lane_failure_but_never_without_inputs(self) -> None:
        needs = {
            "select": {"result": "success", "outputs": {"validate_lite": "true", "upload_artifacts": "true"}},
            "package": {"result": "failure"},
            "source": {"result": "success"},
        }
        self.assertTrue(workflow_job_runs("lite-runtime", needs=needs))
        self.assertFalse(workflow_job_runs("lite-runtime", needs=needs, cancelled=True))
        for job, field, value in (
            ("source", "result", "failure"),
            ("select", "validate_lite", "false"),
            ("select", "upload_artifacts", "false"),
        ):
            changed = json.loads(json.dumps(needs))
            (changed[job] if field == "result" else changed[job]["outputs"])[field] = value
            with self.subTest(job=job, field=field):
                self.assertFalse(workflow_job_runs("lite-runtime", needs=changed))

    def test_publish_requires_successful_lite_validation_not_skipped_or_failed(self) -> None:
        needs = {
            "select": {"result": "success", "outputs": {"publish_release": "true"}},
            "package": {"result": "success"},
            "source": {"result": "success"},
            "lite-runtime": {"result": "success"},
        }
        self.assertTrue(workflow_job_runs("publish", needs=needs))
        for result in ("failure", "skipped", "cancelled"):
            needs["lite-runtime"]["result"] = result
            self.assertFalse(workflow_job_runs("publish", needs=needs), result)

    def test_native_lite_smoke_step_passes_downloaded_inputs_and_fixture_dependencies(self) -> None:
        script = workflow_python_script("Verify candidate Desktop Lite package runtime")
        for platform, extension, package_flag in (
            ("macos", "dmg", "--macos-dmg"),
            ("windows", "zip", "--windows-zip"),
            ("linux", "tar.gz", "--linux-tgz"),
        ):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                desktop, source = root / "candidate-inputs/desktop", root / "candidate-inputs/python"
                desktop.mkdir(parents=True)
                source.mkdir()
                package = desktop / f"candidate-lite.{extension}"
                package.write_bytes(b"candidate")
                wheel = source / "culvia-0.2.0-py3-none-any.whl"
                wheel.write_bytes(b"wheel")
                env = {"PACKAGE_GLOB": f"dist/lite/*.{extension}", "PACKAGE_PLATFORM": platform}
                with chdir(root), patch.dict(os.environ, env), patch("subprocess.run") as run:
                    exec(compile(script, "workflow-lite-runtime", "exec"), {})
                commands = [call.args[0] for call in run.call_args_list]
                self.assertEqual(
                    commands[0], [sys.executable, "-m", "pip", "install", f"{wheel.relative_to(root)}[release]"]
                )
                self.assertEqual(commands[1], [sys.executable, "-m", "pip", "check"])
                command = commands[2]
                if platform == "linux":
                    self.assertEqual(command[:2], ["xvfb-run", "-a"])
                    command = command[2:]
                self.assertEqual(
                    command[:4],
                    [
                        sys.executable,
                        "tools/check_lite_package_runtime.py",
                        package_flag,
                        str(package.relative_to(root)),
                    ],
                )
                self.assertEqual(command[command.index("--wheel") + 1], str(wheel.relative_to(root)))
                self.assertEqual(command[command.index("--python") + 1], sys.executable)
                self.assertEqual(
                    command[command.index("--output") + 1],
                    str(Path("smoke-reports") / f"{package.name}.lite-runtime.json"),
                )
                self.assertTrue(all(call.kwargs["check"] for call in run.call_args_list))

    def test_native_lite_smoke_rejects_ambiguous_downloaded_packages_before_install(self) -> None:
        script = workflow_python_script("Verify candidate Desktop Lite package runtime")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "candidate-inputs/desktop").mkdir(parents=True)
            (root / "candidate-inputs/python").mkdir()
            for name in ("first.zip", "second.zip"):
                (root / "candidate-inputs/desktop" / name).write_bytes(b"candidate")
            (root / "candidate-inputs/python/culvia-0.2.0-py3-none-any.whl").write_bytes(b"wheel")
            with chdir(root), patch.dict(os.environ, {"PACKAGE_GLOB": "dist/*.zip"}), patch("subprocess.run") as run:
                with self.assertRaisesRegex(SystemExit, "exactly one"):
                    exec(compile(script, "workflow-lite-runtime", "exec"), {})
            run.assert_not_called()

    def test_failure_report_records_unvalidated_input_without_overwriting_tool_evidence(self) -> None:
        script = workflow_python_script("Preserve Lite runtime failure report")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with chdir(root), patch.dict(os.environ, {"PACKAGE_ARTIFACT": "culvia-linux-lite-x64"}):
                exec(compile(script, "workflow-lite-failure-report", "exec"), {})
                report = root / "smoke-reports/culvia-linux-lite-x64.lite-runtime.json"
                self.assertIs(json.loads(report.read_text())["ok"], False)
                report.unlink()
                original = root / "smoke-reports/candidate.tar.gz.lite-runtime.json"
                original.write_text('{"ok": false, "checks": ["original failure"]}')
                exec(compile(script, "workflow-lite-failure-report", "exec"), {})
                self.assertEqual(list(original.parent.iterdir()), [original])
                self.assertEqual(json.loads(original.read_text())["checks"], ["original failure"])

    def test_release_assets_accept_exact_successful_native_lite_evidence(self) -> None:
        for platform, arch in (("macos", "arm64"), ("macos", "x64"), ("windows", "x64"), ("linux", "x64")):
            with self.subTest(platform=platform, arch=arch), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                matrix, report = make_lite_release_assets(root, platform=platform, arch=arch)
                assets = check_desktop_release_workflow.release_asset_paths(root, matrix=matrix, version="0.2.0")
                self.assertIn(report, assets)
                self.assertEqual(len(assets), 6)

    def test_complete_release_keeps_full_packages_and_independent_lite_reports(self) -> None:
        result, outputs = run_matrix_selection(EVENT_NAME="push", REF_NAME="v0.2.0", REF_TYPE="tag")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs["publish_release"], "true")
        matrix = json.loads(outputs["matrix"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for job in matrix["include"]:
                if job["profile"] == "lite":
                    make_lite_release_assets(root, platform=job["platform"], arch=job["arch"])
                    continue
                directory = root / job["artifact_name"]
                directory.mkdir()
                if job["platform"] == "macos":
                    arch = "aarch64" if job["arch"] == "arm64" else "x64"
                    name = f"Culvia_0.2.0_{arch}.dmg"
                else:
                    name = "culvia-0.2.0-windows-x86_64-pc-windows-msvc.zip"
                for suffix in ("", ".sha256", ".evidence.json"):
                    (directory / (name + suffix)).write_bytes(b"verified Full asset")
            assets = check_desktop_release_workflow.release_asset_paths(root, matrix=matrix, version="0.2.0")
            self.assertEqual(len(assets), 27)
            self.assertEqual(len({path.name for path in assets}), 27)

    def test_release_assets_reject_failed_incomplete_or_mismatched_lite_evidence(self) -> None:
        replacements = (
            ("ok", False),
            ("schema", "unknown"),
            ("runtimeProfile", "full"),
            ("platform", "windows"),
            ("target", "aarch64-apple-darwin"),
            ("version", "0.1.0"),
            ("firstLaunch", {"ok": False}),
            ("reuseLaunch", {}),
            ("artifact", {"name": "other.tar.gz", "sha256": "bad", "sizeBytes": 1}),
            ("wheel", {"name": "other.whl", "sha256": "bad", "sizeBytes": 1}),
        )
        for key, value in replacements:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                matrix, report = make_lite_release_assets(root)
                payload = json.loads(report.read_text())
                payload[key] = value
                report.write_text(json.dumps(payload))
                with self.assertRaisesRegex(ValueError, "Lite runtime evidence"):
                    check_desktop_release_workflow.release_asset_paths(root, matrix=matrix, version="0.2.0")

    def test_release_assets_reject_changed_package_or_wheel_after_validation(self) -> None:
        for changed_suffix in (".whl", "linux-lite-x86_64-unknown-linux-gnu.tar.gz"):
            with self.subTest(changed_suffix=changed_suffix), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                matrix, _ = make_lite_release_assets(root)
                artifact = next(root.rglob(f"*{changed_suffix}"))
                original = artifact.read_bytes()
                artifact.write_bytes(bytes([original[0] ^ 1]) + original[1:])
                with self.assertRaisesRegex(ValueError, "Lite runtime evidence"):
                    check_desktop_release_workflow.release_asset_paths(root, matrix=matrix, version="0.2.0")

    def test_release_assets_reject_unknown_files_nested_directories_and_missing_reports(self) -> None:
        for extra in ("debug.log", "nested/unexpected.zip", "duplicate/report.lite-runtime.json", None):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                matrix, report = make_lite_release_assets(root)
                if extra is None:
                    report.unlink()
                else:
                    path = report.parent / extra
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("{}")
                with self.assertRaises(ValueError):
                    check_desktop_release_workflow.release_asset_paths(root, matrix=matrix, version="0.2.0")

    def test_workflow_checker_rejects_removed_lite_runtime_safety_gates(self) -> None:
        replacements = (
            (
                "needs.select.outputs.release_ref || github.sha",
                "needs.select.outputs.release_ref || github.ref",
                "workflow pins checkout fallbacks to the triggering commit",
            ),
            (
                "!cancelled() && needs.select.result",
                "success() && needs.select.result",
                "workflow validates available Lite packages after unrelated Full failures",
            ),
            (
                'f"{wheel}[release]"',
                'f"{wheel}"',
                "workflow smoke tests same-run Lite packages with the candidate wheel",
            ),
            ("if: ${{ !cancelled() }}", "if: success()", "workflow preserves separate Lite runtime failure evidence"),
            (
                "needs.lite-runtime.result == 'success'",
                "needs.lite-runtime.result != 'failure'",
                "workflow publishes only after successful Lite runtime evidence verification",
            ),
            (
                "verified = release_asset_paths(",
                "verified = list(",
                "workflow publishes only after successful Lite runtime evidence verification",
            ),
        )
        for before, after, failed_check in replacements:
            with self.subTest(before=before), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                copy_workflow_fixture(root)
                workflow = root / ".github/workflows/desktop-release.yml"
                original = workflow.read_text()
                self.assertIn(before, original)
                workflow.write_text(original.replace(before, after))
                payload = check_desktop_release_workflow.result_payload(
                    check_desktop_release_workflow.collect_checks(root)
                )
                self.assertIn(failed_check, payload["failed"])

    def test_workflow_checker_rejects_broad_upload_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_workflow_fixture(root)
            workflow = root / ".github/workflows/desktop-release.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "dist/windows/culvia-*-windows-x86_64-pc-windows-msvc.zip",
                    "dist/**",
                ),
                encoding="utf-8",
            )

            payload = check_desktop_release_workflow.result_payload(check_desktop_release_workflow.collect_checks(root))

        self.assertFalse(payload["ok"])
        self.assertIn(
            "workflow uploads only verified final archives, checksums, and evidence manifests", payload["failed"]
        )

    def test_workflow_checker_rejects_macos_lite_dmg_without_lite_basename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_workflow_fixture(root)
            workflow = root / ".github/workflows/desktop-release.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace("dist/macos-lite/*-lite.dmg", "dist/macos-lite/*.dmg"),
                encoding="utf-8",
            )

            payload = check_desktop_release_workflow.result_payload(check_desktop_release_workflow.collect_checks(root))

        self.assertFalse(payload["ok"])
        self.assertIn(
            "workflow uploads only verified final archives, checksums, and evidence manifests", payload["failed"]
        )

    def test_workflow_checker_rejects_ref_only_release_concurrency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_workflow_fixture(root)
            workflow = root / ".github/workflows/desktop-release.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "github.event_name == 'workflow_dispatch' && inputs.release_tag || github.ref_name",
                    "github.ref_name",
                ),
                encoding="utf-8",
            )

            payload = check_desktop_release_workflow.result_payload(check_desktop_release_workflow.collect_checks(root))

        self.assertFalse(payload["ok"])
        self.assertIn("workflow serializes runs by target release tag or ref", payload["failed"])

    def test_workflow_checker_rejects_canceling_same_target_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_workflow_fixture(root)
            workflow = root / ".github/workflows/desktop-release.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace("cancel-in-progress: false", "cancel-in-progress: true"),
                encoding="utf-8",
            )

            payload = check_desktop_release_workflow.result_payload(check_desktop_release_workflow.collect_checks(root))

        self.assertFalse(payload["ok"])
        self.assertIn("workflow serializes runs by target release tag or ref", payload["failed"])

    def test_workflow_checker_rejects_unsafe_manual_publish_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_workflow_fixture(root)
            workflow = root / ".github/workflows/desktop-release.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace("        default: release\n", "        default: full\n"),
                encoding="utf-8",
            )

            payload = check_desktop_release_workflow.result_payload(check_desktop_release_workflow.collect_checks(root))

        self.assertFalse(payload["ok"])
        self.assertIn("workflow manual publish defaults to complete release selection", payload["failed"])

    def test_workflow_checker_rejects_incomplete_release_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_workflow_fixture(root)
            workflow = root / ".github/workflows/desktop-release.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    'return job["profile"] == "lite" or job["platform"] in {"macos", "windows"}',
                    'return job["profile"] == "lite"',
                ),
                encoding="utf-8",
            )

            payload = check_desktop_release_workflow.result_payload(check_desktop_release_workflow.collect_checks(root))

        self.assertFalse(payload["ok"])
        self.assertIn("workflow release profile selects complete supported matrix", payload["failed"])

    def test_workflow_checker_rejects_linux_full_in_release_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_workflow_fixture(root)
            workflow = root / ".github/workflows/desktop-release.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    'return job["profile"] == "lite" or job["platform"] in {"macos", "windows"}',
                    "return True",
                ),
                encoding="utf-8",
            )

            payload = check_desktop_release_workflow.result_payload(check_desktop_release_workflow.collect_checks(root))

        self.assertFalse(payload["ok"])
        self.assertIn("workflow release profile selects complete supported matrix", payload["failed"])

    def test_workflow_checker_rejects_manual_publish_without_complete_matrix_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_workflow_fixture(root)
            workflow = root / ".github/workflows/desktop-release.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    'if manual_publish and (selected_platform != "all" or selected_profile != "release"):',
                    'if manual_publish and selected_platform != "all":',
                ),
                encoding="utf-8",
            )

            payload = check_desktop_release_workflow.result_payload(check_desktop_release_workflow.collect_checks(root))

        self.assertFalse(payload["ok"])
        self.assertIn("workflow manual publish rejects incomplete release selection", payload["failed"])

    def test_workflow_checker_rejects_lite_runtime_wheel_install_without_extra(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_workflow_fixture(root)
            workflow = root / ".github/workflows/desktop-release.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    'pip install "${runtime_wheels[0]}[desktop-runtime]"',
                    'pip install "${runtime_wheels[0]}"',
                ),
                encoding="utf-8",
            )

            payload = check_desktop_release_workflow.result_payload(check_desktop_release_workflow.collect_checks(root))

        self.assertFalse(payload["ok"])
        self.assertIn(
            "workflow verifies a clean dependency-resolved Desktop Lite runtime wheel",
            payload["failed"],
        )

    def test_workflow_checker_requires_lite_safe_model_runtime_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_workflow_fixture(root)
            workflow = root / ".github/workflows/desktop-release.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "import inspect, keyring, safetensors, torch",
                    "import inspect, keyring, torch",
                ),
                encoding="utf-8",
            )

            payload = check_desktop_release_workflow.result_payload(check_desktop_release_workflow.collect_checks(root))

        self.assertFalse(payload["ok"])
        self.assertIn(
            "workflow verifies a clean dependency-resolved Desktop Lite runtime wheel",
            payload["failed"],
        )

    def test_workflow_checker_requires_macos_intel_clip_safetensors_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_workflow_fixture(root)
            workflow = root / ".github/workflows/desktop-release.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "use_safetensors=True",
                    "use_safetensors=False",
                ),
                encoding="utf-8",
            )

            payload = check_desktop_release_workflow.result_payload(check_desktop_release_workflow.collect_checks(root))

        self.assertFalse(payload["ok"])
        self.assertIn("workflow verifies the macOS Intel model runtime contract", payload["failed"])

    def test_workflow_checker_rejects_direct_upload_path_without_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_workflow_fixture(root)
            workflow = root / ".github/workflows/desktop-release.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "path: |\n            ${{ matrix.artifact_path }}\n            ${{ matrix.checksum_path }}\n            ${{ matrix.evidence_path }}",
                    "path: dist/windows/culvia-*-windows-x86_64-pc-windows-msvc.zip",
                ),
                encoding="utf-8",
            )

            payload = check_desktop_release_workflow.result_payload(check_desktop_release_workflow.collect_checks(root))

        self.assertFalse(payload["ok"])
        self.assertIn(
            "workflow uploads only verified final archives, checksums, and evidence manifests", payload["failed"]
        )

    def test_workflow_checker_rejects_broad_checksum_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_workflow_fixture(root)
            workflow = root / ".github/workflows/desktop-release.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "dist/windows/culvia-*-windows-x86_64-pc-windows-msvc.zip.sha256",
                    "dist/**",
                ),
                encoding="utf-8",
            )

            payload = check_desktop_release_workflow.result_payload(check_desktop_release_workflow.collect_checks(root))

        self.assertFalse(payload["ok"])
        self.assertIn(
            "workflow uploads only verified final archives, checksums, and evidence manifests", payload["failed"]
        )

    def test_workflow_checker_rejects_missing_evidence_upload_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_workflow_fixture(root)
            workflow = root / ".github/workflows/desktop-release.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    "            ${{ matrix.evidence_path }}\n",
                    "",
                ),
                encoding="utf-8",
            )

            payload = check_desktop_release_workflow.result_payload(check_desktop_release_workflow.collect_checks(root))

        self.assertFalse(payload["ok"])
        self.assertIn(
            "workflow uploads only verified final archives, checksums, and evidence manifests", payload["failed"]
        )

    def test_workflow_checker_rejects_missing_artifact_attestations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_workflow_fixture(root)
            workflow = root / ".github/workflows/desktop-release.yml"
            text = workflow.read_text(encoding="utf-8")
            start = text.index("      - name: Generate desktop package attestations")
            end = text.index("      - name: Upload verified desktop package")
            text = text[:start] + text[end:]
            start = text.index("      - name: Generate Python distribution attestations")
            end = text.index("      - name: Upload verified Python distributions")
            workflow.write_text(text[:start] + text[end:], encoding="utf-8")

            payload = check_desktop_release_workflow.result_payload(check_desktop_release_workflow.collect_checks(root))

        self.assertFalse(payload["ok"])
        self.assertIn("workflow generates GitHub artifact attestations", payload["failed"])

    def test_workflow_checker_rejects_release_publish_without_explicit_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_workflow_fixture(root)
            workflow = root / ".github/workflows/desktop-release.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(' --repo "${GITHUB_REPOSITORY}"', ""),
                encoding="utf-8",
            )

            payload = check_desktop_release_workflow.result_payload(check_desktop_release_workflow.collect_checks(root))

        self.assertFalse(payload["ok"])
        self.assertIn("workflow creates immutable release with explicit repository", payload["failed"])

    def test_workflow_checker_rejects_mutable_release_uploads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_workflow_fixture(root)
            workflow = root / ".github/workflows/desktop-release.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    '"${RELEASE_TAG}" "${assets[@]}"',
                    '"${RELEASE_TAG}" "${assets[@]}" --clobber',
                ),
                encoding="utf-8",
            )

            payload = check_desktop_release_workflow.result_payload(check_desktop_release_workflow.collect_checks(root))

        self.assertFalse(payload["ok"])
        self.assertIn("workflow creates immutable release with explicit repository", payload["failed"])

    def test_workflow_checker_rejects_missing_duplicate_asset_basename_guard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_workflow_fixture(root)
            workflow = root / ".github/workflows/desktop-release.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace("if duplicates:", "if False:"),
                encoding="utf-8",
            )

            payload = check_desktop_release_workflow.result_payload(check_desktop_release_workflow.collect_checks(root))

        self.assertFalse(payload["ok"])
        self.assertIn("workflow rejects duplicate release asset basenames before upload", payload["failed"])

    def test_workflow_checker_rejects_missing_version_tag_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_workflow_fixture(root)
            workflow = root / ".github/workflows/desktop-release.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace(
                    'python tools/check_version_sync.py --tag "${{ needs.select.outputs.release_ref }}"',
                    "python -c \"print('version check removed')\"",
                ),
                encoding="utf-8",
            )

            payload = check_desktop_release_workflow.result_payload(check_desktop_release_workflow.collect_checks(root))

        self.assertFalse(payload["ok"])
        self.assertIn("workflow enforces synchronized release tag", payload["failed"])

    def test_workflow_checker_rejects_raw_actions_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_workflow_fixture(root)
            workflow = root / ".github/workflows/desktop-release.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8")
                + """

      - name: Unsafe workspace cache
        uses: actions/cache@v4
        with:
          path: .
          key: unsafe
""",
                encoding="utf-8",
            )

            payload = check_desktop_release_workflow.result_payload(check_desktop_release_workflow.collect_checks(root))

        self.assertFalse(payload["ok"])
        self.assertIn("workflow avoids raw cache artifacts", payload["failed"])

    def test_workflow_checker_rejects_secrets_and_bypasses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copy_workflow_fixture(root)
            workflow = root / ".github/workflows/desktop-release.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8")
                + "\n# ${{ secrets.API_KEY }}\n# continue-on-error: true\n# set +e\n",
                encoding="utf-8",
            )

            payload = check_desktop_release_workflow.result_payload(check_desktop_release_workflow.collect_checks(root))

        self.assertFalse(payload["ok"])
        self.assertIn("workflow has no release bypasses or secrets", payload["failed"])


if __name__ == "__main__":
    unittest.main()
