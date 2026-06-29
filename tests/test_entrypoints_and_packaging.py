from __future__ import annotations

import importlib
import io
import re
import sys
import tomllib
import unittest
from pathlib import Path
from urllib.parse import urlparse
from unittest.mock import patch

from culvia.supervisor import ServerTarget, SupervisorConfig
from tools import generate_app_icons


ROOT = Path(__file__).resolve().parents[1]


def normalized_markup(text: str) -> str:
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


class EntrypointAndPackagingTests(unittest.TestCase):
    def test_pyproject_scripts_point_to_importable_callables(self) -> None:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        scripts = data["project"]["scripts"]

        self.assertIn("culvia", scripts)
        self.assertIn("culvia-web", scripts)
        self.assertIn("culvia-supervisor", scripts)
        self.assertEqual(scripts["culvia"], "culvia.cli:main")
        for target in scripts.values():
            module_name, callable_name = target.split(":", 1)
            module = importlib.import_module(module_name)
            self.assertTrue(callable(getattr(module, callable_name)))

    def test_requirements_match_runtime_package_dependencies(self) -> None:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        pyproject_dependencies = {item.strip().lower() for item in data["project"]["dependencies"]}
        requirements = {
            line.strip().lower()
            for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

        self.assertEqual(requirements, pyproject_dependencies)

    def test_desktop_build_dependency_is_optional(self) -> None:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        runtime_dependencies = {item.strip().lower() for item in data["project"]["dependencies"]}
        desktop_dependencies = {item.strip().lower() for item in data["project"]["optional-dependencies"]["desktop"]}

        self.assertIn("pyinstaller>=6", desktop_dependencies)
        self.assertIn("keyring>=25", desktop_dependencies)
        self.assertNotIn("pyinstaller>=6", runtime_dependencies)
        self.assertNotIn("keyring>=25", runtime_dependencies)

    def test_release_dependency_is_optional(self) -> None:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        runtime_dependencies = {item.strip().lower() for item in data["project"]["dependencies"]}
        requirements = {
            line.strip().lower()
            for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        release_dependencies = {item.strip().lower() for item in data["project"]["optional-dependencies"]["release"]}

        for dependency in ("build>=1.2", "twine>=5", "wheel>=0.43"):
            self.assertIn(dependency, release_dependencies)
            self.assertNotIn(dependency, runtime_dependencies)
            self.assertNotIn(dependency, requirements)

    def test_development_dependency_is_optional(self) -> None:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        runtime_dependencies = {item.strip().lower() for item in data["project"]["dependencies"]}
        dev_dependencies = {item.strip().lower() for item in data["project"]["optional-dependencies"]["dev"]}

        for dependency in ("pre-commit>=3.7", "ruff>=0.8"):
            self.assertIn(dependency, dev_dependencies)
            self.assertNotIn(dependency, runtime_dependencies)

    def test_open_source_package_metadata_is_complete(self) -> None:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = data["project"]

        self.assertTrue((ROOT / "LICENSE").exists())
        self.assertEqual(project["license"], {"file": "LICENSE"})
        self.assertEqual(project["authors"], [{"name": "Culvia contributors"}])
        self.assertIn("photography", project["keywords"])
        self.assertIn("photo-culling", project["keywords"])
        self.assertIn("License :: OSI Approved :: MIT License", project["classifiers"])
        self.assertIn("Operating System :: MacOS", project["classifiers"])
        self.assertIn("Operating System :: Microsoft :: Windows", project["classifiers"])
        self.assertIn("Operating System :: POSIX :: Linux", project["classifiers"])
        for key in ("Homepage", "Documentation", "Issues", "Source"):
            self.assertTrue(project["urls"][key].startswith("https://"), key)

    def test_packaged_web_data_files_match_html_references(self) -> None:
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        data_files = data["tool"]["setuptools"]["data-files"]
        files = {file for group in data_files.values() for file in group}
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        html_static_files = {
            f"web/{urlparse(reference).path.removeprefix('/static/')}"
            for reference in re.findall(r'(?:href|src)="([^"]+)"', html)
            if urlparse(reference).path.startswith("/static/")
        }

        self.assertIn("web/index.html", files)
        self.assertTrue(html_static_files.issubset(files), sorted(html_static_files - files))
        self.assertIn("web/i18n_messages.js", files)
        self.assertIn("web/locales/zh-CN.js", files)
        self.assertIn("web/locales/en.js", files)
        self.assertIn("web/i18n.js", files)
        for relative_path in files:
            self.assertTrue((ROOT / relative_path).exists(), relative_path)

    def test_brand_icon_source_drives_web_favicon_and_sidebar_mark(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        icons_js = (ROOT / "web" / "icons.js").read_text(encoding="utf-8")
        splash_html = (ROOT / "desktop" / "tauri" / "src-tauri" / "assets" / "splash.html").read_text(encoding="utf-8")
        source_icon = ROOT / "assets" / "brand" / "culvia-icon.svg"

        self.assertEqual(
            source_icon.read_text(encoding="utf-8"),
            (ROOT / "web" / "favicon.svg").read_text(encoding="utf-8"),
        )
        self.assertIn(
            normalized_markup(generate_app_icons.splash_svg_markup(source_icon)),
            normalized_markup(splash_html),
        )
        self.assertIn('src="/static/favicon.svg"', html)
        self.assertNotIn("culviaMark", html)
        self.assertNotIn("culviaMark", icons_js)

    def test_web_entrypoint_parses_auto_port_without_starting_server(self) -> None:
        with patch("culvia.server.find_available_port", return_value=49200):
            import culvia.server

            config = culvia.server.parse_args(["--host", "127.0.0.1", "--port", "auto", "--reload"])

        self.assertEqual(config.target.host, "127.0.0.1")
        self.assertEqual(config.target.port, 49200)
        self.assertTrue(config.reload)

    def test_supervisor_entrypoint_delegates_to_supervisor(self) -> None:
        expected = SupervisorConfig(target=ServerTarget("127.0.0.1", 8501), open_browser=False)
        with (
            patch("culvia.supervisor.parse_args", return_value=expected),
            patch(
                "culvia.supervisor.run_supervisor",
                return_value=0,
            ) as run,
        ):
            import culvia.supervisor

            result = culvia.supervisor.main(["--no-open"])

        self.assertEqual(result, 0)
        run.assert_called_once_with(expected)

    def test_cli_entrypoint_delegates_to_package_batch_cli(self) -> None:
        import culvia.cli

        with patch("culvia.batch_cli.main", return_value=17) as batch_main:
            self.assertEqual(culvia.cli.main(["folder-a"]), 17)

        batch_main.assert_called_once_with(["folder-a"])

    def test_cli_help_does_not_import_scoring_dependencies(self) -> None:
        original = sys.modules.pop("culvia.scoring", None)
        try:
            sys.modules["culvia.scoring"] = None
            import culvia.cli

            stdout = io.StringIO()
            with patch("sys.stdout", stdout):
                result = culvia.cli.main(["--help"])

            self.assertEqual(result, 0)
            self.assertIn("照片审美与技术评分命令行工具", stdout.getvalue())
            self.assertIn("--cache", stdout.getvalue())
        finally:
            sys.modules.pop("culvia.scoring", None)
            if original is not None:
                sys.modules["culvia.scoring"] = original


if __name__ == "__main__":
    unittest.main()
