from __future__ import annotations

import sqlite3
import os
import tempfile
import unittest
from pathlib import Path

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


class BackendWorkflowSmokeTests(unittest.TestCase):
    def test_workflow_environment_disables_keychain_and_scrubs_llm_env(self) -> None:
        original_key = os.environ.get("CULVIA_LLM_API_KEY")
        try:
            os.environ["CULVIA_LLM_API_KEY"] = "real-key-should-not-leak"
            env = check_backend_workflow_smoke.workflow_environment({"env": {"CULVIA_CACHE_PATH": "/tmp/x"}})
        finally:
            if original_key is None:
                os.environ.pop("CULVIA_LLM_API_KEY", None)
            else:
                os.environ["CULVIA_LLM_API_KEY"] = original_key

        self.assertEqual(env["CULVIA_DISABLE_KEYCHAIN"], "1")
        self.assertNotIn("CULVIA_LLM_API_KEY", env)
        self.assertEqual(env["CULVIA_CACHE_PATH"], "/tmp/x")

    def test_collect_workflow_checks_exercises_curation_and_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = {
                "count": 2,
                "photoDir": str(Path(tmp) / "photos"),
                "cachePath": str(Path(tmp) / "state" / "culvia_scores.sqlite"),
            }
            requests: list[tuple[str, str, object | None]] = []
            score_job_id = ""
            scored_photo: dict[str, object] = {}
            score_source: dict[str, object] = {}

            def json_request(path: str, method: str, payload: object | None, _timeout: float) -> object:
                nonlocal score_job_id, scored_photo, score_source
                requests.append((method, path, payload))
                if path == "/api/state" and not score_job_id:
                    return {
                        "source": {"cachePath": fixture["cachePath"], "folders": [fixture["photoDir"]]},
                        "summary": {"scored": 2, "showing": 2},
                        "photos": [
                            {"fileId": "image-1", "thumb": "/api/thumbnail?file_id=image-1"},
                            {"fileId": "image-2", "thumb": "/api/thumbnail?file_id=image-2"},
                        ],
                    }
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
                if path == "/api/filter":
                    return {"summary": {"showing": 1}}
                if path == "/api/mark":
                    return {"action": {"fileId": "image-1", "status": "pick"}}
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
                    assert isinstance(payload, dict)
                    score_job_id = "score-job-1"
                    photo_dir = str(payload["folders"][0])
                    cache_path = str(payload["cachePath"])
                    image_path = str(next(Path(photo_dir).glob("*.jpg")))
                    file_id = "technical-image-1"
                    write_basic_technical_cache(cache_path, image_path, file_id)
                    score_source = {
                        "mode": "folders",
                        "folders": [photo_dir],
                        "cachePath": cache_path,
                    }
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
                raise AssertionError(f"unexpected request: {method} {path}")

            def bytes_request(path: str, _timeout: float) -> bytes:
                if path == "/static/app.js":
                    return b"x" * 1200
                if path == "/api/thumbnail?file_id=image-1":
                    return b"\xff\xd8" + b"x" * 200
                raise AssertionError(f"unexpected bytes request: {path}")

            checks = check_backend_workflow_smoke.collect_workflow_checks(
                base_url="http://127.0.0.1:8501/",
                fixture=fixture,
                export_dir=Path(tmp) / "exported",
                json_requester=json_request,
                bytes_requester=bytes_request,
            )

        payload = check_backend_workflow_smoke.result_payload(checks)
        self.assertTrue(payload["ok"], payload["failed"])
        self.assertIn(
            ("POST", "/api/mark", {"fileId": "image-1", "rating": 5, "status": "pick", "colorLabel": "green"}), requests
        )
        self.assertIn(("POST", "/api/export/selected-files", {"destination": str(Path(tmp) / "exported")}), requests)
        self.assertIn(
            ("POST", "/api/llm-config", check_backend_workflow_smoke.llm_config_smoke_payload(fixture["cachePath"])),
            requests,
        )
        self.assertTrue(any(request[1] == "/api/score" for request in requests))

    def test_collect_workflow_checks_reports_missing_fixture_photos(self) -> None:
        fixture = {"count": 2, "photoDir": "/photos", "cachePath": "/state/culvia_scores.sqlite"}

        def json_request(path: str, _method: str, _payload: object | None, _timeout: float) -> object:
            self.assertEqual(path, "/api/state")
            return {
                "source": {"cachePath": fixture["cachePath"], "folders": [fixture["photoDir"]]},
                "summary": {"scored": 2},
                "photos": [],
            }

        checks = check_backend_workflow_smoke.collect_workflow_checks(
            base_url="http://127.0.0.1:8501/",
            fixture=fixture,
            export_dir=Path("/tmp/exported"),
            json_requester=json_request,
            bytes_requester=lambda _path, _timeout: b"",
        )
        payload = check_backend_workflow_smoke.result_payload(checks)

        self.assertFalse(payload["ok"])
        self.assertIn("backend workflow exposes fixture photos", payload["failed"])


if __name__ == "__main__":
    unittest.main()
