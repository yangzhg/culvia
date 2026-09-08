from __future__ import annotations

import unittest
from typing import Any

import pandas as pd

from culvia.insight_store import AnalysisInsight, AnalysisInsightMatch
from culvia.schema import (
    LLM_REVIEW_FIELDS,
    LLM_REVIEW_GENERATION_COLUMN,
    MODEL_CAPABILITIES,
    MODEL_CORE_AESTHETIC,
    MODEL_LLM_REVIEW,
    MODEL_RESULT_VERSION_COLUMNS,
    field_group_for_model,
)
from culvia.score_view import CurrentScoreViewDependencies, load_current_score_view


def complete_scores(model_key: str, value: float) -> dict[str, float]:
    return {column: value for column in field_group_for_model(model_key).cache_columns}


def llm_scores(value: float) -> dict[str, float]:
    return {f"{field}_0_10": value for field in LLM_REVIEW_FIELDS}


class CurrentScoreViewTests(unittest.TestCase):
    def test_text_identity_uses_current_local_scores_and_exact_generation(self) -> None:
        current_version = MODEL_CAPABILITIES[MODEL_CORE_AESTHETIC].result_version
        source = pd.DataFrame(
            [
                {
                    "file_id": "current",
                    **complete_scores(MODEL_CORE_AESTHETIC, 8.0),
                    MODEL_RESULT_VERSION_COLUMNS[MODEL_CORE_AESTHETIC]: current_version,
                    LLM_REVIEW_GENERATION_COLUMN: 1.0,
                    **llm_scores(8.0),
                },
                {
                    "file_id": "stale-local",
                    **complete_scores(MODEL_CORE_AESTHETIC, 9.0),
                    MODEL_RESULT_VERSION_COLUMNS[MODEL_CORE_AESTHETIC]: "score-v1:old",
                    LLM_REVIEW_GENERATION_COLUMN: 2.0,
                    **llm_scores(9.0),
                },
                {
                    "file_id": "generation-mismatch",
                    **complete_scores(MODEL_CORE_AESTHETIC, 6.0),
                    MODEL_RESULT_VERSION_COLUMNS[MODEL_CORE_AESTHETIC]: current_version,
                    LLM_REVIEW_GENERATION_COLUMN: 3.0,
                    **llm_scores(6.0),
                },
            ]
        )
        calls: dict[str, Any] = {}

        def build_prompt_version(
            record: dict[str, Any],
            *,
            prompt_version: str,
            input_mode: str,
        ) -> str:
            self.assertEqual(input_mode, "text")
            overall = record.get("overall_0_10")
            score_identity = "missing" if pd.isna(overall) else f"{float(overall):g}"
            return f"{prompt_version}:{score_identity}"

        def load_matching_results(
            cache_path: str,
            *,
            file_ids: list[str],
            analyzer_key: str,
            provider: str,
            model: str,
            model_version: str,
            prompt_version: str,
            prompt_versions_by_file_id: dict[str, str] | None,
        ) -> dict[str, AnalysisInsightMatch]:
            self.assertEqual(cache_path, "/tmp/current.sqlite")
            self.assertEqual(file_ids, ["current", "stale-local", "generation-mismatch"])
            self.assertEqual(analyzer_key, MODEL_LLM_REVIEW)
            self.assertEqual((provider, model, model_version), ("provider", "model", "model"))
            self.assertEqual(prompt_version, "prompt")
            self.assertEqual(
                prompt_versions_by_file_id,
                {
                    "current": "prompt:8",
                    "stale-local": "prompt:missing",
                    "generation-mismatch": "prompt:6",
                },
            )
            return {
                "current": AnalysisInsightMatch(1.0),
                "generation-mismatch": AnalysisInsightMatch(4.0),
            }

        dependencies = CurrentScoreViewDependencies(
            normalize_dataframe=lambda value: value.copy(),
            load_matching_results=load_matching_results,
            llm_review_provider=lambda: "provider",
            llm_review_model_name=lambda: "model",
            llm_review_prompt_version=lambda: "prompt",
            llm_review_result_prompt_version=build_prompt_version,
            llm_review_input_mode=lambda: "text",
        )

        view = load_current_score_view(source, "/tmp/current.sqlite", dependencies)
        rows = view.dataframe.set_index("file_id")

        self.assertEqual(view.current_llm_file_ids, frozenset({"current"}))
        self.assertEqual(float(rows.loc["current", "llm_review_overall_0_10"]), 8.0)
        self.assertTrue(pd.isna(rows.loc["stale-local", "overall_0_10"]))
        self.assertTrue(pd.isna(rows.loc["stale-local", "llm_review_overall_0_10"]))
        self.assertTrue(pd.isna(rows.loc["generation-mismatch", "llm_review_overall_0_10"]))
        self.assertEqual(
            view.local_summary[MODEL_CORE_AESTHETIC],
            {"current": 2, "legacy": 0, "stale": 1, "incomplete": 0, "missing": 0},
        )

        def load_insights(cache_path: str, *, file_ids: list[str]) -> list[AnalysisInsight]:
            self.assertEqual(cache_path, "/tmp/current.sqlite")
            calls["insight_file_ids"] = file_ids
            return [
                AnalysisInsight(
                    file_id="current",
                    analyzer_key=MODEL_LLM_REVIEW,
                    provider="provider",
                    model="model",
                    model_version="model",
                    prompt_version="prompt:8",
                    title="current insight",
                    created_at=1.0,
                ),
                AnalysisInsight(
                    file_id="current",
                    analyzer_key=MODEL_LLM_REVIEW,
                    provider="provider",
                    model="model",
                    model_version="model",
                    prompt_version="prompt:stale",
                    title="wrong prompt",
                    created_at=1.0,
                ),
                AnalysisInsight(
                    file_id="stale-local",
                    analyzer_key=MODEL_LLM_REVIEW,
                    provider="provider",
                    model="model",
                    model_version="model",
                    prompt_version="prompt:missing",
                    title="not current",
                    created_at=2.0,
                ),
            ]

        insights = view.load_current_insights(
            ["stale-local", "current", "current", "not-requested"],
            load_insights,
        )

        self.assertEqual(calls["insight_file_ids"], ["current"])
        self.assertEqual(list(insights), ["current"])
        self.assertEqual(insights["current"].title, "current insight")

    def test_image_identity_uses_one_prompt_version(self) -> None:
        source = pd.DataFrame(
            [
                {
                    "file_id": "image",
                    LLM_REVIEW_GENERATION_COLUMN: 5.0,
                    **llm_scores(7.0),
                }
            ]
        )

        def load_matching_results(
            _cache_path: str,
            *,
            prompt_versions_by_file_id: dict[str, str] | None,
            **_identity: Any,
        ) -> dict[str, AnalysisInsightMatch]:
            self.assertIsNone(prompt_versions_by_file_id)
            return {"image": AnalysisInsightMatch(5.0)}

        dependencies = CurrentScoreViewDependencies(
            normalize_dataframe=lambda value: value.copy(),
            load_matching_results=load_matching_results,
            llm_review_provider=lambda: "provider",
            llm_review_model_name=lambda: "model",
            llm_review_prompt_version=lambda: "prompt",
            llm_review_result_prompt_version=lambda _record, **_identity: self.fail(
                "image mode must not build per-file prompt identities"
            ),
            llm_review_input_mode=lambda: "image",
        )

        view = load_current_score_view(source, "/tmp/current.sqlite", dependencies)

        self.assertEqual(view.current_llm_file_ids, frozenset({"image"}))
        self.assertEqual(float(view.dataframe.loc[0, "llm_review_overall_0_10"]), 7.0)

    def test_disabled_persistent_cache_never_loads_identity_or_insights(self) -> None:
        source = pd.DataFrame(
            [
                {
                    "file_id": "image",
                    LLM_REVIEW_GENERATION_COLUMN: 5.0,
                    **llm_scores(7.0),
                }
            ]
        )

        def persistent_access(*_args: Any, **_kwargs: Any) -> Any:
            self.fail("disabled persistent cache must not be accessed")

        dependencies = CurrentScoreViewDependencies(
            normalize_dataframe=lambda value: value.copy(),
            load_matching_results=persistent_access,
            llm_review_provider=persistent_access,
            llm_review_model_name=persistent_access,
            llm_review_prompt_version=persistent_access,
            llm_review_result_prompt_version=persistent_access,
            llm_review_input_mode=persistent_access,
        )

        view = load_current_score_view(
            source,
            "/tmp/current.sqlite",
            dependencies,
            allow_persistent_cache=False,
        )

        self.assertEqual(view.current_llm_file_ids, frozenset())
        self.assertTrue(pd.isna(view.dataframe.loc[0, LLM_REVIEW_GENERATION_COLUMN]))
        self.assertTrue(pd.isna(view.dataframe.loc[0, "llm_review_overall_0_10"]))
        self.assertEqual(view.load_current_insights(["image"], persistent_access), {})


if __name__ == "__main__":
    unittest.main()
