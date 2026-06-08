from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import check_backend_smoke, prepare_runtime_fixture


DEFAULT_COUNT = 8
SENTINEL_LLM_API_KEY = "unit-test-api-key-0000000000003931"
SENTINEL_LLM_BASE_URL = "https://example.test/v1"
SENTINEL_LLM_MODEL = "culvia-smoke-model"
LLM_ENV_KEYS = (
    "CULVIA_LLM_API_KEY",
    "CULVIA_LLM_ENDPOINT",
    "CULVIA_LLM_BASE_URL",
    "CULVIA_LLM_MODEL",
    "CULVIA_LLM_PROVIDER",
    "CULVIA_LLM_TIMEOUT",
    "CULVIA_LLM_MAX_IMAGE_SIZE",
    "CULVIA_LLM_INPUT_MODE",
    "CULVIA_LLM_PROMPT_PRESET",
    "CULVIA_LLM_CUSTOM_PROMPT",
    "OPENAI_API_KEY",
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


JsonRequester = Callable[[str, str, Any | None, float], Any]
BytesRequester = Callable[[str, float], bytes]


def check(name: str, ok: bool, detail: str) -> CheckResult:
    return CheckResult(name=name, ok=bool(ok), detail=detail)


def result_payload(
    checks: Sequence[CheckResult],
    *,
    ready: dict[str, Any] | None = None,
    command: Sequence[str] | None = None,
    fixture: dict[str, Any] | None = None,
    returncode: int | None = None,
    seconds: float | None = None,
    stdout_tail: Sequence[str] = (),
    stderr_tail: Sequence[str] = (),
) -> dict[str, Any]:
    failed = [item.name for item in checks if not item.ok]
    payload: dict[str, Any] = {
        "ok": not failed,
        "failed": failed,
        "checks": [{"name": item.name, "ok": item.ok, "detail": item.detail} for item in checks],
    }
    if ready is not None:
        payload["ready"] = ready
    if command is not None:
        payload["command"] = list(command)
    if fixture is not None:
        payload["fixture"] = {
            "root": fixture.get("root"),
            "photoDir": fixture.get("photoDir"),
            "cachePath": fixture.get("cachePath"),
            "count": fixture.get("count"),
        }
    if returncode is not None:
        payload["returncode"] = returncode
    if seconds is not None:
        payload["seconds"] = round(seconds, 3)
    if stdout_tail:
        payload["stdoutTail"] = list(stdout_tail)
    if stderr_tail:
        payload["stderrTail"] = list(stderr_tail)
    return payload


def resolve_url(base_url: str, path: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def request_json(
    base_url: str, path: str, method: str = "GET", payload: Any | None = None, timeout: float = 10.0
) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        resolve_url(base_url, path),
        data=data,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def request_bytes(base_url: str, path: str, timeout: float = 10.0) -> bytes:
    request = urllib.request.Request(resolve_url(base_url, path), headers={"Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def scrub_llm_environment(env: dict[str, str]) -> dict[str, str]:
    for key in LLM_ENV_KEYS:
        env.pop(key, None)
    return env


def workflow_environment(fixture: dict[str, Any]) -> dict[str, str]:
    env = os.environ.copy()
    env.update({str(key): str(value) for key, value in dict(fixture["env"]).items()})
    env["CULVIA_DISABLE_KEYCHAIN"] = "1"
    return scrub_llm_environment(env)


def llm_config_smoke_payload(cache_path: str) -> dict[str, Any]:
    return {
        "apiKey": SENTINEL_LLM_API_KEY,
        "baseUrl": SENTINEL_LLM_BASE_URL,
        "model": SENTINEL_LLM_MODEL,
        "promptPreset": "technical",
        "persist": True,
        "cachePath": cache_path,
    }


def read_persisted_llm_rows(cache_path: Path) -> dict[str, str]:
    with sqlite3.connect(cache_path) as conn:
        rows = conn.execute('SELECT "key", "value" FROM photo_app_config WHERE "key" LIKE "llm_%"').fetchall()
    return {str(key): str(value) for key, value in rows}


def collect_llm_config_checks(
    *,
    json_get: JsonRequester,
    cache_path: str,
    timeout: float,
) -> list[CheckResult]:
    checks: list[CheckResult] = []
    try:
        configured = json_get("/api/llm-config", "POST", llm_config_smoke_payload(cache_path), timeout)
    except Exception as exc:  # noqa: BLE001
        return [check("backend workflow saves non-secret LLM config", False, repr(exc))]

    llm = configured.get("llm") if isinstance(configured, dict) else {}
    body_text = json.dumps(configured, ensure_ascii=False, sort_keys=True)
    checks.append(
        check(
            "backend workflow saves non-secret LLM config",
            isinstance(llm, dict)
            and bool(llm.get("configured"))
            and llm.get("keyLabel") == "unit****3931"
            and llm.get("source") == "当前会话"
            and llm.get("baseUrl") == SENTINEL_LLM_BASE_URL
            and llm.get("endpoint") == f"{SENTINEL_LLM_BASE_URL}/chat/completions"
            and llm.get("model") == SENTINEL_LLM_MODEL
            and llm.get("promptPreset") == "technical"
            and SENTINEL_LLM_API_KEY not in body_text,
            f"configured={llm.get('configured') if isinstance(llm, dict) else 'invalid'}, "
            f"keyLabel={llm.get('keyLabel') if isinstance(llm, dict) else 'invalid'}, "
            f"source={llm.get('source') if isinstance(llm, dict) else 'invalid'}, "
            f"model={llm.get('model') if isinstance(llm, dict) else 'invalid'}",
        )
    )

    try:
        rows = read_persisted_llm_rows(Path(cache_path))
        checks.append(
            check(
                "backend workflow does not persist LLM API key",
                rows.get("llm_base_url") == SENTINEL_LLM_BASE_URL
                and rows.get("llm_model") == SENTINEL_LLM_MODEL
                and rows.get("llm_prompt_preset") == "technical"
                and "llm_api_key" not in rows
                and SENTINEL_LLM_API_KEY not in rows.values(),
                f"persistedKeys={sorted(rows)}",
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(check("backend workflow does not persist LLM API key", False, repr(exc)))
    return checks


def create_scoring_smoke_image(root: Path) -> tuple[Path, Path, Path]:
    photo_dir = root / "photos"
    state_dir = root / "state"
    cache_path = state_dir / "culvia_scores.sqlite"
    image_path = photo_dir / "basic-technical-smoke.jpg"
    photo_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    prepare_runtime_fixture.create_fixture_image(image_path, index=0)
    return photo_dir, cache_path, image_path


def scoring_smoke_payload(photo_dir: Path, cache_path: Path) -> dict[str, Any]:
    return {
        "mode": "folders",
        "folders": [str(photo_dir)],
        "cachePath": str(cache_path),
        "networkMode": "direct",
        "selectedModels": ["basic_technical"],
        "uploadedPaths": [],
    }


def poll_scoring_result(
    *,
    json_get: JsonRequester,
    job_id: str,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_state: dict[str, Any] = {}
    while time.monotonic() < deadline:
        state = json_get("/api/state", "GET", None, min(5.0, max(1.0, timeout)))
        if isinstance(state, dict):
            last_state = state
            job = state.get("job") if isinstance(state.get("job"), dict) else {}
            if job.get("jobId") == job_id and job.get("phase") == "error":
                return state
            if job.get("jobId") == job_id and not bool(job.get("running")):
                return state
        time.sleep(0.25)
    return last_state


def numeric_score_map(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    scores: dict[str, float] = {}
    for key, raw in value.items():
        try:
            scores[str(key)] = float(raw)
        except (TypeError, ValueError):
            continue
    return scores


def sqlite_basic_technical_row(cache_path: Path) -> dict[str, Any]:
    columns = (
        "file_id",
        "path",
        "folder",
        "filename",
        "error",
        "technical_overall_0_10",
        "sharpness_0_10",
        "exposure_0_10",
        "contrast_0_10",
        "cleanliness_0_10",
    )
    with sqlite3.connect(cache_path) as conn:
        quoted_columns = ", ".join(f'"{column}"' for column in columns)
        row = conn.execute(f"SELECT {quoted_columns} FROM culvia_scores LIMIT 1").fetchone()
        count = conn.execute("SELECT COUNT(*) FROM culvia_scores").fetchone()[0]
    if row is None:
        return {"count": count}
    return {"count": count, **dict(zip(columns, row))}


def collect_basic_technical_scoring_checks(
    *,
    json_get: JsonRequester,
    smoke_root: Path,
    timeout: float,
) -> list[CheckResult]:
    checks: list[CheckResult] = []
    photo_dir, cache_path, image_path = create_scoring_smoke_image(smoke_root)
    try:
        json_get(
            "/api/filter",
            "POST",
            {
                "manualStatus": "all",
                "colorLabel": "all",
                "modelAgreement": "all",
                "minScore": 0,
                "minTechnical": 0,
                "minModelQuality": 0,
                "minAestheticReference": 0,
                "minLlmReview": 0,
                "limit": 500,
            },
            timeout,
        )
    except Exception as exc:  # noqa: BLE001
        return [check("backend workflow resets filters for basic technical scoring", False, repr(exc))]
    try:
        started = json_get("/api/score", "POST", scoring_smoke_payload(photo_dir, cache_path), timeout)
        job_id = str(started.get("jobId") or "") if isinstance(started, dict) else ""
        checks.append(
            check(
                "backend workflow starts basic technical scoring",
                isinstance(started, dict) and bool(started.get("started")) and bool(job_id),
                f"started={started.get('started') if isinstance(started, dict) else 'invalid'}, jobId={job_id or 'missing'}",
            )
        )
    except Exception as exc:  # noqa: BLE001
        return [check("backend workflow starts basic technical scoring", False, repr(exc))]
    if not checks[-1].ok:
        return checks

    final_state = poll_scoring_result(json_get=json_get, job_id=job_id, timeout=max(10.0, timeout))
    job = final_state.get("job") if isinstance(final_state.get("job"), dict) else {}
    source = final_state.get("source") if isinstance(final_state.get("source"), dict) else {}
    summary = final_state.get("summary") if isinstance(final_state.get("summary"), dict) else {}
    photos = final_state.get("photos") if isinstance(final_state.get("photos"), list) else []
    photo = photos[0] if photos and isinstance(photos[0], dict) else {}
    technical_scores = numeric_score_map(photo.get("technicalScores") if isinstance(photo, dict) else {})
    expected_fields = {"technical_overall", "sharpness", "exposure", "contrast", "cleanliness"}
    recommendation = photo.get("recommendation") if isinstance(photo, dict) else None

    checks.append(
        check(
            "backend workflow completes basic technical scoring",
            job.get("jobId") == job_id
            and job.get("phase") == "done"
            and not bool(job.get("running"))
            and int(job.get("done") or 0) == 1
            and int(job.get("total") or 0) == 1
            and not str(job.get("error") or ""),
            f"phase={job.get('phase')}, running={job.get('running')}, done={job.get('done')}, total={job.get('total')}, error={job.get('error')}",
        )
    )
    checks.append(
        check(
            "backend workflow exposes basic technical score result",
            source.get("mode") == "folders"
            and source.get("folders") == [str(photo_dir)]
            and source.get("cachePath") == str(cache_path)
            and int(summary.get("scored") or 0) == 1
            and int(summary.get("showing") or 0) == 1
            and int(final_state.get("errors") or 0) == 0
            and str(photo.get("path") or "") == str(image_path)
            and set(technical_scores) == expected_fields
            and all(0.0 <= value <= 10.0 for value in technical_scores.values())
            and recommendation is not None
            and abs(float(recommendation) - technical_scores["technical_overall"]) < 0.0001,
            f"source={source.get('mode')} folders={source.get('folders')} scored={summary.get('scored')} "
            f"showing={summary.get('showing')} technicalFields={sorted(technical_scores)} recommendation={recommendation}",
        )
    )
    try:
        row = sqlite_basic_technical_row(cache_path)
        technical_columns = [
            "technical_overall_0_10",
            "sharpness_0_10",
            "exposure_0_10",
            "contrast_0_10",
            "cleanliness_0_10",
        ]
        checks.append(
            check(
                "backend workflow writes basic technical scores to SQLite",
                int(row.get("count") or 0) == 1
                and row.get("path") == str(image_path)
                and row.get("folder") == str(photo_dir)
                and row.get("filename") == image_path.name
                and row.get("error") == ""
                and all(
                    row.get(column) is not None and 0.0 <= float(row[column]) <= 10.0 for column in technical_columns
                ),
                f"count={row.get('count')}, path={row.get('path')}, technicalColumns={[(column, row.get(column)) for column in technical_columns]}",
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(check("backend workflow writes basic technical scores to SQLite", False, repr(exc)))
    return checks


def collect_workflow_checks(
    *,
    base_url: str,
    fixture: dict[str, Any],
    export_dir: Path,
    timeout: float = 10.0,
    json_requester: JsonRequester | None = None,
    bytes_requester: BytesRequester | None = None,
) -> list[CheckResult]:
    json_get = json_requester or (
        lambda path, method, payload, request_timeout: request_json(base_url, path, method, payload, request_timeout)
    )
    bytes_get = bytes_requester or (lambda path, request_timeout: request_bytes(base_url, path, request_timeout))
    expected_count = int(fixture.get("count") or 0)
    checks: list[CheckResult] = []

    try:
        state = json_get("/api/state", "GET", None, timeout)
    except Exception as exc:  # noqa: BLE001 - release smoke reports exact request failure.
        return [check("backend workflow state endpoint responds", False, repr(exc))]

    source = state.get("source") if isinstance(state, dict) else {}
    summary = state.get("summary") if isinstance(state, dict) else {}
    photos = state.get("photos") if isinstance(state, dict) else []
    cache_path = str(source.get("cachePath") or "") if isinstance(source, dict) else ""
    folders = source.get("folders") if isinstance(source, dict) else []
    scored = int(summary.get("scored") or 0) if isinstance(summary, dict) else 0
    checks.append(
        check(
            "backend workflow loads fixture cache",
            cache_path == str(fixture.get("cachePath"))
            and str(fixture.get("photoDir")) in [str(item) for item in folders]
            and scored == expected_count,
            f"cache={cache_path}, folders={folders}, scored={scored}, expected={expected_count}",
        )
    )
    checks.append(
        check(
            "backend workflow exposes fixture photos",
            isinstance(photos, list) and len(photos) == expected_count,
            f"photos={len(photos) if isinstance(photos, list) else 'invalid'}",
        )
    )
    if not checks[-1].ok:
        return checks

    first = photos[0]
    first_id = str(first.get("fileId") or "")
    thumb_path = str(first.get("thumb") or "")

    try:
        app_js = bytes_get("/static/app.js", timeout)
        checks.append(check("backend workflow serves web assets", len(app_js) > 1000, f"app.js bytes={len(app_js)}"))
    except Exception as exc:  # noqa: BLE001
        checks.append(check("backend workflow serves web assets", False, repr(exc)))

    try:
        thumbnail = bytes_get(thumb_path, timeout)
        checks.append(
            check("backend workflow renders thumbnail", len(thumbnail) > 100, f"thumbnail bytes={len(thumbnail)}")
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(check("backend workflow renders thumbnail", False, repr(exc)))

    try:
        filtered = json_get(
            "/api/filter",
            "POST",
            {"manualStatus": "pick", "minScore": 0, "limit": 500, "colorLabel": "all"},
            timeout,
        )
        filtered_summary = filtered.get("summary") if isinstance(filtered, dict) else {}
        showing = int(filtered_summary.get("showing") or 0) if isinstance(filtered_summary, dict) else 0
        checks.append(check("backend workflow filters picked photos", showing > 0, f"showing={showing}"))
    except Exception as exc:  # noqa: BLE001
        checks.append(check("backend workflow filters picked photos", False, repr(exc)))

    try:
        marked = json_get(
            "/api/mark",
            "POST",
            {"fileId": first_id, "rating": 5, "status": "pick", "colorLabel": "green"},
            timeout,
        )
        action = marked.get("action") if isinstance(marked, dict) else {}
        checks.append(
            check(
                "backend workflow marks a photo",
                action.get("fileId") == first_id and action.get("status") == "pick",
                f"fileId={action.get('fileId')}, status={action.get('status')}",
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(check("backend workflow marks a photo", False, repr(exc)))

    export_dir.mkdir(parents=True, exist_ok=True)
    try:
        preflight = json_get("/api/export/preflight", "POST", {"destination": str(export_dir)}, timeout)
        checks.append(
            check(
                "backend workflow export preflight succeeds",
                int(preflight.get("ready") or 0) > 0 and int(preflight.get("total") or 0) > 0,
                f"total={preflight.get('total')}, ready={preflight.get('ready')}, missing={preflight.get('missing')}",
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(check("backend workflow export preflight succeeds", False, repr(exc)))

    try:
        copied = json_get("/api/export/selected-files", "POST", {"destination": str(export_dir)}, timeout)
        checks.append(
            check(
                "backend workflow copies selected files",
                int(copied.get("copied") or 0) > 0,
                f"copied={copied.get('copied')}, skipped={copied.get('skipped')}",
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(check("backend workflow copies selected files", False, repr(exc)))

    try:
        history = json_get("/api/curation/history?limit=5", "GET", None, timeout)
        actions = history.get("actions") if isinstance(history, dict) else []
        checks.append(
            check(
                "backend workflow records curation history",
                isinstance(actions, list)
                and any(item.get("kind") == "mark" for item in actions if isinstance(item, dict)),
                f"actions={len(actions) if isinstance(actions, list) else 'invalid'}",
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(check("backend workflow records curation history", False, repr(exc)))

    checks.extend(
        collect_llm_config_checks(
            json_get=json_get,
            cache_path=str(fixture.get("cachePath") or ""),
            timeout=timeout,
        )
    )
    checks.extend(
        collect_basic_technical_scoring_checks(
            json_get=json_get,
            smoke_root=export_dir.parent / "basic-technical-smoke",
            timeout=max(10.0, timeout),
        )
    )
    return checks


def command_for_args(args: argparse.Namespace) -> tuple[str, list[str]]:
    if args.source:
        return "source", [
            str(args.python),
            "-m",
            "culvia.server",
            "--host",
            "127.0.0.1",
            "--port",
            "auto",
            "--no-open",
            "--print-json",
            "--health-timeout",
            str(max(1.0, args.timeout)),
        ]
    binary = args.binary or check_backend_smoke.default_binary_path()
    return "binary", [
        str(binary),
        "--host",
        "127.0.0.1",
        "--port",
        "auto",
        "--no-open",
        "--print-json",
        "--health-timeout",
        str(max(1.0, args.timeout)),
    ]


def run_workflow_smoke(
    command: Sequence[str],
    *,
    fixture: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    started = time.monotonic()
    stderr_tail: deque[str] = deque(maxlen=60)
    stdout_tail: deque[str] = deque(maxlen=60)
    env = workflow_environment(fixture)
    process: subprocess.Popen[str] | None = None
    checks: list[CheckResult] = []
    ready: dict[str, Any] | None = None
    try:
        process = subprocess.Popen(
            list(command),
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        ready = check_backend_smoke.wait_for_ready(process, timeout, stdout_tail=stdout_tail, stderr_tail=stderr_tail)
        check_backend_smoke.wait_for_health(str(ready["healthUrl"]), timeout)
        checks = collect_workflow_checks(
            base_url=str(ready["baseUrl"]),
            fixture=fixture,
            export_dir=Path(str(fixture["root"])) / "exported",
            timeout=min(15.0, max(3.0, timeout / 6.0)),
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(check("backend workflow process reaches ready state", False, repr(exc)))
    finally:
        returncode = check_backend_smoke.terminate_process(process) if process is not None else None
    return result_payload(
        checks,
        ready=ready,
        command=command,
        fixture=fixture,
        returncode=returncode,
        seconds=time.monotonic() - started,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
    )


def build_fixture(args: argparse.Namespace) -> tuple[dict[str, Any], tempfile.TemporaryDirectory[str] | None]:
    if args.fixture_root is not None:
        return prepare_runtime_fixture.write_fixture(
            args.fixture_root, count=max(1, args.count), force=args.force_fixture
        ), None
    temp = tempfile.TemporaryDirectory(prefix="culvia-server-workflow-")
    fixture = prepare_runtime_fixture.write_fixture(Path(temp.name), count=max(1, args.count), force=False)
    return fixture, temp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a fixture curation/export workflow against a Culvia backend.")
    parser.add_argument("--binary", type=Path, default=None, help="Backend binary to test. Defaults to current target.")
    parser.add_argument("--source", action="store_true", help="Run the source backend module instead of a binary.")
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--fixture-root", type=Path, default=None)
    parser.add_argument(
        "--force-fixture", action="store_true", help="Replace --fixture-root when it contains a fixture marker."
    )
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    mode, command = command_for_args(args)
    fixture, cleanup = build_fixture(args)
    try:
        payload = {"mode": mode, **run_workflow_smoke(command, fixture=fixture, timeout=max(1.0, args.timeout))}
    finally:
        if cleanup is not None:
            cleanup.cleanup()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(("OK" if payload["ok"] else "FAIL") + f" backend workflow smoke ({mode})")
        for item in payload["checks"]:
            print(("OK" if item["ok"] else "FAIL") + f" {item['name']}: {item['detail']}")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
