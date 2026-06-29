from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import check_desktop_release_workflow, desktop_release_contract


ROOT = Path(__file__).resolve().parents[1]


def copy_workflow_fixture(target: Path) -> None:
    for relative in (
        ".github/workflows/desktop-release.yml",
        "tools/desktop_release_contract.py",
    ):
        source = ROOT / relative
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


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
        self.assertIn("formal package gate", names)
        self.assertIn("write release checksum", names)
        self.assertIn("cargo build --release --locked --manifest-path", commands)
        self.assertIn("desktop/tauri/src-tauri/Cargo.toml", commands)
        self.assertNotIn("run tauri:build", commands)
        self.assertIn("tools/build_windows_zip.py --build", commands)
        self.assertIn("tools/check_portable_package_preflight.py --windows-zip", commands)
        self.assertIn("tools/check_portable_package_runtime.py --windows-zip", commands)
        self.assertIn("--exit-after-ms 20000", commands)
        self.assertIn("tools/formal_gate.py --windows-zip-artifact", commands)
        self.assertIn("--skip-unit-tests", commands)
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
        self.assertIn("tools/formal_gate.py --linux-tgz-artifact", commands)
        self.assertIn("--skip-unit-tests", commands)
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

    def test_run_prints_step_progress_to_stderr(self) -> None:
        contract = desktop_release_contract.platform_contract("linux")

        def fake_run_step(step: desktop_release_contract.ReleaseStep, *, root: Path = ROOT) -> dict[str, object]:
            return {"name": step.name, "command": list(step.command), "returncode": 1, "seconds": 0.25, "ok": False}

        stderr = io.StringIO()
        with (
            patch("tools.desktop_release_contract.native_platform_key", return_value="linux"),
            patch("tools.desktop_release_contract.run_step", side_effect=fake_run_step),
            patch("sys.stderr", stderr),
        ):
            payload = desktop_release_contract.run_contract(contract, python=Path("/python"), progress=True)

        self.assertFalse(payload["ok"])
        self.assertIn("[linux-release] 1/12 install python desktop extras ...", stderr.getvalue())
        self.assertIn("[linux-release] 1/12 FAIL install python desktop extras (0.25s)", stderr.getvalue())

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
