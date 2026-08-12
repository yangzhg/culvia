from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from culvia.insight_store import AnalysisInsight, AnalysisInsightMatch
from culvia.schema import (
    LLM_REVIEW_GENERATION_COLUMN,
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
    current_insight_generations: dict[str, float] | None = None,
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

    @contextmanager
    def open_checkpoint_writer(cache_path: str | Path):
        class Writer:
            def upsert(self, df: pd.DataFrame) -> None:
                call_log.setdefault("save_order", []).append("cache")
                call_log.setdefault("checkpointed", []).append(df.copy())
                call_log["saved_cache"] = {
                    "df": df.copy(),
                    "cache_path": str(cache_path),
                }

        yield Writer()

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
            created_at=2.0,
        )
        return SimpleNamespace(scores={"llm_review_overall": 8.8}, insights=[insight])

    def apply_llm_review_scores(
        record: dict[str, object], scores: dict[str, float], *, generation: float
    ) -> dict[str, object]:
        record["llm_review_overall_0_10"] = scores["llm_review_overall"]
        record[LLM_REVIEW_GENERATION_COLUMN] = generation
        return record

    def save_analysis_insights(saved_insights: list[AnalysisInsight], cache_path: str | Path) -> None:
        call_log.setdefault("save_order", []).append("insight")
        call_log["saved_insights"] = (list(saved_insights), str(cache_path))

    return ScoreImagePathDependencies(
        build_file_id=lambda _path: "image-1",
        get_device=lambda: "cpu",
        normalize_selected_models=lambda value: [str(item) for item in value or []],
        model_recompute_plan=lambda _record, _models: dict(active_recompute_plan),
        model_output_fields=lambda model_key: (model_key,),
        load_cache_records=lambda _cache_path: cache_df.copy() if cache_df is not None else pd.DataFrame(),
        open_checkpoint_writer=open_checkpoint_writer,
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
        load_latest_matching_analysis_insight_results=lambda _cache_path, **_identity: {
            file_id: AnalysisInsightMatch(generation)
            for file_id, generation in (current_insight_generations or {}).items()
        },
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
                dependencies=make_dependencies(
                    cache_df=cache_df,
                    current_insight_generations={},
                    calls=calls,
                ),
                cache_path=cache_path,
                use_cache=True,
                model_loader=lambda _device: self.fail("core model should not load"),
                clip_reference_loader=lambda _device: self.fail("clip model should not load"),
                selected_models=[MODEL_LLM_REVIEW],
                progress_callback=lambda done, total, path, state: progress.append((done, total, path.name, state)),
                publish_result=lambda _df: calls.setdefault("save_order", []).append("publish"),
            )

        self.assertEqual(device, "cpu")
        self.assertEqual(float(df.loc[0, "llm_review_overall_0_10"]), 8.8)
        self.assertEqual(len(calls["llm_paths"]), 1)
        self.assertEqual(len(calls["checkpointed"]), 1)
        self.assertEqual(len(calls["saved_insights"][0]), 1)
        self.assertEqual(calls["save_order"], ["cache", "insight", "publish"])
        self.assertEqual([item[3] for item in progress], ["started", "llm_done", "reviewed"])

    def test_cached_llm_scores_with_matching_insight_stay_cached(self) -> None:
        cache_df = pd.DataFrame(
            [
                {
                    "file_id": "image-1",
                    "path": "/photos/a.jpg",
                    "filename": "a.jpg",
                    "error": "",
                    LLM_REVIEW_GENERATION_COLUMN: 1.0,
                    "llm_review_overall_0_10": 7.1,
                }
            ]
        )
        calls: dict[str, object] = {}
        progress: list[tuple[int, int, str, str]] = []

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            cache_path.write_text("", encoding="utf-8")
            df, _device = score_image_paths(
                [Path("/photos/a.jpg")],
                dependencies=make_dependencies(
                    cache_df=cache_df,
                    current_insight_generations={"image-1": 1.0},
                    calls=calls,
                ),
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

    def test_legacy_cached_llm_score_is_recomputed_without_a_generation(self) -> None:
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

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            cache_path.write_text("", encoding="utf-8")
            df, _device = score_image_paths(
                [Path("/photos/a.jpg")],
                dependencies=make_dependencies(
                    cache_df=cache_df,
                    current_insight_generations={"image-1": 1.0},
                    calls=calls,
                ),
                cache_path=cache_path,
                use_cache=True,
                model_loader=lambda _device: self.fail("core model should not load"),
                clip_reference_loader=lambda _device: self.fail("clip model should not load"),
                selected_models=[MODEL_LLM_REVIEW],
            )

        self.assertEqual(len(calls["llm_paths"]), 1)
        self.assertEqual(float(df.loc[0, LLM_REVIEW_GENERATION_COLUMN]), 2.0)
        self.assertEqual(float(df.loc[0, "llm_review_overall_0_10"]), 8.8)

    def test_inactive_llm_scores_are_masked_when_cached_generation_is_stale(self) -> None:
        cache_df = pd.DataFrame(
            [
                {
                    "file_id": "image-1",
                    "path": "/photos/a.jpg",
                    "filename": "a.jpg",
                    "error": "",
                    LLM_REVIEW_GENERATION_COLUMN: 1.0,
                    "llm_review_overall_0_10": 9.7,
                    "recommendation_0_10": 9.9,
                }
            ]
        )
        calls: dict[str, object] = {}

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            cache_path.write_text("", encoding="utf-8")
            df, _device = score_image_paths(
                [Path("/photos/a.jpg")],
                dependencies=make_dependencies(
                    cache_df=cache_df,
                    current_insight_generations={"image-1": 2.0},
                    calls=calls,
                ),
                cache_path=cache_path,
                use_cache=True,
                model_loader=lambda _device: self.fail("core model should not load"),
                clip_reference_loader=lambda _device: self.fail("clip model should not load"),
                selected_models=[MODEL_BASIC_TECHNICAL],
            )

        self.assertTrue(pd.isna(df.loc[0, LLM_REVIEW_GENERATION_COLUMN]))
        self.assertTrue(pd.isna(df.loc[0, "llm_review_overall_0_10"]))
        self.assertTrue(pd.isna(df.loc[0, "recommendation_0_10"]))
        saved = calls["saved_cache"]["df"]
        self.assertTrue(pd.isna(saved.loc[0, LLM_REVIEW_GENERATION_COLUMN]))
        self.assertTrue(pd.isna(saved.loc[0, "llm_review_overall_0_10"]))
        self.assertTrue(pd.isna(saved.loc[0, "recommendation_0_10"]))

    def test_llm_insight_save_failure_invalidates_the_checkpointed_generation(self) -> None:
        calls: dict[str, object] = {}
        dependencies = make_dependencies(
            cache_df=pd.DataFrame(),
            current_insight_generations={},
            recompute_plan=base_plan(llm_review=True),
            calls=calls,
        )
        dependencies = ScoreImagePathDependencies(
            **{
                **dependencies.__dict__,
                "save_analysis_insights": lambda _insights, _cache_path: (_ for _ in ()).throw(
                    RuntimeError("insight write failed")
                ),
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            with self.assertRaisesRegex(RuntimeError, "insight write failed"):
                score_image_paths(
                    [Path("/photos/a.jpg")],
                    dependencies=dependencies,
                    cache_path=cache_path,
                    use_cache=True,
                    model_loader=lambda _device: self.fail("core model should not load"),
                    clip_reference_loader=lambda _device: self.fail("clip model should not load"),
                    selected_models=[MODEL_LLM_REVIEW],
                )

        checkpoints = calls["checkpointed"]
        self.assertEqual(len(checkpoints), 2)
        published = checkpoints[0].iloc[0]
        invalidated = checkpoints[1].iloc[0]
        self.assertEqual(float(published[LLM_REVIEW_GENERATION_COLUMN]), 2.0)
        self.assertTrue(pd.isna(invalidated[LLM_REVIEW_GENERATION_COLUMN]))
        self.assertTrue(pd.isna(invalidated["llm_review_overall_0_10"]))


if __name__ == "__main__":
    unittest.main()
