from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from culvia.app_state import AppStateStore, create_initial_state
from culvia.insight_store import AnalysisInsight, AnalysisInsightMatch
from culvia.job_service import ScoringJobService
from culvia.llm_review_runner import LlmReviewRunnerDependencies, run_llm_review_job
from culvia.llm_runtime import AnalyzerOutput
from culvia.schema import (
    LLM_REVIEW_FIELDS,
    LLM_REVIEW_GENERATION_COLUMN,
    MODEL_LLM_REVIEW,
    score_column,
)
from culvia.scoring import (
    apply_llm_review_scores,
    llm_review_prompt_version,
    llm_review_status,
    normalize_score_dataframe,
)


def make_row(file_id: str, path: str, *, scored: bool = False) -> dict[str, object]:
    row: dict[str, object] = {
        "file_id": file_id,
        "path": path,
        "folder": str(Path(path).parent),
        "filename": Path(path).name,
        "error": "",
    }
    if scored:
        row[LLM_REVIEW_GENERATION_COLUMN] = 1.0
        for field in LLM_REVIEW_FIELDS:
            row[score_column(field, "0_10")] = 8.0
    return row


def make_store(cache_path: str, scores_df: pd.DataFrame) -> AppStateStore:
    store = AppStateStore(
        create_initial_state(
            scores_df=scores_df,
            default_photo_dirs=[],
            default_cache_path=cache_path,
            filter_defaults={},
            default_selected_models=[],
        )
    )
    store.data["source"]["cachePath"] = cache_path
    return store


def make_dependencies(calls: dict[str, Any], *, configured: bool = True) -> LlmReviewRunnerDependencies:
    def score_llm_review_image(
        path: str | Path,
        file_id: str,
        score_context: Mapping[str, object] | None,
    ) -> AnalyzerOutput:
        calls.setdefault("reviewed", []).append((str(path), file_id, dict(score_context or {})))
        scores = {field: 7.0 for field in LLM_REVIEW_FIELDS}
        return AnalyzerOutput(
            scores=scores,
            insights=(
                AnalysisInsight(
                    file_id=file_id,
                    analyzer_key=MODEL_LLM_REVIEW,
                    provider="unit",
                    model="mock-vlm",
                    model_version="mock-vlm",
                    prompt_version="prompt-v1",
                    score=7.0,
                    created_at=2.0,
                ),
            ),
        )

    def save_cache_records(df: pd.DataFrame, cache_path: str | Path, existing_df: pd.DataFrame | None) -> None:
        calls.setdefault("cache_saves", []).append((df.copy(), str(cache_path), existing_df.copy()))

    def save_analysis_insights(insights: Sequence[AnalysisInsight], cache_path: str | Path) -> None:
        calls.setdefault("insight_saves", []).append((tuple(insights), str(cache_path)))

    return LlmReviewRunnerDependencies(
        default_cache_path="/tmp/default.sqlite",
        refresh_persisted_llm_config=lambda cache_path: calls.setdefault("refreshed", []).append(cache_path),
        llm_review_configured=lambda: configured,
        llm_review_status=lambda: {"provider": "unit", "model": "mock-vlm", "promptVersion": "prompt-v1"},
        sanitize_uploaded_paths=lambda value: [Path(item) for item in value or []],
        scan_image_paths=lambda folders: ([], []),
        build_file_id=lambda path: f"id:{Path(path).name}",
        normalize_score_dataframe=normalize_score_dataframe,
        score_llm_review_image=score_llm_review_image,
        apply_llm_review_scores=apply_llm_review_scores,
        load_cache_records=lambda cache_path: pd.DataFrame(),
        save_cache_records=save_cache_records,
        load_latest_matching_analysis_insight_results=lambda cache_path, **identity: {
            "current": AnalysisInsightMatch(1.0)
        },
        save_analysis_insights=save_analysis_insights,
        thumbnail_url=lambda path, max_size: f"/thumb/{Path(path).name}?max={max_size}",
    )


