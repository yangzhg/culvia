from __future__ import annotations

import plistlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import check_macos_app_launch_smoke
from tools import check_backend_workflow_smoke


def write_llm_config_rows(cache_path: str) -> None:
    path = Path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            'CREATE TABLE IF NOT EXISTS photo_app_config ("key" TEXT PRIMARY KEY, "value" TEXT NOT NULL, "updated_at" REAL NOT NULL)'
        )
        conn.executemany(
            'INSERT OR REPLACE INTO photo_app_config ("key", "value", "updated_at") VALUES (?, ?, 1.0)',
            (
                ("llm_base_url", check_backend_workflow_smoke.SENTINEL_LLM_BASE_URL),
                ("llm_model", check_backend_workflow_smoke.SENTINEL_LLM_MODEL),
                ("llm_prompt_preset", "technical"),
            ),
        )
        conn.commit()


def write_basic_technical_cache(cache_path: str, image_path: str, file_id: str) -> None:
    path = Path(cache_path)
    source = Path(image_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE culvia_scores ("
            '"file_id" TEXT PRIMARY KEY, "path" TEXT, "folder" TEXT, "filename" TEXT, "error" TEXT, '
            '"technical_overall_0_10" REAL, "sharpness_0_10" REAL, "exposure_0_10" REAL, '
            '"contrast_0_10" REAL, "cleanliness_0_10" REAL)'
        )
        conn.execute(
            "INSERT INTO culvia_scores VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (file_id, str(source), str(source.parent), source.name, "", 8.4, 8.0, 8.5, 8.6, 8.7),
        )
        conn.commit()


class MacosAppLaunchSmokeTests(unittest.TestCase):
    def test_parse_smoke_event_accepts_known_events(self) -> None:
        event = check_macos_app_launch_smoke.parse_smoke_event(
            '{"event":"windowCreated","label":"main","baseUrl":"http://127.0.0.1:8501"}'
        )

        self.assertIsNotNone(event)
        self.assertEqual(event["event"], "windowCreated")
        frontend = check_macos_app_launch_smoke.parse_smoke_event(
            '{"event":"frontendReady","label":"main","baseUrl":"http://127.0.0.1:8501","viewTabs":4}'
        )
        self.assertIsNotNone(frontend)
        self.assertEqual(frontend["event"], "frontendReady")
        self.assertIsNone(check_macos_app_launch_smoke.parse_smoke_event('{"event":"ignored"}'))
        self.assertIsNone(check_macos_app_launch_smoke.parse_smoke_event("not json"))

    def test_app_executable_resolves_from_info_plist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "Culvia.app"
            macos = app / "Contents" / "MacOS"
            macos.mkdir(parents=True)
            executable = macos / "culvia-desktop"
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
            with (app / "Contents" / "Info.plist").open("wb") as handle:
                plistlib.dump({"CFBundleExecutable": executable.name}, handle)

            resolved, error = check_macos_app_launch_smoke.app_executable(app)

        self.assertEqual(resolved, executable)
        self.assertEqual(error, "")

    def test_launch_environment_sets_desktop_smoke_flags(self) -> None:
        fixture = {
            "env": {
                "CULVIA_CACHE_PATH": "/fixture/state/culvia_scores.sqlite",
                "CULVIA_PHOTO_DIRS": "/fixture/photos",
            }
        }

        env = check_macos_app_launch_smoke.launch_environment(
            fixture,
            exit_after_ms=1500,
            ready_timeout_secs=120,
        )

        self.assertEqual(env["CULVIA_DESKTOP_FORCE_BACKEND"], "1")
        self.assertEqual(env["CULVIA_DESKTOP_SMOKE"], "1")
        self.assertEqual(env["CULVIA_DESKTOP_SMOKE_EXIT_AFTER_MS"], "1500")
        self.assertEqual(env["CULVIA_DESKTOP_READY_TIMEOUT_SECS"], "120")
        self.assertEqual(env["CULVIA_DESKTOP_BACKEND_HEALTH_TIMEOUT_SECS"], "120")
        self.assertEqual(env["CULVIA_DESKTOP_FRONTEND_READY_TIMEOUT_SECS"], "120")
        self.assertEqual(env["CULVIA_CACHE_PATH"], "/fixture/state/culvia_scores.sqlite")

    def test_launch_environment_scrubs_llm_secrets(self) -> None:
        fixture = {
            "env": {
                "CULVIA_CACHE_PATH": "/fixture/state/culvia_scores.sqlite",
                "CULVIA_PHOTO_DIRS": "/fixture/photos",
            }
        }

        with patch.dict("os.environ", {"OPENAI_API_KEY": "real-key", "CULVIA_LLM_MODEL": "real-model"}):
            env = check_macos_app_launch_smoke.launch_environment(
                fixture,
                exit_after_ms=1500,
                ready_timeout_secs=120,
            )

        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("CULVIA_LLM_MODEL", env)

    def test_result_payload_fails_when_required_event_is_missing(self) -> None:
        checks = [
            check_macos_app_launch_smoke.check(
                "macos app emits backend, window, and frontend ready smoke events",
                False,
                "events=['backendReady']",
            )
        ]

        payload = check_macos_app_launch_smoke.result_payload(checks, events=[{"event": "backendReady"}])

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["failed"], ["macos app emits backend, window, and frontend ready smoke events"])
        self.assertEqual(payload["events"], [{"event": "backendReady"}])

    def test_base_url_from_events_prefers_backend_ready(self) -> None:
        events = [
            {"event": "windowCreated", "baseUrl": "http://127.0.0.1:2"},
            {"event": "backendReady", "baseUrl": "http://127.0.0.1:1"},
        ]

        self.assertEqual(check_macos_app_launch_smoke.base_url_from_events(events), "http://127.0.0.1:1")

    def test_collect_app_runtime_checks_reuses_workflow_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = {
                "root": tmp,
                "cachePath": f"{tmp}/state/culvia_scores.sqlite",
                "photoDir": f"{tmp}/photos",
                "count": 1,
            }
            score_job_id = ""
            scored_photo: dict[str, object] = {}
            score_source: dict[str, object] = {}

            def json_requester(path, method, payload, timeout):  # noqa: ANN001 - test double mirrors tool callback.
                nonlocal score_job_id, scored_photo, score_source
                if path == "/api/state" and not score_job_id:
                    return {
                        "source": {
                            "cachePath": fixture["cachePath"],
                            "folders": [fixture["photoDir"]],
                        },
                        "summary": {"scored": 1},
                        "photos": [{"fileId": "photo-1", "thumb": "/api/thumbnail?path=photo-1&max=420"}],
                    }
                if path == "/api/filter":
                    return {"summary": {"showing": 1}}
                if path == "/api/mark":
                    return {"action": {"fileId": payload["fileId"], "status": "pick"}}
                if path == "/api/export/preflight":
                    return {"total": 1, "ready": 1, "missing": 0}
                if path == "/api/export/selected-files":
                    return {"copied": 1, "skipped": 0}
                if path == "/api/curation/history?limit=5":
                    return {"actions": [{"kind": "mark"}]}
                if path == "/api/llm-config":
                    write_llm_config_rows(fixture["cachePath"])
                    return {
                        "llm": {
                            "configured": True,
                            "keyLabel": "unit****3931",
                            "source": "当前会话",
                            "baseUrl": check_backend_workflow_smoke.SENTINEL_LLM_BASE_URL,
                            "endpoint": f"{check_backend_workflow_smoke.SENTINEL_LLM_BASE_URL}/chat/completions",
                            "model": check_backend_workflow_smoke.SENTINEL_LLM_MODEL,
                            "promptPreset": "technical",
                        }
                    }
                if path == "/api/score":
                    score_job_id = "score-job-1"
                    photo_dir = str(payload["folders"][0])
                    cache_path = str(payload["cachePath"])
                    image_path = str(next(Path(photo_dir).glob("*.jpg")))
                    file_id = "technical-photo-1"
                    write_basic_technical_cache(cache_path, image_path, file_id)
                    score_source = {"mode": "folders", "folders": [photo_dir], "cachePath": cache_path}
                    scored_photo = {
                        "fileId": file_id,
                        "path": image_path,
                        "technicalScores": {
                            "technical_overall": 8.4,
                            "sharpness": 8.0,
                            "exposure": 8.5,
                            "contrast": 8.6,
                            "cleanliness": 8.7,
                        },
                        "recommendation": 8.4,
                    }
                    return {"started": True, "jobId": score_job_id}
                if path == "/api/state":
                    return {
                        "source": score_source,
                        "summary": {"scored": 1, "showing": 1},
                        "job": {
                            "jobId": score_job_id,
                            "phase": "done",
                            "running": False,
                            "done": 1,
                            "total": 1,
                            "error": "",
                        },
                        "errors": 0,
                        "photos": [scored_photo],
                    }
                raise AssertionError(f"unexpected JSON request: {method} {path}")

            def bytes_requester(path, timeout):  # noqa: ANN001 - test double mirrors tool callback.
                if path == "/static/app.js":
                    return b"x" * 2000
                if path.startswith("/api/thumbnail"):
                    return b"x" * 200
                raise AssertionError(f"unexpected bytes request: {path}")

            checks = check_macos_app_launch_smoke.collect_app_runtime_checks(
                base_url="http://127.0.0.1:8501",
                fixture=fixture,
                timeout=3.0,
                json_requester=json_requester,
                bytes_requester=bytes_requester,
            )

            self.assertTrue(all(item.ok for item in checks))
            self.assertTrue(all(item.name.startswith("macos app runtime") for item in checks))


if __name__ == "__main__":
    unittest.main()
