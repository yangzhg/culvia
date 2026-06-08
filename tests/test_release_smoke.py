from __future__ import annotations

import io
import tempfile
import tarfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools import release_smoke


ROOT = Path(__file__).resolve().parents[1]


def write_wheel_metadata(archive: zipfile.ZipFile, *, static_version: str | None = None) -> None:
    archive.writestr(
        "culvia-0.1.0.dist-info/METADATA",
        (
            "Metadata-Version: 2.4\n"
            "Name: culvia\n"
            "Version: 0.1.0\n"
            "License-File: LICENSE\n"
            "Project-URL: Homepage, https://github.com/yangzhg/culvia\n"
            "Project-URL: Documentation, https://github.com/yangzhg/culvia#readme\n"
            "Project-URL: Issues, https://github.com/yangzhg/culvia/issues\n"
            "Project-URL: Source, https://github.com/yangzhg/culvia\n"
            "Classifier: License :: OSI Approved :: MIT License\n"
            "Classifier: Operating System :: MacOS\n"
            "Classifier: Operating System :: Microsoft :: Windows\n"
            "Classifier: Operating System :: POSIX :: Linux\n"
            "\n"
        ),
    )
    archive.writestr("culvia-0.1.0.dist-info/licenses/LICENSE", "MIT License\n")
    if static_version is not None:
        archive.writestr("culvia-0.1.0.dist-info/static-version.txt", static_version)


