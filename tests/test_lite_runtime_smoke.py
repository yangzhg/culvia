from __future__ import annotations

import io
import json
import os
import select
import signal
import subprocess
import sys
import tempfile
import unittest
from collections import deque
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

from tools import lite_runtime_smoke as smoke


class LiteRuntimeSmokeTests(unittest.TestCase):
    def make_inputs(self, root: Path) -> dict[str, object]:
        launcher = root / "Culvia"
        launcher.write_text("desktop fixture", encoding="utf-8")
        wheel = root / "candidate wheels" / "culvia-0.2.0-py3-none-any.whl"
        wheel.parent.mkdir()
        wheel.write_bytes(b"candidate wheel")
        work_dir = root / "isolated-work"
        work_dir.mkdir()
        return {
            "launcher": launcher,
            "wheel": wheel,
            "python": Path(sys.executable),
            "work_dir": work_dir,
            "expected_version": "0.2.0",
            "expected_target": "aarch64-apple-darwin",
        }

    def probe_payload(self, inputs: dict[str, object]) -> dict[str, object]:
        venv = Path(inputs["work_dir"]) / "runtime" / "venv"
        return {
            "prefix": str(venv),
            "basePrefix": str(Path(sys.base_prefix)),
            "baseExecutable": str(inputs["python"]),
            "module": str(venv / "lib" / "python3.11" / "site-packages" / "culvia" / "__init__.py"),
            "distributionRoot": str(venv / "lib" / "python3.11" / "site-packages"),
            "version": "0.2.0",
            "moduleVersion": "0.2.0",
            "architecture": "arm64",
            "isolated": True,
            "userSiteEnabled": False,
            "origin": {
                "url": Path(inputs["wheel"]).as_uri(),
                "archive_info": {"hashes": {"sha256": smoke.sha256_file(Path(inputs["wheel"]))}},
            },
            "venvConfigSha256": "configuration-fingerprint",
            "venvConfigMtimeNs": 12345,
        }

    def validated_probe(self, inputs: dict[str, object], payload: dict[str, object]) -> dict[str, object]:
        checks = smoke.probe_checks(
            payload,
            venv=Path(inputs["work_dir"]) / "runtime" / "venv",
            python=Path(inputs["python"]),
            wheel=Path(inputs["wheel"]),
            wheel_sha256=smoke.sha256_file(Path(inputs["wheel"])),
            expected_version="0.2.0",
            expected_target="aarch64-apple-darwin",
        )
        return smoke.result(checks, runtime=payload)

    def fake_launch(
        self,
        inputs: dict[str, object],
        *,
        events=None,
        app_change=None,
        exit_timeout=False,
        shutdown_error="",
        reuse=False,
    ):
        process = MagicMock()
        process.returncode = 0
        process.poll.return_value = 0
        process.wait.return_value = 0
        if exit_timeout:
            process.wait.side_effect = subprocess.TimeoutExpired("desktop", 25)
            process.poll.return_value = None
        tree = MagicMock()
        tree.start.return_value = process
        tree.close.return_value = ""
        tree.process = process
        app = {
            "shellVersion": "0.2.0",
            "serviceVersion": "0.2.0",
            "desktopTarget": "aarch64-apple-darwin",
            "runtimeProfile": "lite",
            "distribution": "desktop",
            **(app_change or {}),
        }
        if events is None:
            events = [{"event": name, "baseUrl": "http://127.0.0.1:12345"} for name in smoke.REQUIRED_EVENTS]
        with ExitStack() as stack:
            stack.enter_context(patch.object(smoke, "ProcessTree", return_value=tree))
            fixture = stack.enter_context(
                patch.object(
                    smoke.prepare_runtime_fixture,
                    "write_fixture",
                    side_effect=lambda root, **_: {"root": str(root), "env": {}},
                )
            )
            stack.enter_context(patch.object(smoke, "wait_for_lite_events", return_value=events))
            stack.enter_context(
                patch.object(smoke.desktop_smoke, "wait_for_backend_shutdown", side_effect=[shutdown_error, ""])
            )
            request = stack.enter_context(patch.object(smoke.workflow, "request_json", return_value={"app": app}))
            workflow = stack.enter_context(
                patch.object(
                    smoke.workflow,
                    "collect_workflow_checks",
                    return_value=[smoke.workflow.check("fixture workflow", True, "passed")],
                )
            )
            payload = smoke.run_launch(**inputs, timeout=900, exit_after_ms=20000, reuse=reuse)
        return payload, tree, fixture, request, workflow

    def test_environment_removes_inherited_selectors_credentials_and_pip_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = self.make_inputs(root)
            contaminated = {
                "PATH": "/usr/bin",
                "SystemRoot": "C:\\Windows",
                "DISPLAY": ":17",
                "CULVIA_RUNTIME_VENV": "/existing-runtime",
                "CULVIA_RUNTIME_SKIP_INSTALL": "1",
                "CULVIA_DESKTOP_RUNTIME_MODE": "full",
                "CULVIA_DESKTOP_APP_VERSION": "wrong",
                "CULVIA_WEB_DIR": "/checkout/web",
                "CULVIA_BACKEND_PATH": "/foreign/backend",
                "CULVIA_LLM_API_KEY": "do-not-inherit",
                "OPENAI_API_KEY": "also-private",
                "ANTHROPIC_BASE_URL": "https://private.example.test",
                "PYTHONPATH": "/checkout",
                "PYTHONHOME": "/other-python",
                "PYTHONUSERBASE": "/user-site",
                "PIP_INDEX_URL": "https://private:credential@example.test/simple",
                "PIP_TARGET": "/other-target",
                "PIP_PREFIX": "/other-prefix",
                "PIP_CONSTRAINT": "/other-constraint",
                "PIP_CONFIG_FILE": "/personal-pip.conf",
                "UV_INDEX_URL": "https://other.example.test",
                "VIRTUAL_ENV": "/active-venv",
                "CONDA_PREFIX": "/active-conda",
                "GH_TOKEN": "private-token",
            }
            fixture = {"env": {"CULVIA_STATE_DIR": str(root / "fixture-state")}}
            env = smoke.launch_environment(
                fixture,
                work_dir=Path(inputs["work_dir"]),
                wheel=Path(inputs["wheel"]),
                python=Path(inputs["python"]),
                timeout=901.2,
                exit_after_ms=20000,
                reuse=False,
                environ=contaminated,
            )
            for key in contaminated.keys() - {
                "PATH",
                "SystemRoot",
                "DISPLAY",
                "CULVIA_RUNTIME_VENV",
                "PIP_CONFIG_FILE",
            }:
                self.assertNotIn(key, env)
            self.assertEqual(env["PATH"], contaminated["PATH"])
            self.assertEqual(env["SystemRoot"], contaminated["SystemRoot"])
            self.assertEqual(env["DISPLAY"], ":17")
            self.assertEqual(env["PIP_CONFIG_FILE"], os.devnull)
            self.assertEqual(env["PIP_NO_CACHE_DIR"], "1")
            self.assertEqual(env["PYTHONNOUSERSITE"], "1")
            self.assertEqual(env["PYTHONSAFEPATH"], "1")
            self.assertEqual(env["CULVIA_DISABLE_KEYCHAIN"], "1")
            self.assertEqual(env["CULVIA_DESKTOP_READY_TIMEOUT_SECS"], "902")
            self.assertEqual(env["CULVIA_STATE_DIR"], fixture["env"]["CULVIA_STATE_DIR"])
            for key in ("CULVIA_RUNTIME_HOME", "CULVIA_RUNTIME_CONFIG", "CULVIA_RUNTIME_VENV"):
                self.assertTrue(Path(env[key]).is_relative_to(Path(inputs["work_dir"])))
            self.assertFalse(Path(env["CULVIA_RUNTIME_VENV"]).exists())

    def test_candidate_wheel_with_spaces_is_one_requirement_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inputs = self.make_inputs(Path(tmp))
            env = smoke.launch_environment(
                {"env": {}},
                work_dir=Path(inputs["work_dir"]),
                wheel=Path(inputs["wheel"]),
                python=Path(inputs["python"]),
                timeout=900,
                exit_after_ms=20000,
                reuse=True,
                environ={},
            )
        requirement = env["CULVIA_RUNTIME_PACKAGE"]
        self.assertEqual(len(requirement.split()), 1)
        self.assertIn("candidate%20wheels", requirement)
        self.assertTrue(requirement.startswith("culvia[desktop-runtime]@file:///"))
        self.assertEqual(env["CULVIA_RUNTIME_SKIP_INSTALL"], "1")
        self.assertNotIn("CULVIA_DESKTOP_RUNTIME_MODE", env)

    def test_api_identity_requires_version_target_profile_and_distribution(self) -> None:
        app = {
            "shellVersion": "0.2.0",
            "serviceVersion": "0.2.0",
            "desktopTarget": "aarch64-apple-darwin",
            "runtimeProfile": "lite",
            "distribution": "desktop",
        }
        self.assertTrue(
            all(
                item["ok"]
                for item in smoke.identity_checks({"app": app}, version="0.2.0", target="aarch64-apple-darwin")
            )
        )
        for field, wrong in (
            ("shellVersion", "0.1.0"),
            ("serviceVersion", "0.1.0"),
            ("desktopTarget", "x86_64-apple-darwin"),
            ("runtimeProfile", "full"),
            ("distribution", "python"),
        ):
            with self.subTest(field=field):
                checks = smoke.identity_checks(
                    {"app": {**app, field: wrong}}, version="0.2.0", target="aarch64-apple-darwin"
                )
                self.assertEqual(
                    [item["name"] for item in checks if not item["ok"]], [f"app {field} matches candidate"]
                )

    def test_probe_accepts_only_exact_wheel_version_architecture_and_isolated_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inputs = self.make_inputs(Path(tmp))
            payload = self.probe_payload(inputs)
            self.assertTrue(self.validated_probe(inputs, payload)["ok"])
            for wrong in (
                {"version": "0.1.0"},
                {"moduleVersion": "0.1.0"},
                {"architecture": "x86_64"},
                {"module": str(smoke.ROOT / "culvia" / "__init__.py")},
                {"distributionRoot": "/other-site"},
                {"prefix": str(inputs["work_dir"])},
                {"baseExecutable": "/another/python"},
                {"isolated": False},
                {"userSiteEnabled": True},
                {"origin": None},
                {"origin": {"url": "https://example.test/culvia.whl"}},
                {"origin": {"url": Path(inputs["wheel"]).as_uri(), "archive_info": {"hashes": {"sha256": "wrong"}}}},
                {"origin": {"url": Path(inputs["wheel"]).as_uri(), "dir_info": {"editable": True}}},
            ):
                with self.subTest(wrong=wrong):
                    self.assertFalse(self.validated_probe(inputs, {**payload, **wrong})["ok"])

    def test_first_launch_creates_runtime_and_second_launch_reuses_same_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inputs = self.make_inputs(Path(tmp))
            calls: list[dict[str, object]] = []

            def launch(**kwargs: object) -> dict[str, object]:
                calls.append(kwargs)
                venv = Path(kwargs["work_dir"]) / "runtime" / "venv"
                if not kwargs["reuse"]:
                    self.assertFalse(venv.exists())
                    venv.mkdir(parents=True)
                else:
                    self.assertTrue(venv.is_dir())
                return smoke.result([smoke.check("desktop workflow", True, "passed")], skipInstall=kwargs["reuse"])

            probe = self.validated_probe(inputs, self.probe_payload(inputs))
            with (
                patch.object(smoke, "run_launch", side_effect=launch),
                patch.object(smoke, "probe_runtime", return_value=probe),
            ):
                payload = smoke.run_lite_smoke(**inputs)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual([call["reuse"] for call in calls], [False, True])
        self.assertEqual(calls[0]["work_dir"], calls[1]["work_dir"])
        self.assertTrue(payload["reuseLaunch"]["skipInstall"])
        self.assertIn("second launch reuses unchanged installed runtime", [item["name"] for item in payload["checks"]])

    def test_failed_first_launch_or_origin_probe_never_runs_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for failed_launch in (True, False):
                case_root = Path(tmp) / str(failed_launch)
                case_root.mkdir()
                inputs = self.make_inputs(case_root)
                launched = smoke.result([smoke.check("desktop workflow", not failed_launch, "failure")])
                probe = self.validated_probe(inputs, {**self.probe_payload(inputs), "origin": None})
                with (
                    patch.object(smoke, "run_launch", return_value=launched) as launch,
                    patch.object(smoke, "probe_runtime", return_value=probe),
                ):
                    payload = smoke.run_lite_smoke(**inputs)
                self.assertFalse(payload["ok"])
                self.assertEqual(launch.call_count, 1)
                self.assertIsNone(payload["reuseLaunch"])

    def test_reuse_rejects_recreated_venv_even_when_version_and_origin_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inputs = self.make_inputs(Path(tmp))
            first = self.validated_probe(inputs, self.probe_payload(inputs))
            second = self.validated_probe(inputs, {**self.probe_payload(inputs), "venvConfigMtimeNs": 99999})
            with (
                patch.object(
                    smoke,
                    "run_launch",
                    side_effect=lambda **_: smoke.result([smoke.check("desktop workflow", True, "passed")]),
                ),
                patch.object(smoke, "probe_runtime", side_effect=[first, second]),
            ):
                payload = smoke.run_lite_smoke(**inputs)
        self.assertFalse(payload["ok"])
        self.assertIn("second launch reuses unchanged installed runtime", payload["failed"])

    def test_preexisting_work_directory_or_runtime_is_not_a_first_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inputs = self.make_inputs(Path(tmp))
            (Path(inputs["work_dir"]) / "runtime").mkdir()
            with patch.object(smoke, "run_launch") as launch:
                payload = smoke.run_lite_smoke(**inputs)
        self.assertFalse(payload["ok"])
        self.assertIsNone(payload["firstLaunch"])
        self.assertIsNone(payload["reuseLaunch"])
        launch.assert_not_called()

    def test_launch_requires_readiness_identity_workflow_normal_exit_and_backend_shutdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inputs = self.make_inputs(Path(tmp))
            payload, tree, fixture, _, workflow = self.fake_launch(inputs)
            self.assertTrue(payload["ok"], payload)
            self.assertEqual(fixture.call_args.args[0], Path(inputs["work_dir"]) / "first-fixture")
            self.assertEqual(tree.start.call_args.kwargs["cwd"], inputs["work_dir"])
            self.assertNotIn("CULVIA_RUNTIME_SKIP_INSTALL", tree.start.call_args.kwargs["env"])
            self.assertEqual(workflow.call_count, 1)
            tree.close.assert_called_once_with()
            reused, reuse_tree, reuse_fixture, _, _ = self.fake_launch(inputs, reuse=True)
            self.assertTrue(reused["ok"], reused)
            self.assertEqual(reuse_fixture.call_args.args[0], Path(inputs["work_dir"]) / "reuse-fixture")
            self.assertEqual(reuse_tree.start.call_args.kwargs["env"]["CULVIA_RUNTIME_SKIP_INSTALL"], "1")
            self.assertEqual(
                reuse_tree.start.call_args.kwargs["env"]["CULVIA_RUNTIME_VENV"],
                tree.start.call_args.kwargs["env"]["CULVIA_RUNTIME_VENV"],
            )

    def test_incomplete_readiness_cleans_up_without_running_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inputs = self.make_inputs(Path(tmp))
            payload, tree, _, request, workflow = self.fake_launch(inputs, events=[])
        self.assertFalse(payload["ok"])
        self.assertIn("desktop emits all ready events", payload["failed"])
        request.assert_not_called()
        workflow.assert_not_called()
        tree.close.assert_called_once_with()

    def test_terminal_events_before_or_between_ready_events_stop_the_queue_immediately(self) -> None:
        ready = [{"event": name, "baseUrl": "http://127.0.0.1:12345"} for name in smoke.REQUIRED_EVENTS]
        for name in ("backendError", "windowCreateError", "splashCreateError", "frontendReadyTimeout"):
            for prefix_size in (0, 1, 2):
                with self.subTest(event=name, prefix=prefix_size):
                    failure = {"event": name, "error": "Startup failed before readiness", "timeoutSeconds": 900}
                    prefix = ready[:prefix_size]
                    lines = ["pip install progress", "not JSON", json.dumps(["ignored"])]
                    lines.extend(json.dumps(event) for event in [*prefix, failure, *ready[prefix_size:]])
                    pending = MagicMock()
                    pending.get.side_effect = lines
                    process = MagicMock()
                    process.poll.return_value = None
                    with (
                        patch.object(smoke.queue, "Queue", return_value=pending),
                        patch.object(smoke.threading, "Thread"),
                    ):
                        events = smoke.wait_for_lite_events(
                            process, timeout=900, stdout_tail=deque(), stderr_tail=deque()
                        )
                    self.assertEqual(events, [*prefix, failure])
                    self.assertEqual(pending.get.call_count, 3 + len(prefix) + 1)
                    process.wait.assert_not_called()

    def test_waiter_preserves_failure_and_tail_from_a_live_process(self) -> None:
        failure = {"event": "backendError", "error": "The local service closed output before it became ready"}
        process = MagicMock()
        process.stdout = io.StringIO(json.dumps(failure) + "\n")
        process.stderr = io.StringIO("backend startup failed\n")
        process.poll.return_value = None
        stdout_tail: deque[str] = deque()
        events = smoke.wait_for_lite_events(process, timeout=900, stdout_tail=stdout_tail, stderr_tail=deque())
        self.assertEqual(events, [failure])
        self.assertIn(json.dumps(failure), stdout_tail)
        process.wait.assert_not_called()

    def test_waiter_drains_ready_events_even_when_process_already_exited(self) -> None:
        ready = [{"event": name, "baseUrl": "http://127.0.0.1:12345"} for name in smoke.REQUIRED_EVENTS]
        process = MagicMock()
        process.stdout = io.StringIO("\n".join(json.dumps(event) for event in ready) + "\n")
        process.stderr = io.StringIO("")
        process.poll.return_value = 0
        events = smoke.wait_for_lite_events(process, timeout=900, stdout_tail=deque(), stderr_tail=deque())
        self.assertEqual(events, ready)

    def test_terminal_failure_is_reported_and_cleans_up_without_waiting_for_auto_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inputs = self.make_inputs(Path(tmp))
            failure = {"event": "backendError", "error": "The local service closed output before it became ready"}
            payload, tree, _, request, workflow = self.fake_launch(inputs, events=[failure])
        self.assertFalse(payload["ok"])
        self.assertIn("desktop reports no startup failure", payload["failed"])
        self.assertEqual(payload["events"], [failure])
        self.assertEqual(payload["terminalEvents"], [failure])
        self.assertIn(
            failure["error"],
            next(item["detail"] for item in payload["checks"] if item["name"] == "desktop reports no startup failure"),
        )
        request.assert_not_called()
        workflow.assert_not_called()
        tree.process.wait.assert_not_called()
        tree.close.assert_called_once_with()

    def test_wrong_live_identity_never_mutates_the_unexpected_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inputs = self.make_inputs(Path(tmp))
            payload, tree, _, _, workflow = self.fake_launch(inputs, app_change={"serviceVersion": "0.1.0"})
        self.assertFalse(payload["ok"])
        self.assertIn("app serviceVersion matches candidate", payload["failed"])
        workflow.assert_not_called()
        tree.close.assert_called_once_with()

    def test_exit_timeout_and_surviving_backend_are_failures_even_after_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inputs = self.make_inputs(Path(tmp))
            payload, tree, _, _, _ = self.fake_launch(inputs, exit_timeout=True)
            self.assertFalse(payload["ok"])
            self.assertIn("desktop exits automatically", payload["failed"])
            tree.close.assert_called_once_with()
            payload, tree, _, _, _ = self.fake_launch(inputs, shutdown_error="backend still answered")
        self.assertFalse(payload["ok"])
        self.assertIn("desktop stops backend after exit", payload["failed"])
        tree.close.assert_called_once_with()

    def test_linux_without_display_uses_xvfb_and_keeps_launcher_argument_intact(self) -> None:
        with patch.object(smoke.shutil, "which", return_value="/usr/bin/xvfb-run"):
            command = smoke.launcher_command(
                Path("/tmp/app with spaces/culvia"), "x86_64-unknown-linux-gnu", {"PATH": "/usr/bin"}
            )
        self.assertEqual(command, ["/usr/bin/xvfb-run", "-a", "/tmp/app with spaces/culvia"])
        with patch.object(smoke.shutil, "which", return_value=None), self.assertRaisesRegex(ValueError, "DISPLAY"):
            smoke.launcher_command(Path("/tmp/app"), "x86_64-unknown-linux-gnu", {})

    def test_ready_event_must_not_target_external_service(self) -> None:
        for url in (
            "https://example.test",
            "http://example.test:1234",
            "http://user:secret@127.0.0.1:1234",
            "http://127.0.0.1:1234/path",
            "http://127.0.0.1:1234/?token=private",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                smoke.loopback_url([{"event": "backendReady", "baseUrl": url}])
        self.assertEqual(
            smoke.loopback_url([{"event": "backendReady", "baseUrl": "http://127.0.0.1:1234"}]), "http://127.0.0.1:1234"
        )

    def test_failure_evidence_redacts_credentials_in_nested_logs(self) -> None:
        original = {
            "stderrTail": [
                "https://username:password@example.test/simple?token=other-private",
                "failure sample-private-key",
            ]
        }
        payload = smoke.sanitize(original, {"sample-private-key"})
        serialized = json.dumps(payload)
        for private in ("username", "password", "other-private", "sample-private-key"):
            self.assertNotIn(private, serialized)
        self.assertIn("example.test", serialized)

    @unittest.skipIf(smoke.WINDOWS, "POSIX process-group signals")
    def test_posix_cleanup_kills_group_even_after_leader_exits(self) -> None:
        process = MagicMock()
        process.pid = 12345
        process.poll.return_value = 1
        process.wait.return_value = 1
        tree = smoke.ProcessTree()
        tree.process = process
        with patch.object(smoke.os, "killpg") as killpg:
            error = tree.close()
        self.assertEqual(error, "")
        self.assertEqual(killpg.call_args_list[0].args, (12345, signal.SIGTERM))
        self.assertEqual(killpg.call_args_list[-1].args, (12345, signal.SIGKILL))

    @unittest.skipIf(smoke.WINDOWS, "POSIX process-group ownership")
    def test_real_posix_cleanup_kills_stubborn_descendant_after_leader_exits(self) -> None:
        child = "import os,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print(os.getpid(),flush=True); time.sleep(60)"
        parent = f"import subprocess,sys; subprocess.Popen([sys.executable,'-u','-c',{child!r}])"
        with tempfile.TemporaryDirectory() as tmp:
            tree = smoke.ProcessTree()
            process = tree.start([sys.executable, "-u", "-c", parent], cwd=Path(tmp), env=dict(os.environ))
            try:
                readable, _, _ = select.select([process.stdout], [], [], 5)
                self.assertTrue(readable, "descendant did not become ready")
                child_pid = int(process.stdout.readline())
                os.kill(child_pid, 0)
                process.wait(timeout=5)
                self.assertEqual(process.returncode, 0)
                self.assertEqual(tree.close(), "")
                # An orphan that retained this pipe would make communicate time out.
                process.communicate(timeout=5)
                self.assertEqual(tree.close(), "")
            finally:
                tree.close()

    def test_windows_resumes_only_the_owned_suspended_thread_and_releases_handles(self) -> None:
        import ctypes

        job = smoke._WindowsJob.__new__(smoke._WindowsJob)
        job.ctypes = ctypes
        job.kernel = MagicMock()
        job.kernel.CreateToolhelp32Snapshot.return_value = 101
        job.kernel.OpenThread.return_value = 202
        job.kernel.ResumeThread.return_value = 1

        def entry(owner: int, thread_id: int):
            def fill(_snapshot, pointer):
                pointer._obj.th32OwnerProcessID = owner
                pointer._obj.th32ThreadID = thread_id
                return True

            return fill

        job.kernel.Thread32First.side_effect = entry(77, 88)
        job.kernel.Thread32Next.side_effect = entry(1234, 99)
        job.resume_initial_thread(1234)
        job.kernel.OpenThread.assert_called_once_with(0x0002, False, 99)
        job.kernel.ResumeThread.assert_called_once_with(202)
        self.assertEqual([call.args[0] for call in job.kernel.CloseHandle.call_args_list], [202, 101])

    def test_windows_assigns_suspended_process_to_job_before_resume_and_closes_job(self) -> None:
        process = MagicMock()
        process.wait.return_value = 0
        job = MagicMock()
        with (
            patch.object(smoke, "WINDOWS", True),
            patch.object(smoke, "_WindowsJob", return_value=job),
            patch.object(smoke.subprocess, "Popen", return_value=process) as popen,
        ):
            tree = smoke.ProcessTree()
            tree.start(["desktop.exe"], cwd=Path("/isolated"), env={})
            self.assertEqual(popen.call_args.kwargs["creationflags"] & 0x4, 0x4)
            job.assign_and_resume.assert_called_once_with(process)
            self.assertEqual(tree.close(), "")
        job.terminate.assert_called_once_with()
        job.close.assert_called_once_with()

    def test_windows_job_assignment_failure_kills_suspended_process(self) -> None:
        process = MagicMock()
        process.wait.side_effect = [subprocess.TimeoutExpired("desktop", 5), 1]
        job = MagicMock()
        job.assign_and_resume.side_effect = OSError("cannot assign")
        with (
            patch.object(smoke, "WINDOWS", True),
            patch.object(smoke, "_WindowsJob", return_value=job),
            patch.object(smoke.subprocess, "Popen", return_value=process),
        ):
            with self.assertRaisesRegex(OSError, "cannot assign"):
                smoke.ProcessTree().start(["desktop.exe"], cwd=Path("/isolated"), env={})
        process.kill.assert_called_once_with()
        job.close.assert_called_once_with()

    def test_probe_runs_isolated_python_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inputs = self.make_inputs(Path(tmp))
            venv = Path(inputs["work_dir"]) / "runtime" / "venv"
            executable = venv / ("Scripts/python.exe" if smoke.WINDOWS else "bin/python")
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"python fixture")
            process = MagicMock()
            process.returncode = 0
            process.communicate.return_value = (json.dumps(self.probe_payload(inputs)), "")
            with (
                patch.object(smoke.ProcessTree, "start", return_value=process) as start,
                patch.object(smoke.ProcessTree, "close", return_value=""),
            ):
                payload = smoke.probe_runtime(
                    venv=venv,
                    python=Path(inputs["python"]),
                    wheel=Path(inputs["wheel"]),
                    wheel_sha256=smoke.sha256_file(Path(inputs["wheel"])),
                    expected_version="0.2.0",
                    expected_target="aarch64-apple-darwin",
                    work_dir=Path(inputs["work_dir"]),
                    env={},
                )
            self.assertTrue(payload["ok"], payload)
            self.assertEqual(start.call_args.args[0][:3], [str(executable), "-I", "-c"])
            self.assertEqual(start.call_args.kwargs["cwd"], inputs["work_dir"])

    def test_probe_timeout_closes_owned_process_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            inputs = self.make_inputs(Path(tmp))
            venv = Path(inputs["work_dir"]) / "runtime" / "venv"
            executable = venv / ("Scripts/python.exe" if smoke.WINDOWS else "bin/python")
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"python fixture")
            process = MagicMock()
            process.communicate.side_effect = subprocess.TimeoutExpired("runtime probe", 30)
            with (
                patch.object(smoke.ProcessTree, "start", return_value=process),
                patch.object(smoke.ProcessTree, "close", return_value="") as close,
            ):
                payload = smoke.probe_runtime(
                    venv=venv,
                    python=Path(inputs["python"]),
                    wheel=Path(inputs["wheel"]),
                    wheel_sha256=smoke.sha256_file(Path(inputs["wheel"])),
                    expected_version="0.2.0",
                    expected_target="aarch64-apple-darwin",
                    work_dir=Path(inputs["work_dir"]),
                    env={},
                )
        self.assertFalse(payload["ok"])
        close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
