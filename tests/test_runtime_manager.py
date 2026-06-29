from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from culvia import runtime_manager


class RuntimeManagerTests(unittest.TestCase):
    def test_default_runtime_paths_use_app_managed_venv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {"CULVIA_RUNTIME_HOME": str(Path(tmp) / "runtime")}

            self.assertEqual(runtime_manager.runtime_home(env), Path(tmp) / "runtime")
            self.assertEqual(runtime_manager.default_venv_path(env), Path(tmp) / "runtime" / "venv")

    def test_explicit_runtime_venv_overrides_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "CULVIA_RUNTIME_HOME": str(Path(tmp) / "runtime"),
                "CULVIA_RUNTIME_VENV": str(Path(tmp) / "custom-venv"),
            }

            self.assertEqual(runtime_manager.default_venv_path(env), Path(tmp) / "custom-venv")

    def test_runtime_config_can_persist_lite_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {"CULVIA_RUNTIME_CONFIG": str(Path(tmp) / "runtime.json")}

            payload = runtime_manager.configure_runtime(
                mode="lite",
                python=Path("/opt/python/bin/python3.11"),
                venv=Path("/tmp/culvia-venv"),
                package="culvia[desktop-runtime]==1.2.3",
                auto_install=False,
                env=env,
            )
            config = runtime_manager.load_runtime_config(env=env)

        self.assertTrue(payload["ok"])
        self.assertEqual(config.mode, "lite")
        self.assertEqual(config.python, "/opt/python/bin/python3.11")
        self.assertEqual(config.venv, "/tmp/culvia-venv")
        self.assertEqual(config.package, "culvia[desktop-runtime]==1.2.3")
        self.assertFalse(config.auto_install)

    def test_configured_venv_and_python_are_used_before_defaults(self) -> None:
        config = runtime_manager.RuntimeConfig(
            python="/configured/python",
            venv="/configured/venv",
            package="culvia[desktop-runtime]==4.5.6",
        )

        self.assertEqual(runtime_manager.default_venv_path({}, config=config), Path("/configured/venv"))
        self.assertEqual(runtime_manager.python_candidate_commands({}, config=config)[0], ("/configured/python",))
        self.assertEqual(
            runtime_manager.package_install_args(
                runtime_manager.profile_by_name("desktop-lite"), env={}, config=config
            ),
            ["culvia[desktop-runtime]==4.5.6"],
        )

    def test_environment_overrides_runtime_config(self) -> None:
        config = runtime_manager.RuntimeConfig(python="/configured/python", venv="/configured/venv")
        env = {
            "CULVIA_RUNTIME_PYTHON": "/env/python",
            "CULVIA_RUNTIME_VENV": "/env/venv",
        }

        self.assertEqual(runtime_manager.default_venv_path(env, config=config), Path("/env/venv"))
        self.assertEqual(runtime_manager.python_candidate_commands(env, config=config)[0], ("/env/python",))

    def test_python_candidate_commands_respect_configured_python(self) -> None:
        commands = runtime_manager.python_candidate_commands({"CULVIA_RUNTIME_PYTHON": "/opt/python/bin/python3"})

        self.assertEqual(commands[0], ("/opt/python/bin/python3",))
        self.assertGreater(len(commands), 1)

    def test_package_install_args_prefer_explicit_package(self) -> None:
        profile = runtime_manager.profile_by_name("desktop-lite")

        self.assertEqual(
            runtime_manager.package_install_args(profile, package="culvia==1.2.3"),
            ["culvia==1.2.3"],
        )

    def test_package_install_args_support_editable_source_with_profile_extra(self) -> None:
        profile = runtime_manager.profile_by_name("desktop-lite")

        self.assertEqual(
            runtime_manager.package_install_args(profile, editable_source=Path("/repo/culvia")),
            ["-e", "/repo/culvia[desktop-runtime]"],
        )

    def test_module_status_reports_missing_modules_without_importing_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            python = Path(tmp) / "python"

            status = runtime_manager.module_status(python, ("culvia", "starlette"))

        self.assertFalse(status["ok"])
        self.assertEqual(status["missing"], ["culvia", "starlette"])

    def test_doctor_payload_marks_runtime_not_ready_when_modules_are_missing(self) -> None:
        profile = runtime_manager.profile_by_name("desktop-lite")
        with tempfile.TemporaryDirectory() as tmp:
            env = {"CULVIA_RUNTIME_HOME": str(Path(tmp) / "runtime")}
            with (
                patch("culvia.runtime_manager.find_base_python") as find_base,
                patch("culvia.runtime_manager.module_status") as module_status,
            ):
                find_base.return_value = runtime_manager.PythonInfo(
                    command=("python3.11",),
                    executable="/usr/bin/python3.11",
                    version="3.11.9",
                    ok=True,
                )
                module_status.return_value = {
                    "ok": False,
                    "python": str(Path(tmp) / "runtime" / "venv" / "bin" / "python"),
                    "missing": ["culvia"],
                }

                payload = runtime_manager.doctor_payload(
                    profile=profile,
                    venv_path=Path(tmp) / "runtime" / "venv",
                    env=env,
                )

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["missingModules"], ["culvia"])
        self.assertEqual(payload["profile"]["name"], "desktop-lite")

    def test_cli_runtime_subcommand_dispatches_from_culvia_cli(self) -> None:
        from culvia import cli

        with patch("culvia.runtime_manager.main", return_value=0) as runtime_main:
            result = cli.main(["runtime", "doctor", "--json"])

        self.assertEqual(result, 0)
        runtime_main.assert_called_once_with(["doctor", "--json"])

    def test_cli_doctor_json_reports_not_ready_without_creating_venv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output: list[str] = []

            def fake_print(text: str) -> None:
                output.append(text)

            with patch("builtins.print", fake_print):
                result = runtime_manager.main(
                    [
                        "doctor",
                        "--venv",
                        str(Path(tmp) / "venv"),
                        "--json",
                    ]
                )

        self.assertEqual(result, 1)
        payload = json.loads("\n".join(output))
        self.assertFalse(payload["ok"])
        self.assertIn("missingModules", payload)

    def test_cli_configure_writes_runtime_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "runtime.json"
            with (
                patch.dict("os.environ", {"CULVIA_RUNTIME_CONFIG": str(config_path)}),
                patch("builtins.print"),
            ):
                result = runtime_manager.main(
                    [
                        "configure",
                        "--mode",
                        "lite",
                        "--python",
                        "/usr/local/bin/python3.11",
                        "--venv",
                        str(Path(tmp) / "venv"),
                        "--package",
                        "culvia[desktop-runtime]==0.1.0",
                        "--no-auto-install",
                        "--json",
                    ]
                )
                config = runtime_manager.load_runtime_config()

        self.assertEqual(result, 0)
        self.assertEqual(config.mode, "lite")
        self.assertEqual(config.python, "/usr/local/bin/python3.11")
        self.assertFalse(config.auto_install)


if __name__ == "__main__":
    unittest.main()
