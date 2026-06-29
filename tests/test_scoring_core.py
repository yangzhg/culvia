from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from culvia.insight_store import AnalysisInsight
from culvia.schema import (
    MODEL_BASIC_TECHNICAL,
    MODEL_CLIP_AESTHETIC,
    MODEL_CLIP_IQA,
    MODEL_CORE_AESTHETIC,
    MODEL_LLM_REVIEW,
)
from culvia.scoring_core import ScoreImagePathDependencies, score_image_paths


MODEL_KEYS = (
    MODEL_CORE_AESTHETIC,
    MODEL_BASIC_TECHNICAL,
    MODEL_CLIP_IQA,
    MODEL_CLIP_AESTHETIC,
    MODEL_LLM_REVIEW,
)


def base_plan(**overrides: bool) -> dict[str, bool]:
    plan = {model_key: False for model_key in MODEL_KEYS}
    plan.update(overrides)
    return plan


def make_dependencies(
    *,
    cache_df: pd.DataFrame | None = None,
    insights: list[AnalysisInsight] | None = None,
    recompute_plan: dict[str, bool] | None = None,
    calls: dict[str, object] | None = None,
) -> ScoreImagePathDependencies:
    call_log = calls if calls is not None else {}
    active_recompute_plan = recompute_plan if recompute_plan is not None else base_plan()

    def make_empty_record(path: Path, file_id: str, error: str) -> dict[str, object]:
        return {
            "file_id": file_id,
            "path": str(path),
            "filename": path.name,
            "error": error,
        }

    def save_cache_records(df: pd.DataFrame, cache_path: str | Path, existing_df: pd.DataFrame | None) -> None:
        call_log["saved_cache"] = {
            "df": df.copy(),
            "cache_path": str(cache_path),
            "existing_rows": 0 if existing_df is None else len(existing_df),
        }

    def score_llm_review_image(path: Path, *, file_id: str, score_context: dict[str, object]) -> SimpleNamespace:
        call_log.setdefault("llm_paths", []).append((path, file_id, dict(score_context)))
        insight = AnalysisInsight(
            file_id=file_id,
            analyzer_key=MODEL_LLM_REVIEW,
            provider="test-provider",
            model="test-model",
            model_version="test-model",
            prompt_version="prompt-v1",
            score=8.8,
        )
        return SimpleNamespace(scores={"llm_review_overall": 8.8}, insights=[insight])

    def apply_llm_review_scores(record: dict[str, object], scores: dict[str, float]) -> dict[str, object]:
        record["llm_review_overall_0_10"] = scores["llm_review_overall"]
        return record

    def save_analysis_insights(saved_insights: list[AnalysisInsight], cache_path: str | Path) -> None:
        call_log["saved_insights"] = (list(saved_insights), str(cache_path))

    return ScoreImagePathDependencies(
        build_file_id=lambda _path: "image-1",
        get_device=lambda: "cpu",
        normalize_selected_models=lambda value: [str(item) for item in value or []],
        model_recompute_plan=lambda _record, _models: dict(active_recompute_plan),
        model_output_fields=lambda model_key: (model_key,),
        load_cache_records=lambda _cache_path: cache_df.copy() if cache_df is not None else pd.DataFrame(),
        save_cache_records=save_cache_records,
        normalize_score_dataframe=lambda df: df,
        make_empty_record=make_empty_record,
        score_aesthetic_image=lambda _path, _model: {},
        apply_aesthetic_scores=lambda record, _scores: record,
        analyze_technical_quality=lambda _path: {},
        apply_technical_scores=lambda record, _scores: record,
        score_clip_reference_image=lambda _path, _model: {},
        apply_clip_reference_scores=lambda record, _scores: record,
        score_llm_review_image=score_llm_review_image,
        apply_llm_review_scores=apply_llm_review_scores,
        load_analysis_insights=lambda _cache_path, file_ids=None: list(insights or []),
        save_analysis_insights=save_analysis_insights,
        llm_review_prompt_version=lambda: "prompt-v1",
        llm_review_provider=lambda: "test-provider",
        llm_review_model_name=lambda: "test-model",
    )


class ScoringCoreTests(unittest.TestCase):
    def test_cached_llm_scores_without_matching_insight_are_recomputed(self) -> None:
        cache_df = pd.DataFrame(
            [
                {
                    "file_id": "image-1",
                    "path": "/photos/a.jpg",
                    "filename": "a.jpg",
                    "error": "",
                    "llm_review_overall_0_10": 7.1,
                }
            ]
        )
        calls: dict[str, object] = {}
        progress: list[tuple[int, int, str, str]] = []

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            cache_path.write_text("", encoding="utf-8")
            df, device = score_image_paths(
                [Path("/photos/a.jpg")],
                dependencies=make_dependencies(cache_df=cache_df, insights=[], calls=calls),
                cache_path=cache_path,
                use_cache=True,
                model_loader=lambda _device: self.fail("core model should not load"),
                clip_reference_loader=lambda _device: self.fail("clip model should not load"),
                selected_models=[MODEL_LLM_REVIEW],
                progress_callback=lambda done, total, path, state: progress.append((done, total, path.name, state)),
            )

        self.assertEqual(device, "cpu")
        self.assertEqual(float(df.loc[0, "llm_review_overall_0_10"]), 8.8)
        self.assertEqual(len(calls["llm_paths"]), 1)
        self.assertEqual(calls["saved_cache"]["existing_rows"], 1)
        self.assertEqual(len(calls["saved_insights"][0]), 1)
        self.assertEqual([item[3] for item in progress], ["started", "llm_done", "reviewed"])

    def test_cached_llm_scores_with_matching_insight_stay_cached(self) -> None:
        cache_df = pd.DataFrame(
            [
                {
                    "file_id": "image-1",
                    "path": "/photos/a.jpg",
                    "filename": "a.jpg",
                    "error": "",
                    "llm_review_overall_0_10": 7.1,
                }
            ]
        )
        matching_insight = AnalysisInsight(
            file_id="image-1",
            analyzer_key=MODEL_LLM_REVIEW,
            provider="test-provider",
            model="test-model",
            model_version="test-model",
            prompt_version="prompt-v1",
        )
        calls: dict[str, object] = {}
        progress: list[tuple[int, int, str, str]] = []

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            cache_path.write_text("", encoding="utf-8")
            df, _device = score_image_paths(
                [Path("/photos/a.jpg")],
                dependencies=make_dependencies(cache_df=cache_df, insights=[matching_insight], calls=calls),
                cache_path=cache_path,
                use_cache=True,
                model_loader=lambda _device: self.fail("core model should not load"),
                clip_reference_loader=lambda _device: self.fail("clip model should not load"),
                selected_models=[MODEL_LLM_REVIEW],
                progress_callback=lambda done, total, path, state: progress.append((done, total, path.name, state)),
            )

        self.assertEqual(float(df.loc[0, "llm_review_overall_0_10"]), 7.1)
        self.assertNotIn("llm_paths", calls)
        self.assertNotIn("saved_insights", calls)
        self.assertEqual([item[3] for item in progress], ["cached"])


if __name__ == "__main__":
    unittest.main()
