from __future__ import annotations

import ast
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools import desktop_release_contract, release_status_report


ROOT = Path(__file__).resolve().parents[1]


class ReleaseStatusReportTests(unittest.TestCase):
    def check_result(self, name: str, *, ok: bool = True, optional: bool = False) -> SimpleNamespace:
        return SimpleNamespace(name=name, ok=ok, optional=optional, detail=name)

    def write_checksum_and_evidence(self, artifact: Path) -> None:
        digest = release_status_report.write_release_checksum.sha256_file(artifact)
        checksum = Path(str(artifact) + ".sha256")
        checksum.write_text(
            release_status_report.write_release_checksum.checksum_text(digest=digest, artifact=artifact),
            encoding="utf-8",
        )
        manifest = {
            "schema": release_status_report.write_release_evidence_manifest.SCHEMA,
            "artifactName": artifact.name,
            "checksumName": checksum.name,
            "sha256": digest,
            "sizeBytes": artifact.stat().st_size,
            "contractOk": True,
            "requiredSteps": list(release_status_report.write_release_evidence_manifest.REQUIRED_RESULT_STEPS),
            "steps": [
                {"name": name, "ok": True, "returncode": 0, "seconds": 0.01, "command": ["echo", name]}
                for name in release_status_report.write_release_evidence_manifest.REQUIRED_RESULT_STEPS
            ],
        }
        Path(str(artifact) + ".evidence.json").write_text(json.dumps(manifest), encoding="utf-8")

    def write_macos_app_checksum_and_evidence(self, *, app: Path, dmg: Path) -> None:
        digest = release_status_report.write_release_checksum.sha256_file(dmg)
        checksum = Path(str(dmg) + ".sha256")
        checksum.write_text(
            release_status_report.write_release_checksum.checksum_text(digest=digest, artifact=dmg),
            encoding="utf-8",
        )
        manifest = {
            "schema": release_status_report.write_release_evidence_manifest.MACOS_APP_SCHEMA,
            "platform": "macos",
            "appName": app.name,
            "artifactName": dmg.name,
            "checksumName": checksum.name,
            "sha256": digest,
            "sizeBytes": dmg.stat().st_size,
            "contractOk": True,
            "requiredSteps": list(release_status_report.write_release_evidence_manifest.MACOS_APP_REQUIRED_STEPS),
            "steps": [
                {"name": name, "ok": True, "returncode": 0, "seconds": 0.01, "command": ["echo", name]}
                for name in release_status_report.write_release_evidence_manifest.MACOS_APP_REQUIRED_STEPS
            ],
        }
        Path(str(dmg) + ".evidence.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_estimated_remaining_separates_external_only_blockers(self) -> None:
        estimate = release_status_report.estimated_remaining_payload(
            formal_ready=False,
            blocker_summary={
                "localActionable": [],
                "externalRequired": ["windows: missing artifact"],
                "environment": ["release environment: gh CLI is not available"],
            },
        )

        self.assertEqual(estimate["formal"], "external release evidence only")
        self.assertEqual(estimate["localActionable"], "0")
        self.assertEqual(estimate["externalRelease"], "1-2 release runs")

    def test_redact_local_paths_replaces_repo_home_and_temp_paths(self) -> None:
        root = Path(tempfile.gettempdir()) / "culvia-redaction-root"
        payload = {
            "path": str(root / "dist" / "artifact.zip"),
            "commands": [
                f"python {root / 'tools' / 'release_status_report.py'} --json",
                f"python --wheelhouse {Path(tempfile.gettempdir()) / 'culvia-wheelhouse'}",
            ],
        }

        redacted = release_status_report.redact_local_paths(payload, root=root)
        text = json.dumps(redacted)

        self.assertIn("<repo>/dist/artifact.zip", text)
        self.assertIn("<tmp>/culvia-wheelhouse", text)
        self.assertNotIn(str(root), text)
        self.assertNotIn(tempfile.gettempdir(), text)

    def test_public_payload_redacts_tokens_urls_unknown_paths_and_long_logs(self) -> None:
        openai_key = "sk-" + "1234567890abcdef"
        pypi_key = "pypi-" + "1234567890abcdef"
        github_token = "ghp_" + "1234567890abcdef"
        payload = {
            "detail": (
                f"OPENAI_API_KEY={openai_key} "
                f"TWINE_PASSWORD={pypi_key} "
                f"GITHUB_TOKEN={github_token} "
                "https://user:pass@example.com/simple "
                "/Volumes/release/culvia.zip "
                "C:\\Users\\alice\\culvia\\dist\\app.zip " + ("x" * 2500)
            )
        }

        public = release_status_report.public_release_payload(payload, root=Path("/repo"))
        text = json.dumps(public)

        self.assertTrue(public["redacted"])
        self.assertEqual(public["visibility"], "public-redacted")
        self.assertIn("OPENAI_API_KEY=<redacted>", text)
        self.assertIn("TWINE_PASSWORD=<redacted>", text)
        self.assertIn("GITHUB_TOKEN=<redacted>", text)
        self.assertIn("https://<redacted>@example.com/simple", text)
        self.assertIn("<path>", text)
        self.assertIn("...<truncated>", text)
        for secret in (openai_key, pypi_key, github_token, "user:pass", "/Volumes/release", "C:\\Users\\alice"):
            self.assertNotIn(secret, text)

    def test_main_writes_redacted_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            output = Path(tmp) / "release-status.json"
            payload = {
                "formalReady": False,
                "betaReady": True,
                "estimatedRemaining": {"beta": "0", "formal": "1-2"},
                "platforms": {},
                "blockers": [f"missing artifact: {root / 'dist' / 'culvia.zip'}"],
                "blockerSummary": {"localActionable": [], "externalRequired": [], "environment": []},
                "nextCommandsByCategory": {"localActionable": [], "externalRequired": [], "environment": []},
                "nextCommands": [f"python {root / 'tools' / 'desktop_release_contract.py'} --json"],
            }

            with (
                patch("tools.release_status_report.collect_report", return_value=payload),
                patch(
                    "sys.stdout",
                    new_callable=io.StringIO,
                ) as stdout,
            ):
                code = release_status_report.main(
                    [
                        "--root",
                        str(root),
                        "--json",
                        "--redact-local-paths",
                        "--json-output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 0)
            written = json.loads(output.read_text(encoding="utf-8"))
            printed = json.loads(stdout.getvalue())
            self.assertEqual(written, printed)
            self.assertTrue(written["redacted"])
            self.assertEqual(written["visibility"], "public-redacted")
            self.assertIn("<repo>/dist/culvia.zip", json.dumps(written))
            self.assertNotIn(str(root), json.dumps(written))

    def test_public_json_output_forces_redaction_without_stdout_redaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            output = Path(tmp) / "public-release-status.json"
            payload = {
                "formalReady": False,
                "betaReady": True,
                "estimatedRemaining": {"beta": "0", "formal": "1-2"},
                "platforms": {},
                "blockers": [f"missing artifact: {root / 'dist' / 'culvia.zip'}"],
                "blockerSummary": {"localActionable": [], "externalRequired": [], "environment": []},
                "nextCommandsByCategory": {"localActionable": [], "externalRequired": [], "environment": []},
                "nextCommands": [f"python {root / 'tools' / 'desktop_release_contract.py'} --json"],
            }

            with (
                patch("tools.release_status_report.collect_report", return_value=payload),
                patch(
                    "sys.stdout",
                    new_callable=io.StringIO,
                ) as stdout,
            ):
                code = release_status_report.main(
                    [
                        "--root",
                        str(root),
                        "--json",
                        "--public-json-output",
                        str(output),
                    ]
                )

            self.assertEqual(code, 0)
            written = json.loads(output.read_text(encoding="utf-8"))
            printed = json.loads(stdout.getvalue())
            self.assertTrue(written["redacted"])
            self.assertEqual(written["visibility"], "public-redacted")
            self.assertIn("<repo>/dist/culvia.zip", json.dumps(written))
            self.assertNotIn(str(root), json.dumps(written))
            self.assertIn(str(root), json.dumps(printed))
            self.assertNotIn("redacted", printed)

    def test_main_rejects_same_public_and_private_json_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            output = Path(tmp) / "release-status.json"
            payload = {
                "formalReady": False,
                "betaReady": True,
                "estimatedRemaining": {"beta": "0", "formal": "1-2"},
                "platforms": {},
                "blockers": [],
                "blockerSummary": {"localActionable": [], "externalRequired": [], "environment": []},
                "nextCommandsByCategory": {"localActionable": [], "externalRequired": [], "environment": []},
                "nextCommands": [],
            }

            with patch("tools.release_status_report.collect_report", return_value=payload):
                with self.assertRaises(SystemExit) as raised:
                    release_status_report.main(
                        [
                            "--root",
                            str(root),
                            "--json-output",
                            str(output),
                            "--public-json-output",
                            str(output),
                        ]
                    )

            self.assertIn("--json-output and --public-json-output", str(raised.exception))
            self.assertFalse(output.exists())

    def test_macos_report_requires_app_runtime_smoke_evidence(self) -> None:
        non_strict_checks = [
            self.check_result("macos app bundle structure"),
            self.check_result("macos dmg artifact structure"),
        ]
        strict_checks = [
            self.check_result("macos app bundle structure"),
            self.check_result("macos app signature details", ok=False),
        ]

        preview = {
            "ok": True,
            "failed": [],
            "skipped": ["apple development identity is visible"],
            "passed": ["xcode license is accepted"],
        }
        with (
            patch(
                "tools.release_status_report.macos_app_preflight_payload",
                return_value=preview,
            ),
            patch(
                "tools.release_status_report.check_macos_artifact_preflight.collect_checks",
                side_effect=[non_strict_checks, strict_checks],
            ),
        ):
            report = release_status_report.macos_report(root=Path("/repo"))

        self.assertEqual(report.status, "partial")
        self.assertFalse(report.ready)
        self.assertIn("app launch smoke runtime workflow not executed on native macOS runner", report.blockers)
        self.assertIn("python tools/build_macos_app.py --clean-first --json", report.nextCommands)
        self.assertIn("passed: macos app preflight: xcode license is accepted", report.evidence)

    def test_macos_report_allows_existing_artifacts_after_app_build(self) -> None:
        artifact_checks = [
            self.check_result("macos app artifact exists"),
            self.check_result("macos dmg artifact exists"),
        ]

        with (
            patch(
                "tools.release_status_report.macos_app_preflight_payload",
                return_value={
                    "ok": True,
                    "failed": [],
                    "skipped": ["macos app artifact cleanup state is clean"],
                    "passed": ["xcode license is accepted"],
                },
            ) as preview_payload,
            patch(
                "tools.release_status_report.check_macos_artifact_preflight.collect_checks",
                return_value=artifact_checks,
            ),
        ):
            report = release_status_report.macos_report(root=Path("/repo"))

        preview_payload.assert_called_once_with(root=Path("/repo"), require_clean=False)
        self.assertNotIn("macos app preflight: macos app artifact cleanup state is clean", report.blockers)
        self.assertIn("skipped: macos app preflight: macos app artifact cleanup state is clean", report.evidence)

    def test_macos_report_can_launch_app_runtime_smoke(self) -> None:
        strict_checks = [
            self.check_result("macos app bundle structure"),
            self.check_result("macos app signature details"),
        ]
        app_smoke = {
            "ok": True,
            "failed": [],
            "checks": [
                {
                    "name": "macos app runtime loads fixture cache",
                    "ok": True,
                    "detail": "cache=/tmp/culvia_scores.sqlite",
                }
            ],
        }

        with (
            patch(
                "tools.release_status_report.macos_app_preflight_payload",
                return_value={"ok": True, "failed": [], "skipped": [], "passed": ["xcode license is accepted"]},
            ),
            patch(
                "tools.release_status_report.check_macos_artifact_preflight.collect_checks",
                side_effect=[strict_checks, strict_checks],
            ),
            patch("tools.release_status_report.platform.system", return_value="Darwin"),
            patch(
                "tools.release_status_report.macos_app_launch_smoke_payload",
                return_value=app_smoke,
            ),
        ):
            report = release_status_report.macos_report(root=Path("/repo"), launch_runtime=True)

        self.assertEqual(report.status, "ready")
        self.assertTrue(report.ready)
        self.assertIn("passed: app launch smoke: macos app runtime loads fixture cache", report.evidence)

    def test_macos_report_requires_app_checksum_backend(self) -> None:
        artifact_checks = [
            self.check_result("macos app bundle structure"),
            self.check_result("macos dmg artifact structure"),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / "dist" / "macos"
            (bundle / "Culvia.app").mkdir(parents=True)
            dmg = bundle / "Culvia_0.1.0_aarch64.dmg"
            dmg.parent.mkdir(parents=True, exist_ok=True)
            dmg.write_bytes(b"preview dmg")

            with (
                patch(
                    "tools.release_status_report.macos_app_preflight_payload",
                    return_value={"ok": True, "failed": [], "skipped": [], "passed": ["xcode license is accepted"]},
                ),
                patch(
                    "tools.release_status_report.check_macos_artifact_preflight.collect_checks",
                    side_effect=[artifact_checks, artifact_checks],
                ),
                patch("tools.release_status_report.platform.system", return_value="Darwin"),
            ):
                report = release_status_report.macos_report(root=root)

        self.assertEqual(report.status, "blocked")
        self.assertFalse(report.ready)
        self.assertTrue(any("missing checksum" in blocker for blocker in report.blockers))
        checksum_blocker = next(blocker for blocker in report.blockers if "missing checksum" in blocker)
        self.assertEqual(release_status_report.platform_blocker_category(report, checksum_blocker), "localActionable")
        self.assertEqual(
            release_status_report.platform_blocker_next_commands(report, checksum_blocker),
            ["python tools/build_macos_app.py --clean-first --json"],
        )

    def test_macos_formal_blockers_point_to_strict_release_commands(self) -> None:
        report = release_status_report.PlatformReport(
            key="macos",
            label="macOS",
            status="partial",
            ready=False,
            evidence=[],
            blockers=["macos dmg stapler validation"],
            nextCommands=["python tools/build_macos_app.py --clean-first --json"],
        )

        commands = release_status_report.platform_blocker_next_commands(report, "macos dmg stapler validation")

        self.assertIn("python tools/check_macos_artifact_preflight.py --strict --json", commands)
        self.assertFalse(any("build_macos_app.py" in command for command in commands))

    def test_macos_report_accepts_app_checksum_and_evidence_manifest(self) -> None:
        artifact_checks = [
            self.check_result("macos app bundle structure"),
            self.check_result("macos dmg artifact structure"),
        ]
        strict_checks = [
            *artifact_checks,
            self.check_result("macos dmg stapler validation", ok=False),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / "dist" / "macos"
            app = bundle / "Culvia.app"
            dmg = bundle / "Culvia_0.1.0_aarch64.dmg"
            app.mkdir(parents=True)
            dmg.parent.mkdir(parents=True, exist_ok=True)
            dmg.write_bytes(b"preview dmg")
            self.write_macos_app_checksum_and_evidence(app=app, dmg=dmg)

            with (
                patch(
                    "tools.release_status_report.macos_app_preflight_payload",
                    return_value={"ok": True, "failed": [], "skipped": [], "passed": ["xcode license is accepted"]},
                ),
                patch(
                    "tools.release_status_report.check_macos_artifact_preflight.collect_checks",
                    side_effect=[artifact_checks, strict_checks],
                ),
            ):
                report = release_status_report.macos_report(root=root)

        self.assertEqual(report.status, "partial")
        self.assertFalse(report.ready)
        self.assertTrue(any("release checksum matches" in item for item in report.evidence))
        self.assertTrue(any("release evidence manifest matches" in item for item in report.evidence))
        self.assertTrue(any("macos evidence manifest" in item for item in report.evidence))
        self.assertNotIn("app launch smoke runtime workflow not executed on native macOS runner", report.blockers)
        self.assertIn("macos dmg stapler validation", report.blockers)

    def test_macos_report_rejects_app_manifest_lacking_launch_smoke_step(self) -> None:
        artifact_checks = [
            self.check_result("macos app bundle structure"),
            self.check_result("macos dmg artifact structure"),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / "dist" / "macos"
            app = bundle / "Culvia.app"
            dmg = bundle / "Culvia_0.1.0_aarch64.dmg"
            app.mkdir(parents=True)
            dmg.parent.mkdir(parents=True, exist_ok=True)
            dmg.write_bytes(b"preview dmg")
            self.write_macos_app_checksum_and_evidence(app=app, dmg=dmg)
            manifest_path = Path(str(dmg) + ".evidence.json")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for item in manifest["steps"]:
                if item["name"] == "macos app launch smoke":
                    item["name"] = "macos app launch smoke stale name"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with (
                patch(
                    "tools.release_status_report.macos_app_preflight_payload",
                    return_value={"ok": True, "failed": [], "skipped": [], "passed": ["xcode license is accepted"]},
                ),
                patch(
                    "tools.release_status_report.check_macos_artifact_preflight.collect_checks",
                    side_effect=[artifact_checks, artifact_checks],
                ),
            ):
                report = release_status_report.macos_report(root=root)

        self.assertIn("release evidence manifest steps mismatch", report.blockers)
        self.assertIn("app launch smoke runtime workflow not executed on native macOS runner", report.blockers)

    def test_macos_report_blocks_on_app_preflight_failure(self) -> None:
        non_strict_checks = [
            self.check_result("macos app artifact exists", ok=False, optional=True),
            self.check_result("macos dmg artifact exists", ok=False, optional=True),
        ]
        preview = {
            "ok": False,
            "failed": ["macos app artifact cleanup state is clean"],
            "skipped": [],
            "passed": ["xcode license is accepted"],
        }

        with (
            patch(
                "tools.release_status_report.macos_app_preflight_payload",
                return_value=preview,
            ),
            patch(
                "tools.release_status_report.check_macos_artifact_preflight.collect_checks",
                return_value=non_strict_checks,
            ),
        ):
            report = release_status_report.macos_report(root=Path("/repo"))

        self.assertEqual(report.status, "blocked")
        self.assertFalse(report.ready)
        self.assertIn("macos app preflight: macos app artifact cleanup state is clean", report.blockers)
        self.assertEqual(
            release_status_report.platform_blocker_category(
                report,
                "macos app preflight: macos app artifact cleanup state is clean",
            ),
            "localActionable",
        )
        self.assertIn(
            "python tools/check_macos_app_preflight.py --json",
            release_status_report.platform_blocker_next_commands(
                report,
                "macos app preflight: macos app artifact cleanup state is clean",
            ),
        )

    def test_macos_missing_artifacts_are_local_actionable_on_macos(self) -> None:
        report = release_status_report.PlatformReport(
            key="macos",
            label="macOS",
            status="missing",
            ready=False,
            evidence=[],
            blockers=["macos app artifact exists", "macos dmg artifact exists"],
            nextCommands=[],
        )

        with patch("tools.release_status_report.platform.system", return_value="Darwin"):
            self.assertEqual(
                release_status_report.platform_blocker_category(report, "macos app artifact exists"),
                "localActionable",
            )
            self.assertEqual(
                release_status_report.platform_blocker_category(report, "macos dmg artifact exists"),
                "localActionable",
            )

        commands = release_status_report.platform_blocker_next_commands(report, "macos app artifact exists")
        self.assertEqual(commands, ["python tools/build_macos_app.py --clean-first --json"])

    def test_macos_missing_artifacts_are_external_off_macos(self) -> None:
        report = release_status_report.PlatformReport(
            key="macos",
            label="macOS",
            status="missing",
            ready=False,
            evidence=[],
            blockers=["macos app artifact exists"],
            nextCommands=[],
        )

        with patch("tools.release_status_report.platform.system", return_value="Linux"):
            self.assertEqual(
                release_status_report.platform_blocker_category(report, "macos app artifact exists"),
                "externalRequired",
            )

    def test_windows_report_marks_missing_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = desktop_release_contract.PlatformContract(
                key="windows",
                profile="full",
                host_system="Windows",
                runner="windows-latest",
                target="x86_64-pc-windows-msvc",
                archive=root / "dist" / "windows" / "missing.zip",
                checksum=root / "dist" / "windows" / "missing.zip.sha256",
                evidence_manifest=root / "dist" / "windows" / "missing.zip.evidence.json",
                artifact_glob="dist/windows/*.zip",
                artifact_name="culvia-windows-x64",
                desktop_binary=root / "culvia-desktop.exe",
                backend_binary=root / "culvia-server.exe",
                artifact_flag="--windows-zip-artifact",
                preflight_arg="--windows-zip",
                package_build_tool=root / "tools" / "build_windows_zip.py",
                runner_dependencies=(),
            )

            with patch("tools.release_status_report.desktop_release_contract.platform_contract", return_value=contract):
                report = release_status_report.windows_report(root=root)

        self.assertEqual(report.status, "missing")
        self.assertFalse(report.ready)
        self.assertIn("missing artifact", report.blockers[0])
        self.assertIn("--platform windows --run", report.nextCommands[0])

    def test_portable_package_report_requires_checksum_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "culvia.zip"
            artifact.write_bytes(b"payload")

            with patch(
                "tools.release_status_report.check_portable_package_preflight.collect_windows_zip_checks",
                return_value=[self.check_result("windows portable zip artifact exists")],
            ):
                report = release_status_report.portable_package_report(
                    key="windows",
                    label="Windows portable zip",
                    artifact=artifact,
                    preflight_arg="--windows-zip",
                    native_platform="windows",
                    root=root,
                )

        self.assertEqual(report.status, "blocked")
        self.assertFalse(report.ready)
        self.assertIn("missing checksum", report.blockers[0])
        self.assertIn("write_release_checksum.py", report.nextCommands[-1])

    def test_portable_package_report_accepts_matching_checksum_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "culvia.zip"
            artifact.write_bytes(b"payload")
            self.write_checksum_and_evidence(artifact)

            with (
                patch(
                    "tools.release_status_report.check_portable_package_preflight.collect_windows_zip_checks",
                    return_value=[self.check_result("windows portable zip artifact exists")],
                ),
                patch(
                    "tools.release_status_report.portable_package_runtime_tool",
                    side_effect=AssertionError("runtime smoke must be lazy unless launch_runtime is enabled"),
                ),
            ):
                report = release_status_report.portable_package_report(
                    key="windows",
                    label="Windows portable zip",
                    artifact=artifact,
                    preflight_arg="--windows-zip",
                    native_platform="windows",
                    root=root,
                )

        self.assertEqual(report.status, "partial")
        self.assertFalse(report.ready)
        self.assertTrue(any("release checksum matches" in item for item in report.evidence))
        self.assertTrue(any("release evidence manifest matches" in item for item in report.evidence))
        self.assertIn("runtime launch not executed on native windows runner", report.blockers)

    def test_portable_package_report_requires_evidence_manifest_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "culvia.zip"
            artifact.write_bytes(b"payload")
            digest = release_status_report.write_release_checksum.sha256_file(artifact)
            Path(str(artifact) + ".sha256").write_text(
                release_status_report.write_release_checksum.checksum_text(digest=digest, artifact=artifact),
                encoding="utf-8",
            )

            with patch(
                "tools.release_status_report.check_portable_package_preflight.collect_windows_zip_checks",
                return_value=[self.check_result("windows portable zip artifact exists")],
            ):
                report = release_status_report.portable_package_report(
                    key="windows",
                    label="Windows portable zip",
                    artifact=artifact,
                    preflight_arg="--windows-zip",
                    native_platform="windows",
                    root=root,
                )

        self.assertEqual(report.status, "blocked")
        self.assertFalse(report.ready)
        self.assertIn("missing evidence manifest", report.blockers[0])
        self.assertIn("--platform windows --run", report.nextCommands[-1])

    def test_portable_package_report_loads_runtime_smoke_only_for_launch_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "culvia.zip"
            artifact.write_bytes(b"payload")
            self.write_checksum_and_evidence(artifact)
            runtime_tool = SimpleNamespace(
                native_platform_key=lambda: "windows",
                collect_checks=lambda **_kwargs: [
                    self.check_result("windows portable zip launcher runs desktop fixture workflow")
                ],
                result_payload=lambda checks: {
                    "ok": True,
                    "failed": [],
                    "checks": [{"name": item.name, "ok": item.ok, "detail": item.detail} for item in checks],
                },
            )

            with (
                patch(
                    "tools.release_status_report.check_portable_package_preflight.collect_windows_zip_checks",
                    return_value=[self.check_result("windows portable zip artifact exists")],
                ),
                patch(
                    "tools.release_status_report.portable_package_runtime_tool",
                    return_value=runtime_tool,
                ) as lazy_tool,
            ):
                report = release_status_report.portable_package_report(
                    key="windows",
                    label="Windows portable zip",
                    artifact=artifact,
                    preflight_arg="--windows-zip",
                    native_platform="windows",
                    root=root,
                    launch_runtime=True,
                )

        lazy_tool.assert_called_once()
        self.assertEqual(report.status, "ready")
        self.assertTrue(report.ready)
        self.assertIn("passed: windows portable zip launcher runs desktop fixture workflow", report.evidence)

    def test_release_status_report_defers_runtime_smoke_imports(self) -> None:
        tree = ast.parse((ROOT / "tools" / "release_status_report.py").read_text(encoding="utf-8"))
        top_level_tool_imports = {
            alias.name
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module == "tools"
            for alias in node.names
        }

        self.assertNotIn("check_portable_package_runtime", top_level_tool_imports)
        self.assertNotIn("check_macos_app_launch_smoke", top_level_tool_imports)
        self.assertNotIn("check_secret_store_keychain_smoke", top_level_tool_imports)
        self.assertNotIn("prepare_runtime_fixture", top_level_tool_imports)

    def test_pip_distribution_payload_is_explicit_by_default(self) -> None:
        with patch(
            "tools.release_status_report.release_smoke.build_wheel",
            side_effect=AssertionError("release smoke must not run unless explicitly requested"),
        ):
            payload = release_status_report.pip_distribution_payload(run=False)

        self.assertFalse(payload["ok"])
        self.assertIn("pip distribution smoke not executed with --release-smoke", payload["failed"])
        self.assertTrue(any("--release-smoke" in command for command in payload["nextCommands"]))

    def test_pip_distribution_next_commands_include_release_extra_and_strict_sdist_twine_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = release_status_report.pip_distribution_payload(
                root=root,
                run=False,
                wheelhouse=root / "wheelhouse",
                dist_dir=root / "dist",
                install_venv=root / "install",
            )

        commands = "\n".join(payload["nextCommands"])
        self.assertIn("python -m venv", commands)
        self.assertIn("pip install -e '.[release]'", commands)
        self.assertIn("make python-release", commands)
        self.assertIn("--build-sdist", commands)
        self.assertIn("--twine-check", commands)
        self.assertIn("--strict", commands)

    def test_pip_distribution_defaults_to_root_dist_python(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = release_status_report.pip_distribution_payload(root=root, run=False)

        commands = "\n".join(payload["nextCommands"])
        self.assertIn(str(root / "dist" / "python"), commands)
        self.assertIn("--wheelhouse dist/python", commands)
        self.assertIn("--dist-dir dist/python", commands)

    def test_pip_distribution_payload_collects_wheel_install_and_sdist_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wheel = root / "culvia-0.1.0-py3-none-any.whl"
            sdist = root / "culvia-0.1.0.tar.gz"
            wheel.write_bytes(b"wheel")
            sdist.write_bytes(b"sdist")

            with (
                patch(
                    "tools.release_status_report.release_smoke.check_project_metadata",
                    return_value=[],
                ),
                patch(
                    "tools.release_status_report.release_smoke.build_wheel",
                    return_value=(wheel, [], []),
                ),
                patch(
                    "tools.release_status_report.release_smoke.check_wheel_archive",
                    return_value=[],
                ),
                patch(
                    "tools.release_status_report.release_smoke.install_and_check_wheel",
                    return_value=([], []),
                ),
                patch(
                    "tools.release_status_report.release_smoke.build_sdist",
                    return_value=(sdist, [], []),
                ),
                patch(
                    "tools.release_status_report.release_smoke.check_sdist_archive",
                    return_value=[],
                ),
            ):
                payload = release_status_report.pip_distribution_payload(
                    root=root,
                    run=True,
                    build_sdist=True,
                    wheelhouse=root / "wheelhouse",
                    dist_dir=root / "dist",
                    install_venv=root / "install",
                )

        self.assertTrue(payload["ok"])
        self.assertIn("wheel builds with pip --no-build-isolation", payload["passed"])
        self.assertIn("installed wheel entrypoints and web data work", payload["passed"])
        self.assertIn("sdist contains source files and no runtime artifacts", payload["passed"])

    def test_pip_distribution_payload_requires_sdist_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wheel = root / "culvia-0.1.0-py3-none-any.whl"
            wheel.write_bytes(b"wheel")

            with (
                patch(
                    "tools.release_status_report.release_smoke.check_project_metadata",
                    return_value=[],
                ),
                patch(
                    "tools.release_status_report.release_smoke.build_wheel",
                    return_value=(wheel, [], []),
                ),
                patch(
                    "tools.release_status_report.release_smoke.check_wheel_archive",
                    return_value=[],
                ),
                patch(
                    "tools.release_status_report.release_smoke.install_and_check_wheel",
                    return_value=([], []),
                ),
            ):
                payload = release_status_report.pip_distribution_payload(
                    root=root,
                    run=True,
                    wheelhouse=root / "wheelhouse",
                    install_venv=root / "install",
                )

        self.assertFalse(payload["ok"])
        self.assertIn("sdist release smoke executed", payload["failed"])
        self.assertIn("sdist contains source files and no runtime artifacts", payload["failed"])

    def test_collect_report_aggregates_platform_and_environment_blockers(self) -> None:
        macos = release_status_report.PlatformReport(
            key="macos",
            label="macOS",
            status="ready",
            ready=True,
            evidence=["passed"],
            blockers=[],
            nextCommands=[],
        )
        windows = release_status_report.PlatformReport(
            key="windows",
            label="Windows",
            status="missing",
            ready=False,
            evidence=[],
            blockers=["missing artifact"],
            nextCommands=["python tools/desktop_release_contract.py --platform windows --run --json"],
        )
        linux = release_status_report.PlatformReport(
            key="linux",
            label="Linux",
            status="ready",
            ready=True,
            evidence=["passed"],
            blockers=[],
            nextCommands=[],
        )

        with (
            patch(
                "tools.release_status_report.check_desktop_readiness.result_payload",
                return_value={"ok": True, "failed": [], "skipped": []},
            ),
            patch(
                "tools.release_status_report.check_desktop_readiness.collect_checks",
                return_value=[],
            ),
            patch(
                "tools.release_status_report.check_desktop_release_workflow.result_payload",
                return_value={"ok": True, "failed": []},
            ),
            patch(
                "tools.release_status_report.check_desktop_release_workflow.collect_checks",
                return_value=[],
            ),
            patch("tools.release_status_report.macos_report", return_value=macos),
            patch(
                "tools.release_status_report.windows_report",
                return_value=windows,
            ),
            patch("tools.release_status_report.linux_report", return_value=linux),
            patch(
                "tools.release_status_report.release_environment",
                return_value={"gitRemoteConfigured": False, "ghAvailable": False},
            ),
        ):
            payload = release_status_report.collect_report(root=Path("/repo"))

        self.assertTrue(payload["betaReady"])
        self.assertFalse(payload["formalReady"])
        self.assertEqual(payload["estimatedRemaining"]["formal"], "local checks plus external release evidence")
        self.assertEqual(payload["estimatedRemaining"]["localActionable"], "1-2 local passes")
        self.assertEqual(payload["estimatedRemaining"]["externalRelease"], "1-2 release runs")
        self.assertIn("windows: missing artifact", payload["blockers"])
        self.assertIn("keychain: keychain smoke not executed with --keychain-smoke", payload["blockers"])
        self.assertIn("pip distribution: pip distribution smoke not executed with --release-smoke", payload["blockers"])
        self.assertIn("release environment: git remote is not configured", payload["blockers"])
        self.assertIn("release environment: gh CLI is not available", payload["blockers"])
        self.assertIn(
            "pip distribution: pip distribution smoke not executed with --release-smoke",
            payload["blockerSummary"]["localActionable"],
        )
        self.assertIn("windows: missing artifact", payload["blockerSummary"]["externalRequired"])
        self.assertIn(
            "keychain: keychain smoke not executed with --keychain-smoke", payload["blockerSummary"]["externalRequired"]
        )
        self.assertIn("release environment: gh CLI is not available", payload["blockerSummary"]["environment"])
        self.assertTrue(
            any("--release-smoke" in command for command in payload["nextCommandsByCategory"]["localActionable"])
        )
        self.assertTrue(
            any(
                "--platform windows --run" in command
                for command in payload["nextCommandsByCategory"]["externalRequired"]
            )
        )
        self.assertIn("install GitHub CLI, then run gh auth login", payload["nextCommandsByCategory"]["environment"])
        self.assertTrue(any("--platform windows --run" in command for command in payload["nextCommands"]))
        self.assertEqual(
            payload["gates"]["keychainSmoke"]["nextCommands"],
            ["python tools/check_secret_store_keychain_smoke.py --allow-write --preserve-existing --json"],
        )
        self.assertFalse(payload["gates"]["pipDistribution"]["ok"])

    def test_collect_report_macos_focus_defers_windows_and_linux_blockers(self) -> None:
        macos = release_status_report.PlatformReport(
            key="macos",
            label="macOS",
            status="ready",
            ready=True,
            evidence=["passed"],
            blockers=[],
            nextCommands=[],
        )
        windows = release_status_report.PlatformReport(
            key="windows",
            label="Windows",
            status="missing",
            ready=False,
            evidence=[],
            blockers=["missing artifact"],
            nextCommands=["python tools/desktop_release_contract.py --platform windows --run --json"],
        )
        linux = release_status_report.PlatformReport(
            key="linux",
            label="Linux",
            status="missing",
            ready=False,
            evidence=[],
            blockers=["missing artifact"],
            nextCommands=["python tools/desktop_release_contract.py --platform linux --run --json"],
        )

        with (
            patch(
                "tools.release_status_report.check_desktop_readiness.result_payload",
                return_value={"ok": True, "failed": [], "skipped": []},
            ),
            patch(
                "tools.release_status_report.check_desktop_readiness.collect_checks",
                return_value=[],
            ),
            patch(
                "tools.release_status_report.check_desktop_release_workflow.result_payload",
                return_value={"ok": True, "failed": []},
            ),
            patch(
                "tools.release_status_report.check_desktop_release_workflow.collect_checks",
                return_value=[],
            ),
            patch(
                "tools.release_status_report.keychain_smoke_payload",
                return_value={"ok": True, "failed": [], "nextCommands": []},
            ),
            patch(
                "tools.release_status_report.pip_distribution_payload",
                return_value={
                    "ok": True,
                    "failed": [],
                    "skipped": [],
                    "passed": ["release smoke"],
                    "checks": [],
                    "nextCommands": [],
                },
            ),
            patch("tools.release_status_report.macos_report", return_value=macos),
            patch(
                "tools.release_status_report.windows_report",
                return_value=windows,
            ),
            patch(
                "tools.release_status_report.windows_lite_report",
                return_value=release_status_report.PlatformReport(
                    key="windowsLite",
                    label="Windows Lite",
                    status="ready",
                    ready=True,
                    evidence=["passed"],
                    blockers=[],
                    nextCommands=[],
                ),
            ),
            patch("tools.release_status_report.linux_report", return_value=linux),
            patch(
                "tools.release_status_report.linux_lite_report",
                return_value=release_status_report.PlatformReport(
                    key="linuxLite",
                    label="Linux Lite",
                    status="ready",
                    ready=True,
                    evidence=["passed"],
                    blockers=[],
                    nextCommands=[],
                ),
            ),
            patch(
                "tools.release_status_report.release_environment",
                return_value={"gitRemoteConfigured": True, "ghAvailable": True},
            ),
        ):
            payload = release_status_report.collect_report(root=Path("/repo"), focus="macos")

        self.assertEqual(payload["focus"], "macos")
        self.assertFalse(payload["formalReady"])
        self.assertTrue(payload["focusedReady"])
        self.assertEqual(payload["estimatedRemaining"]["formal"], "0")
        self.assertEqual(payload["blockers"], [])
        self.assertIn("windows: missing artifact", payload["deferredBlockers"])
        self.assertIn("linux: missing artifact", payload["deferredBlockers"])
        self.assertIn("windows: missing artifact", payload["blockerSummary"]["deferred"])
        self.assertNotIn("windows: missing artifact", payload["blockerSummary"]["externalRequired"])
        self.assertTrue(
            any("--platform windows --run" in command for command in payload["nextCommandsByCategory"]["deferred"])
        )
        self.assertFalse(any("--platform windows --run" in command for command in payload["nextCommands"]))

    def test_collect_report_checks_macos_before_release_smoke_side_effects(self) -> None:
        calls: list[str] = []
        macos = release_status_report.PlatformReport(
            key="macos",
            label="macOS",
            status="ready",
            ready=True,
            evidence=["passed"],
            blockers=[],
            nextCommands=[],
        )
        ready_report = release_status_report.PlatformReport(
            key="windows",
            label="Windows",
            status="ready",
            ready=True,
            evidence=["passed"],
            blockers=[],
            nextCommands=[],
        )

        def macos_report(**_kwargs: object) -> release_status_report.PlatformReport:
            calls.append("macos")
            return macos

        def pip_distribution(**_kwargs: object) -> dict[str, object]:
            calls.append("pip")
            return {
                "ok": True,
                "failed": [],
                "skipped": [],
                "passed": ["release smoke"],
                "checks": [],
                "nextCommands": [],
            }

        with (
            patch(
                "tools.release_status_report.check_desktop_readiness.result_payload",
                return_value={"ok": True, "failed": [], "skipped": []},
            ),
            patch(
                "tools.release_status_report.check_desktop_readiness.collect_checks",
                return_value=[],
            ),
            patch(
                "tools.release_status_report.check_desktop_release_workflow.result_payload",
                return_value={"ok": True, "failed": []},
            ),
            patch(
                "tools.release_status_report.check_desktop_release_workflow.collect_checks",
                return_value=[],
            ),
            patch(
                "tools.release_status_report.keychain_smoke_payload",
                return_value={"ok": True, "failed": [], "nextCommands": []},
            ),
            patch(
                "tools.release_status_report.macos_report",
                side_effect=macos_report,
            ),
            patch("tools.release_status_report.windows_report", return_value=ready_report),
            patch(
                "tools.release_status_report.linux_report",
                return_value=ready_report,
            ),
            patch(
                "tools.release_status_report.pip_distribution_payload",
                side_effect=pip_distribution,
            ),
            patch(
                "tools.release_status_report.release_environment",
                return_value={"gitRemoteConfigured": True, "ghAvailable": True},
            ),
        ):
            release_status_report.collect_report(root=Path("/repo"), release_smoke_run=True)

        self.assertLess(calls.index("macos"), calls.index("pip"))

    def test_collect_report_classifies_unrun_native_runtime_smoke_as_local_on_macos(self) -> None:
        macos = release_status_report.PlatformReport(
            key="macos",
            label="macOS",
            status="partial",
            ready=False,
            evidence=["passed"],
            blockers=[
                "macos app signature details",
                "app launch smoke runtime workflow not executed on native macOS runner",
            ],
            nextCommands=["python tools/check_macos_artifact_preflight.py --strict --json"],
        )
        windows = release_status_report.PlatformReport(
            key="windows",
            label="Windows",
            status="ready",
            ready=True,
            evidence=["passed"],
            blockers=[],
            nextCommands=[],
        )
        linux = release_status_report.PlatformReport(
            key="linux",
            label="Linux",
            status="ready",
            ready=True,
            evidence=["passed"],
            blockers=[],
            nextCommands=[],
        )

        with (
            patch(
                "tools.release_status_report.check_desktop_readiness.result_payload",
                return_value={"ok": True, "failed": [], "skipped": []},
            ),
            patch(
                "tools.release_status_report.check_desktop_readiness.collect_checks",
                return_value=[],
            ),
            patch(
                "tools.release_status_report.check_desktop_release_workflow.result_payload",
                return_value={"ok": True, "failed": []},
            ),
            patch(
                "tools.release_status_report.check_desktop_release_workflow.collect_checks",
                return_value=[],
            ),
            patch(
                "tools.release_status_report.keychain_smoke_payload",
                return_value={"ok": True, "failed": [], "nextCommands": []},
            ),
            patch(
                "tools.release_status_report.pip_distribution_payload",
                return_value={
                    "ok": True,
                    "failed": [],
                    "skipped": [],
                    "passed": ["release smoke"],
                    "checks": [],
                    "nextCommands": [],
                },
            ),
            patch("tools.release_status_report.macos_report", return_value=macos),
            patch(
                "tools.release_status_report.windows_report",
                return_value=windows,
            ),
            patch(
                "tools.release_status_report.windows_lite_report",
                return_value=release_status_report.PlatformReport(
                    key="windowsLite",
                    label="Windows Lite",
                    status="ready",
                    ready=True,
                    evidence=["passed"],
                    blockers=[],
                    nextCommands=[],
                ),
            ),
            patch("tools.release_status_report.linux_report", return_value=linux),
            patch(
                "tools.release_status_report.linux_lite_report",
                return_value=release_status_report.PlatformReport(
                    key="linuxLite",
                    label="Linux Lite",
                    status="ready",
                    ready=True,
                    evidence=["passed"],
                    blockers=[],
                    nextCommands=[],
                ),
            ),
            patch(
                "tools.release_status_report.release_environment",
                return_value={"gitRemoteConfigured": True, "ghAvailable": True},
            ),
            patch("tools.release_status_report.platform.system", return_value="Darwin"),
        ):
            payload = release_status_report.collect_report(root=Path("/repo"))

        self.assertIn(
            "macos: app launch smoke runtime workflow not executed on native macOS runner",
            payload["blockerSummary"]["localActionable"],
        )
        self.assertIn("macos: macos app signature details", payload["blockerSummary"]["externalRequired"])
        self.assertTrue(
            any("--launch-runtime" in command for command in payload["nextCommandsByCategory"]["localActionable"])
        )
        self.assertEqual(payload["estimatedRemaining"]["formal"], "local checks plus external release evidence")

    def test_collect_report_accepts_explicit_keychain_smoke_evidence(self) -> None:
        macos = release_status_report.PlatformReport(
            key="macos",
            label="macOS",
            status="ready",
            ready=True,
            evidence=["passed"],
            blockers=[],
            nextCommands=[],
        )
        windows = release_status_report.PlatformReport(
            key="windows",
            label="Windows",
            status="ready",
            ready=True,
            evidence=["passed"],
            blockers=[],
            nextCommands=[],
        )
        linux = release_status_report.PlatformReport(
            key="linux",
            label="Linux",
            status="ready",
            ready=True,
            evidence=["passed"],
            blockers=[],
            nextCommands=[],
        )
        keychain_tool = SimpleNamespace(
            collect_checks=lambda allow_write, preserve_existing: (
                [self.check_result("temporary sentinel can be saved and read")],
                {"backend": "FakeKeyring", "restored": True, "original_label": ""},
            ),
            result_payload=lambda checks, **_metadata: {
                "ok": True,
                "failed": [],
                "checks": [{"name": item.name, "ok": item.ok, "detail": item.detail} for item in checks],
            },
        )

        with (
            patch(
                "tools.release_status_report.check_desktop_readiness.result_payload",
                return_value={"ok": True, "failed": [], "skipped": []},
            ),
            patch(
                "tools.release_status_report.check_desktop_readiness.collect_checks",
                return_value=[],
            ),
            patch(
                "tools.release_status_report.check_desktop_release_workflow.result_payload",
                return_value={"ok": True, "failed": []},
            ),
            patch(
                "tools.release_status_report.check_desktop_release_workflow.collect_checks",
                return_value=[],
            ),
            patch("tools.release_status_report.macos_report", return_value=macos),
            patch(
                "tools.release_status_report.windows_report",
                return_value=windows,
            ),
            patch(
                "tools.release_status_report.windows_lite_report",
                return_value=release_status_report.PlatformReport(
                    key="windowsLite",
                    label="Windows Lite",
                    status="ready",
                    ready=True,
                    evidence=["passed"],
                    blockers=[],
                    nextCommands=[],
                ),
            ),
            patch("tools.release_status_report.linux_report", return_value=linux),
            patch(
                "tools.release_status_report.linux_lite_report",
                return_value=release_status_report.PlatformReport(
                    key="linuxLite",
                    label="Linux Lite",
                    status="ready",
                    ready=True,
                    evidence=["passed"],
                    blockers=[],
                    nextCommands=[],
                ),
            ),
            patch(
                "tools.release_status_report.release_environment",
                return_value={"gitRemoteConfigured": True, "ghAvailable": True},
            ),
            patch("tools.release_status_report.keychain_smoke_tool", return_value=keychain_tool),
            patch(
                "tools.release_status_report.pip_distribution_payload",
                return_value={
                    "ok": True,
                    "failed": [],
                    "skipped": [],
                    "passed": ["release smoke"],
                    "checks": [],
                    "nextCommands": [],
                },
            ),
        ):
            payload = release_status_report.collect_report(root=Path("/repo"), keychain_smoke=True)

        self.assertTrue(payload["formalReady"])
        self.assertEqual(payload["estimatedRemaining"]["formal"], "0")
        self.assertEqual(payload["estimatedRemaining"]["localActionable"], "0")
        self.assertEqual(payload["estimatedRemaining"]["externalRelease"], "0")
        self.assertTrue(payload["gates"]["keychainSmoke"]["ok"])
        self.assertEqual(payload["gates"]["keychainSmoke"]["failed"], [])
        self.assertTrue(payload["gates"]["pipDistribution"]["ok"])
        self.assertEqual(payload["blockerSummary"], {"localActionable": [], "externalRequired": [], "environment": []})
        self.assertEqual(
            payload["nextCommandsByCategory"], {"localActionable": [], "externalRequired": [], "environment": []}
        )

    def test_text_report_prints_blocker_categories_and_category_commands(self) -> None:
        payload = {
            "betaReady": True,
            "formalReady": False,
            "estimatedRemaining": {"beta": "0", "formal": "1-2"},
            "platforms": {},
            "blockers": ["pip distribution: not executed"],
            "blockerSummary": {
                "localActionable": ["pip distribution: not executed"],
                "externalRequired": ["windows: missing artifact"],
                "environment": ["release environment: gh CLI is not available"],
            },
            "nextCommandsByCategory": {
                "localActionable": ["python tools/release_status_report.py --release-smoke --build-sdist --json"],
                "externalRequired": ["python tools/desktop_release_contract.py --platform windows --run --json"],
                "environment": ["install GitHub CLI, then run gh auth login"],
            },
        }
        stdout = io.StringIO()

        with patch("sys.stdout", stdout):
            release_status_report.print_text_report(payload)

        output = stdout.getvalue()
        self.assertIn("Local actionable blockers:", output)
        self.assertIn("External required blockers:", output)
        self.assertIn("Environment blockers:", output)
        self.assertIn("next: python tools/desktop_release_contract.py --platform windows --run --json", output)

    def test_main_strict_fails_when_formal_ready_is_false(self) -> None:
        payload = {
            "betaReady": True,
            "formalReady": False,
            "estimatedRemaining": {"beta": "0", "formal": "1-2"},
            "platforms": {},
            "blockers": ["missing artifact"],
        }
        stdout = io.StringIO()

        with patch("tools.release_status_report.collect_report", return_value=payload), patch("sys.stdout", stdout):
            result = release_status_report.main(["--strict", "--json"])

        self.assertEqual(result, 1)
        self.assertFalse(json.loads(stdout.getvalue())["formalReady"])

    def test_main_passes_focus_to_collect_report(self) -> None:
        payload = {
            "focus": "macos",
            "betaReady": True,
            "formalReady": False,
            "focusedReady": True,
            "estimatedRemaining": {"beta": "0", "formal": "0"},
            "platforms": {},
            "blockers": [],
            "deferredBlockers": ["windows: missing artifact"],
            "blockerSummary": {
                "localActionable": [],
                "externalRequired": [],
                "environment": [],
                "deferred": ["windows: missing artifact"],
            },
            "nextCommandsByCategory": {
                "localActionable": [],
                "externalRequired": [],
                "environment": [],
                "deferred": [],
            },
            "nextCommands": [],
        }
        stdout = io.StringIO()

        with (
            patch("tools.release_status_report.collect_report", return_value=payload) as collect_report,
            patch(
                "sys.stdout",
                stdout,
            ),
        ):
            result = release_status_report.main(["--focus", "macos", "--json"])

        self.assertEqual(result, 0)
        self.assertEqual(json.loads(stdout.getvalue())["focus"], "macos")
        self.assertEqual(collect_report.call_args.kwargs["focus"], "macos")

    def test_main_strict_uses_focused_ready_for_macos_focus(self) -> None:
        payload = {
            "focus": "macos",
            "betaReady": True,
            "formalReady": False,
            "focusedReady": True,
            "estimatedRemaining": {"beta": "0", "formal": "0"},
            "platforms": {},
            "blockers": [],
            "deferredBlockers": ["windows: missing artifact"],
            "blockerSummary": {
                "localActionable": [],
                "externalRequired": [],
                "environment": [],
                "deferred": ["windows: missing artifact"],
            },
            "nextCommandsByCategory": {
                "localActionable": [],
                "externalRequired": [],
                "environment": [],
                "deferred": [],
            },
            "nextCommands": [],
        }

        with (
            patch("tools.release_status_report.collect_report", return_value=payload),
            patch("sys.stdout", io.StringIO()),
        ):
            result = release_status_report.main(["--focus", "macos", "--strict", "--json"])

        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
