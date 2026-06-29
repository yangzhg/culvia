from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from culvia.app_state import AppStateStore, create_initial_state
from culvia.insight_store import AnalysisInsight
from culvia.job_service import ScoringJobService
from culvia.llm_review_runner import LlmReviewRunnerDependencies, run_llm_review_job
from culvia.llm_runtime import AnalyzerOutput
from culvia.schema import LLM_REVIEW_FIELDS, MODEL_LLM_REVIEW, score_column
from culvia.scoring import apply_llm_review_scores, normalize_score_dataframe


def make_row(file_id: str, path: str, *, scored: bool = False) -> dict[str, object]:
    row: dict[str, object] = {
        "file_id": file_id,
        "path": path,
        "folder": str(Path(path).parent),
        "filename": Path(path).name,
        "error": "",
    }
    if scored:
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
                ),
            ),
        )

    def save_cache_records(df: pd.DataFrame, cache_path: str | Path, existing_df: pd.DataFrame | None) -> None:
        calls.setdefault("cache_saves", []).append((df.copy(), str(cache_path), existing_df.copy()))

    def save_analysis_insights(insights: Sequence[AnalysisInsight], cache_path: str | Path) -> None:
        calls.setdefault("insight_saves", []).append((tuple(insights), str(cache_path)))

    return LlmReviewRunnerDependencies(
        default_cache_path="/tmp/default.sqlite",
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
        load_analysis_insights=lambda cache_path, file_ids=None: [
            AnalysisInsight(
                file_id="current",
                analyzer_key=MODEL_LLM_REVIEW,
                provider="unit",
                model="mock-vlm",
                model_version="mock-vlm",
                prompt_version="prompt-v1",
            )
        ],
        save_analysis_insights=save_analysis_insights,
        thumbnail_url=lambda path, max_size: f"/thumb/{Path(path).name}?max={max_size}",
    )


class LlmReviewRunnerTests(unittest.TestCase):
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

        run_llm_review_job(
            str(job_id),
            {"mode": "folders", "folders": ["/photos"], "cachePath": cache_path},
            store,
            service,
            make_dependencies(calls),
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