class LlmReviewRunnerTests(unittest.TestCase):
    def test_refreshes_selected_cache_before_configuration_and_status_checks(self) -> None:
        cache_path = "/tmp/llm-review-selected.sqlite"
        store = make_store(cache_path, normalize_score_dataframe(pd.DataFrame()))
        service = ScoringJobService(store)
        job_id = service.reserve(kind="llm_review")
        self.assertTrue(job_id)
        calls: dict[str, Any] = {}
        refreshed = False

        def refresh(path: str) -> None:
            nonlocal refreshed
            refreshed = True
            calls["refresh_path"] = path

        def configured() -> bool:
            self.assertTrue(refreshed)
            return False

        def status() -> Mapping[str, object]:
            raise AssertionError("status must not be read for an unconfigured cache")

        dependencies = replace(
            make_dependencies(calls),
            refresh_persisted_llm_config=refresh,
            llm_review_configured=configured,
            llm_review_status=status,
        )

        run_llm_review_job(
            str(job_id),
            {"mode": "folders", "folders": ["/photos"], "cachePath": cache_path},
            store,
            service,
            dependencies,
        )

        self.assertEqual(calls["refresh_path"], cache_path)
        with store.lock:
            self.assertEqual(store.data["job"]["phase"], "error")
            self.assertEqual(store.data["job"]["error"], "llmReviewNotConfigured")

    def test_config_refresh_failure_stops_before_loading_or_saving_scores(self) -> None:
        cache_path = "/tmp/llm-review-broken.sqlite"
        source_df = normalize_score_dataframe(pd.DataFrame([make_row("current", "/photos/current.jpg", scored=True)]))
        store = make_store(cache_path, source_df)
        service = ScoringJobService(store)
        job_id = service.reserve(kind="llm_review")
        self.assertTrue(job_id)
        calls: dict[str, Any] = {}

        def fail_refresh(_path: str) -> None:
            raise RuntimeError("broken llm config")

        dependencies = replace(
            make_dependencies(calls),
            refresh_persisted_llm_config=fail_refresh,
            load_cache_records=lambda _path: (_ for _ in ()).throw(AssertionError("cache must not load")),
        )

        run_llm_review_job(
            str(job_id),
            {"mode": "folders", "folders": ["/photos"], "cachePath": cache_path},
            store,
            service,
            dependencies,
        )

        self.assertNotIn("cache_saves", calls)
        with store.lock:
            self.assertFalse(store.data["job"]["running"])
            self.assertEqual(store.data["job"]["phase"], "error")
            self.assertIn("broken llm config", store.data["job"]["error"])

    def test_real_status_signature_reuses_an_existing_current_review(self) -> None:
        cache_path = "/tmp/llm-review-current.sqlite"
        scores_df = normalize_score_dataframe(pd.DataFrame([make_row("current", "/photos/current.jpg", scored=True)]))
        store = make_store(cache_path, scores_df)
        service = ScoringJobService(store)
        job_id = service.reserve(kind="llm_review")
        self.assertTrue(job_id)
        calls: dict[str, Any] = {}
        status = llm_review_status()
        dependencies = replace(
            make_dependencies(calls),
            llm_review_status=llm_review_status,
            load_latest_matching_analysis_insight_results=lambda cache_path, **identity: (
                {"current": AnalysisInsightMatch(1.0)}
                if identity
                == {
                    "file_ids": ["current"],
                    "analyzer_key": MODEL_LLM_REVIEW,
                    "provider": str(status["provider"]),
                    "model": str(status["model"]),
                    "model_version": str(status["model"]),
                    "prompt_version": llm_review_prompt_version(),
                }
                else {}
            ),
        )

        run_llm_review_job(
            str(job_id),
            {"mode": "folders", "folders": ["/photos"], "cachePath": cache_path},
            store,
            service,
            dependencies,
        )

        self.assertNotIn("reviewed", calls)
        with store.lock:
            self.assertEqual(store.data["job"]["phase"], "done")
            self.assertEqual(store.data["job"]["titleText"], {"key": "jobText.llmUpToDate"})

    def test_runs_only_photos_missing_current_llm_review_and_writes_incrementally(self) -> None:
        cache_path = "/tmp/llm-review.sqlite"
        scores_df = normalize_score_dataframe(
            pd.DataFrame(
                [
                    make_row("current", "/photos/current.jpg", scored=True),
                    make_row("pending", "/photos/pending.jpg"),
                ]
            )
        )
        store = make_store(cache_path, scores_df)
        service = ScoringJobService(store)
        job_id = service.reserve(kind="llm_review")
        self.assertTrue(job_id)
        calls: dict[str, Any] = {}
        base_dependencies = make_dependencies(calls)

        def save_analysis_insights_after_state_update(
            insights: Sequence[AnalysisInsight], cache_path: str | Path
        ) -> None:
            with store.lock:
                current = store.data["scores_df"]
                pending = current[current["file_id"] == "pending"].iloc[0]
                self.assertAlmostEqual(float(pending[score_column("llm_review_overall", "0_10")]), 7.0)
            calls.setdefault("insight_saves", []).append((tuple(insights), str(cache_path)))

        run_llm_review_job(
            str(job_id),
            {"mode": "folders", "folders": ["/photos"], "cachePath": cache_path},
            store,
            service,
            replace(base_dependencies, save_analysis_insights=save_analysis_insights_after_state_update),
        )

        self.assertEqual([call[1] for call in calls["reviewed"]], ["pending"])
        self.assertEqual(len(calls["cache_saves"]), 1)
        self.assertEqual(len(calls["insight_saves"]), 1)
        with store.lock:
            result_df = store.data["scores_df"]
            pending = result_df[result_df["file_id"] == "pending"].iloc[0]
            self.assertFalse(store.data["job"]["running"])
            self.assertEqual(store.data["job"]["phase"], "done")
        self.assertAlmostEqual(float(pending[score_column("llm_review_overall", "0_10")]), 7.0)

    def test_legacy_current_review_is_recomputed_without_a_generation(self) -> None:
        cache_path = "/tmp/llm-review-legacy.sqlite"
        legacy = make_row("current", "/photos/current.jpg", scored=True)
        legacy[LLM_REVIEW_GENERATION_COLUMN] = pd.NA
        scores_df = normalize_score_dataframe(pd.DataFrame([legacy]))
        store = make_store(cache_path, scores_df)
        service = ScoringJobService(store)
        job_id = service.reserve(kind="llm_review")
        self.assertTrue(job_id)
        calls: dict[str, Any] = {}

        run_llm_review_job(
            str(job_id),
            {"mode": "folders", "folders": ["/photos"], "cachePath": cache_path},
            store,
            service,
            make_dependencies(calls),
        )

        self.assertEqual([call[1] for call in calls["reviewed"]], ["current"])
        self.assertEqual(len(calls["cache_saves"]), 1)
        saved = calls["cache_saves"][0][0]
        self.assertEqual(float(saved.loc[saved["file_id"].eq("current"), LLM_REVIEW_GENERATION_COLUMN].iloc[0]), 2.0)
        with store.lock:
            self.assertEqual(float(store.data["scores_df"].loc[0, LLM_REVIEW_GENERATION_COLUMN]), 2.0)
            self.assertEqual(store.data["job"]["phase"], "done")

    def test_failed_insight_publish_leaves_generation_mismatch_for_retry(self) -> None:
        cache_path = "/tmp/llm-review-retry.sqlite"
        source = make_row("current", "/photos/current.jpg", scored=True)
        source[score_column("llm_cleanliness", "0_10")] = pd.NA
        store = make_store(cache_path, normalize_score_dataframe(pd.DataFrame([source])))
        service = ScoringJobService(store)
        calls: dict[str, Any] = {}
        first_job_id = service.reserve(kind="llm_review")
        self.assertTrue(first_job_id)

        def fail_insight_publish(_insights: Sequence[AnalysisInsight], _cache_path: str | Path) -> None:
            raise RuntimeError("insight publish failed")

        first_dependencies = replace(
            make_dependencies(calls),
            save_analysis_insights=fail_insight_publish,
        )
        run_llm_review_job(
            str(first_job_id),
            {"mode": "folders", "folders": ["/photos"], "cachePath": cache_path},
            store,
            service,
            first_dependencies,
        )

        with store.lock:
            failed_row = store.data["scores_df"].iloc[0]
            self.assertEqual(float(failed_row[LLM_REVIEW_GENERATION_COLUMN]), 2.0)
            self.assertEqual(store.data["job"]["phase"], "error")

        second_job_id = service.reserve(kind="llm_review")
        self.assertTrue(second_job_id)
        run_llm_review_job(
            str(second_job_id),
            {"mode": "folders", "folders": ["/photos"], "cachePath": cache_path},
            store,
            service,
            make_dependencies(calls),
        )

        self.assertEqual([call[1] for call in calls["reviewed"]], ["current", "current"])
        with store.lock:
            self.assertEqual(store.data["job"]["phase"], "done")

    def test_cancelled_job_preserves_cancelled_phase(self) -> None:
        cache_path = "/tmp/llm-review-cancel.sqlite"
        scores_df = normalize_score_dataframe(pd.DataFrame([make_row("pending", "/photos/pending.jpg")]))
        store = make_store(cache_path, scores_df)
        service = ScoringJobService(store)
        job_id = service.reserve(kind="llm_review")
        self.assertTrue(job_id)
        self.assertTrue(service.request_cancel())

        run_llm_review_job(
            str(job_id),
            {"mode": "folders", "folders": ["/photos"], "cachePath": cache_path},
            store,
            service,
            make_dependencies({}),
        )

        with store.lock:
            self.assertFalse(store.data["job"]["running"])
            self.assertEqual(store.data["job"]["phase"], "cancelled")


if __name__ == "__main__":
    unittest.main()