def write_sdist(path: Path, names: list[str]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name in names:
            data = b"MIT License\n" if name.endswith("LICENSE") else b""
            info = tarfile.TarInfo(name=f"culvia-0.1.0/{name}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


class ReleaseSmokeTests(unittest.TestCase):
    def test_static_references_from_html_normalizes_static_urls(self) -> None:
        html = """
        <link href="/static/styles.css?v=1">
        <script src="/static/app.js#main"></script>
        <script src="/assets/ignored.js"></script>
        <script src="https://example.com/static/remote.js"></script>
        <script src="/static/app.js?v=2"></script>
        """

        self.assertEqual(
            release_smoke.static_references_from_html(html),
            {"styles.css", "app.js"},
        )

    def test_expected_web_data_files_follow_index_static_references(self) -> None:
        expected = release_smoke.expected_web_data_files(ROOT)

        self.assertIn("share/culvia/web/index.html", expected)
        self.assertIn("share/culvia/web/favicon.svg", expected)
        self.assertIn("share/culvia/web/i18n_messages.js", expected)
        self.assertIn("share/culvia/web/locales/zh-CN.js", expected)
        self.assertIn("share/culvia/web/i18n.js", expected)
        self.assertIn("share/culvia/web/styles.css", expected)
        self.assertIn("share/culvia/web/styles/00-foundation.css", expected)
        self.assertIn("share/culvia/web/app.js", expected)
        self.assertIn("share/culvia/web/app_config.js", expected)
        self.assertIn("share/culvia/web/distribution_view.js", expected)
        self.assertIn("share/culvia/web/viewer_inspector.js", expected)
        self.assertIn("share/culvia/web/icons.js", expected)
        self.assertIn("share/culvia/web/ui_helpers.js", expected)
        self.assertIn("share/culvia/web/gallery_view.js", expected)
        self.assertIn("share/culvia/web/llm_config_view.js", expected)
        self.assertIn("share/culvia/web/viewer_keyboard.js", expected)
        self.assertTrue(all(path.startswith("share/culvia/web/") for path in expected))

    def test_expected_web_source_files_follow_index_static_references(self) -> None:
        expected = release_smoke.expected_web_source_files(ROOT)

        self.assertIn("web/index.html", expected)
        self.assertIn("web/favicon.svg", expected)
        self.assertIn("web/app.js", expected)
        self.assertIn("web/app_config.js", expected)
        self.assertIn("web/distribution_view.js", expected)
        self.assertIn("web/viewer_inspector.js", expected)
        self.assertIn("web/ui_helpers.js", expected)
        self.assertIn("web/gallery_view.js", expected)
        self.assertIn("web/styles.css", expected)
        self.assertIn("web/styles/00-foundation.css", expected)
        self.assertIn("web/i18n_messages.js", expected)
        self.assertIn("web/locales/en.js", expected)
        self.assertIn("web/viewer_keyboard.js", expected)

    def test_missing_suffixes_matches_wheel_data_file_layout(self) -> None:
        names = [
            "culvia-0.1.0.data/data/share/culvia/web/index.html",
            "culvia-0.1.0.data/data/share/culvia/web/app.js",
        ]

        self.assertEqual(
            release_smoke.missing_suffixes(
                names,
                {
                    "share/culvia/web/index.html",
                    "share/culvia/web/app.js",
                    "share/culvia/web/styles.css",
                },
            ),
            ["share/culvia/web/styles.css"],
        )

    def test_runtime_artifact_detection_rejects_cache_and_database_files(self) -> None:
        names = [
            "culvia/settings.py",
            "model_cache/weights.bin",
            "culvia-0.1.0.data/data/share/culvia/web/app.js",
            "culvia_scores.sqlite",
            "culvia_scores.sqlite-wal",
            "export.csv",
            "culvia/__pycache__/settings.cpython-311.pyc",
        ]

        self.assertEqual(
            release_smoke.find_runtime_artifacts(names),
            sorted(
                [
                    "export.csv",
                    "model_cache/weights.bin",
                    "culvia/__pycache__/settings.cpython-311.pyc",
                    "culvia_scores.sqlite",
                    "culvia_scores.sqlite-wal",
                ]
            ),
        )

    def test_console_scripts_match_pyproject(self) -> None:
        self.assertEqual(
            release_smoke.expected_console_scripts(ROOT),
            {
                "culvia": "culvia.cli:main",
                "culvia-web": "culvia.server:main",
                "culvia-supervisor": "culvia.supervisor:main",
            },
        )

    def test_project_metadata_documents_open_source_distribution(self) -> None:
        self.assertEqual(release_smoke.check_project_metadata(ROOT), [])

    def test_release_extra_declares_strict_sdist_tools_without_runtime_coupling(self) -> None:
        data = release_smoke.load_pyproject(ROOT)
        runtime_names = {release_smoke.dependency_name(item) for item in data["project"]["dependencies"]}
        release_dependencies = data["project"]["optional-dependencies"]["release"]
        release_names = {release_smoke.dependency_name(item) for item in release_dependencies}

        self.assertEqual(release_smoke.REQUIRED_RELEASE_EXTRA_DEPENDENCIES, ("build>=1.2", "twine>=5", "wheel>=0.43"))
        for dependency in release_smoke.REQUIRED_RELEASE_EXTRA_DEPENDENCIES:
            self.assertIn(dependency, release_dependencies)
            self.assertIn(release_smoke.dependency_name(dependency), release_names)
            self.assertNotIn(release_smoke.dependency_name(dependency), runtime_names)

    def test_release_build_defaults_to_root_dist_python(self) -> None:
        parser = release_smoke.build_parser()
        args = parser.parse_args([])

        self.assertEqual(args.wheelhouse, ROOT / "dist" / "python")
        self.assertEqual(args.dist_dir, ROOT / "dist" / "python")

    def test_distribution_artifact_lines_collapses_shared_dist_dir(self) -> None:
        dist_dir = ROOT / "dist" / "python"
        lines = release_smoke.distribution_artifact_lines(
            wheel_path=dist_dir / "culvia-0.1.0-py3-none-any.whl",
            sdist_path=dist_dir / "culvia-0.1.0.tar.gz",
            wheelhouse=dist_dir,
            dist_dir=dist_dir,
            include_wheel_dir=True,
            include_sdist_dir=True,
        )

        self.assertEqual(
            lines,
            [
                f"  dist: {dist_dir}",
                f"  wheel: {dist_dir / 'culvia-0.1.0-py3-none-any.whl'}",
                f"  sdist: {dist_dir / 'culvia-0.1.0.tar.gz'}",
            ],
        )

    def test_entry_point_issues_reports_missing_and_mismatched_scripts(self) -> None:
        issues = release_smoke.entry_point_issues(
            {"culvia": "culvia.cli:main", "culvia-web": "wrong:main"},
            {
                "culvia": "culvia.cli:main",
                "culvia-web": "culvia.server:main",
                "culvia-supervisor": "culvia.supervisor:main",
            },
        )

        self.assertEqual(
            issues,
            [
                "missing console script: culvia-supervisor",
                "console script culvia-web points to 'wrong:main', expected 'culvia.server:main'",
            ],
        )

    def test_check_wheel_archive_accepts_expected_suffixes_and_entrypoints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            wheel = Path(temp_dir) / "culvia-0.1.0-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                for suffix in release_smoke.REQUIRED_PACKAGE_SUFFIXES:
                    archive.writestr(suffix, "")
                for suffix in release_smoke.expected_web_data_files(ROOT):
                    content = (
                        (ROOT / "web" / "index.html").read_text(encoding="utf-8")
                        if suffix.endswith("index.html")
                        else ""
                    )
                    archive.writestr(f"culvia-0.1.0.data/data/{suffix}", content)
                archive.writestr(
                    "culvia-0.1.0.dist-info/entry_points.txt",
                    (
                        "[console_scripts]\n"
                        "culvia = culvia.cli:main\n"
                        "culvia-web = culvia.server:main\n"
                        "culvia-supervisor = culvia.supervisor:main\n"
                    ),
                )
                write_wheel_metadata(archive)

            self.assertEqual(release_smoke.check_wheel_archive(wheel, ROOT), [])

    def test_check_wheel_archive_reports_missing_runtime_and_entrypoint_issues(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            wheel = Path(temp_dir) / "culvia-0.1.0-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("culvia/__init__.py", "")
                archive.writestr("culvia_scores.sqlite-wal", "")
                archive.writestr(
                    "culvia-0.1.0.dist-info/entry_points.txt",
                    "[console_scripts]\nculvia = wrong:main\n",
                )

            issues = release_smoke.check_wheel_archive(wheel, ROOT)

        self.assertTrue(any(issue.startswith("missing web data files:") for issue in issues))
        self.assertTrue(any(issue.startswith("missing package files:") for issue in issues))
        self.assertTrue(any("wheel contains runtime artifacts: culvia_scores.sqlite-wal" in issue for issue in issues))
        self.assertIn("console script culvia points to 'wrong:main', expected 'culvia.cli:main'", issues)
        self.assertIn("missing console script: culvia-web", issues)
        self.assertIn("missing console script: culvia-supervisor", issues)

    def test_check_sdist_archive_accepts_expected_source_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sdist = Path(temp_dir) / "culvia-0.1.0.tar.gz"
            write_sdist(sdist, sorted(release_smoke.source_distribution_suffixes(ROOT)))

            self.assertEqual(release_smoke.check_sdist_archive(sdist, ROOT), [])

    def test_check_sdist_archive_reports_missing_runtime_and_unsafe_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sdist = Path(temp_dir) / "culvia-0.1.0.tar.gz"
            names = ["LICENSE", "pyproject.toml", "culvia_scores.sqlite-wal", "../secret.txt"]
            write_sdist(sdist, names)

            issues = release_smoke.check_sdist_archive(sdist, ROOT)

        self.assertTrue(any(issue.startswith("sdist is missing source files:") for issue in issues))
        self.assertTrue(any("sdist contains runtime artifacts:" in issue for issue in issues))
        self.assertTrue(any("sdist contains unsafe member paths:" in issue for issue in issues))

    def test_check_installed_web_dir_requires_installed_data_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            web_dir = temp / "share" / "culvia" / "web"
            web_dir.mkdir(parents=True)
            for name in release_smoke.INSTALLED_WEB_REQUIRED_FILES:
                (web_dir / name).parent.mkdir(parents=True, exist_ok=True)
                (web_dir / name).write_text("", encoding="utf-8")
            (web_dir / "styles.css").write_text("", encoding="utf-8")
            (web_dir / "app.js").write_text("", encoding="utf-8")
            (web_dir / "index.html").write_text(
                '<link href="/static/styles.css?v=20260604-gallery-state-v2"><script src="/static/app.js?v=20260604-gallery-state-v2"></script>',
                encoding="utf-8",
            )

            self.assertEqual(release_smoke.check_installed_web_dir(web_dir, source_root=ROOT), [])

            issues = release_smoke.check_installed_web_dir(ROOT / "web", source_root=ROOT)
            self.assertTrue(any("source tree" in issue for issue in issues))

    def test_check_installed_web_dir_reports_missing_html_static_references(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            web_dir = Path(temp_dir) / "share" / "culvia" / "web"
            web_dir.mkdir(parents=True)
            for name in release_smoke.INSTALLED_WEB_REQUIRED_FILES:
                (web_dir / name).parent.mkdir(parents=True, exist_ok=True)
                (web_dir / name).write_text("", encoding="utf-8")
            (web_dir / "index.html").write_text(
                '<link href="/static/styles.css?v=old"><script src="/static/missing.js?v=old"></script>',
                encoding="utf-8",
            )

            issues = release_smoke.check_installed_web_dir(web_dir, source_root=ROOT)

        self.assertTrue(
            any("installed web dir is missing HTML static reference missing.js" in issue for issue in issues)
        )

    def test_main_skips_without_wheel_or_build(self) -> None:
        with patch("sys.stdout") as stdout:
            result = release_smoke.main([])

        self.assertEqual(result, 0)
        stdout.write.assert_any_call("SKIP no wheel provided; pass --wheel or --build to run archive checks")

    def test_build_sdist_missing_build_module_is_skip_or_failure_by_strictness(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch("tools.release_smoke.module_available", return_value=False),
        ):
            sdist, issues, skips = release_smoke.build_sdist(ROOT, Path(temp_dir), Path("/python"), strict=False)

            self.assertIsNone(sdist)
            self.assertEqual(issues, [])
            self.assertTrue(any("cannot run build" in item for item in skips))

            sdist, issues, skips = release_smoke.build_sdist(ROOT, Path(temp_dir), Path("/python"), strict=True)

            self.assertIsNone(sdist)
            self.assertTrue(any("cannot run build" in item for item in issues))
            self.assertEqual(skips, [])

    def test_twine_check_accepts_wheel_and_sdist_artifacts(self) -> None:
        wheel = Path("/dist/culvia-0.1.0-py3-none-any.whl")
        sdist = Path("/dist/culvia-0.1.0.tar.gz")
        with (
            patch("tools.release_smoke.module_available", return_value=True),
            patch(
                "tools.release_smoke.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
            ) as run,
        ):
            issues, skips = release_smoke.run_twine_check([wheel, sdist], Path("/python"), strict=True)

        self.assertEqual(issues, [])
        self.assertEqual(skips, [])
        self.assertEqual(
            run.call_args.args[0],
            ["/python", "-m", "twine", "check", str(wheel), str(sdist)],
        )

    def test_twine_check_missing_module_is_skip_or_failure_by_strictness(self) -> None:
        artifact = Path("/dist/culvia-0.1.0.tar.gz")
        with patch("tools.release_smoke.module_available", return_value=False):
            issues, skips = release_smoke.run_twine_check([artifact], Path("/python"), strict=False)
            self.assertEqual(issues, [])
            self.assertTrue(any("cannot run twine" in item for item in skips))

            issues, skips = release_smoke.run_twine_check([artifact], Path("/python"), strict=True)
            self.assertTrue(any("cannot run twine" in item for item in issues))
            self.assertEqual(skips, [])

    def test_build_sdist_with_twine_check_does_not_require_wheel(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch("sys.stdout"):
            sdist = Path(temp_dir) / "culvia-0.1.0.tar.gz"
            sdist.write_bytes(b"sdist")
            with (
                patch("tools.release_smoke.check_project_metadata", return_value=[]),
                patch(
                    "tools.release_smoke.build_sdist",
                    return_value=(sdist, [], []),
                ),
                patch("tools.release_smoke.check_sdist_archive", return_value=[]),
                patch(
                    "tools.release_smoke.run_twine_check",
                    return_value=([], []),
                ) as twine_check,
            ):
                result = release_smoke.main(
                    [
                        "--build-sdist",
                        "--dist-dir",
                        temp_dir,
                        "--twine-check",
                        "--strict",
                    ]
                )

        self.assertEqual(result, 0)
        twine_check.assert_called_once_with([sdist], Path(release_smoke.sys.executable), strict=True)


if __name__ == "__main__":
    unittest.main()
