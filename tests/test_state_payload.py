from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any

import pandas as pd

from culvia.app_state import AppStateStore
from culvia.curation import PhotoMark, curation_summary
from culvia.insight_store import AnalysisInsightMatch
from culvia.payloads import summarize_scores
from culvia.score_view import CurrentScoreView, CurrentScoreViewDependencies, load_current_score_view
from culvia.state_payload import StatePayloadDependencies, build_state_payload


class StatePayloadBuilderTests(unittest.TestCase):
    def test_build_state_payload_composes_display_photos_and_curation_without_app_module(self) -> None:
        source_df = pd.DataFrame(
            [
                {
                    "file_id": "a",
                    "path": "/photos/a.jpg",
                    "llm_review_generation": 3.0,
                    "llm_review_overall_0_10": 7.0,
                },
                {
                    "file_id": "b",
                    "path": "/photos/b.jpg",
                    "llm_review_generation": 1.0,
                    "llm_review_overall_0_10": 8.0,
                },
            ]
        )
        store = AppStateStore(
            {
                "scores_df": source_df,
                "source": {"mode": "folders", "folders": ["/photos"], "cachePath": "/tmp/culvia_scores.sqlite"},
                "sourcePreview": {
                    "mode": "folders",
                    "folders": ["/photos"],
                    "cachePath": "/tmp/culvia_scores.sqlite",
                    "total": 2,
                    "ready": True,
                },
                "filters": {"limit": 80},
                "network": {"mode": "direct"},
                "models": {"selected": ["core"]},
                "job": {"phase": "idle", "running": False},
            }
        )
        calls: dict[str, Any] = {
            "matchingInsightFileIds": [],
            "insightFileIds": [],
        }
        marks = {"a": SimpleNamespace(status="pick")}

        def dataframe_for_display(
            df: pd.DataFrame,
            _filters: dict[str, Any],
            _marks: dict[str, Any],
        ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
            self.assertTrue(pd.isna(df.loc[df["file_id"].eq("a"), "llm_review_overall_0_10"]).all())
            self.assertEqual(float(df.loc[df["file_id"].eq("b"), "llm_review_overall_0_10"].iloc[0]), 8.0)
            return df.copy(), df[df["file_id"].eq("b")].copy(), pd.DataFrame([{"file_id": "err"}])

        def selected_preview_for_display(df: pd.DataFrame, _marks: dict[str, Any], *, limit: int) -> pd.DataFrame:
            self.assertEqual(limit, 80)
            return df[df["file_id"].eq("a")].copy()

        def load_analysis_insights(cache_path: str, *, file_ids: list[str]):
            self.assertEqual(cache_path, "/tmp/culvia_scores.sqlite")
            calls["insightFileIds"] = list(file_ids)
            return [
                SimpleNamespace(
                    file_id="b",
                    analyzer_key="llm_review",
                    provider="current-provider",
                    model="current-model",
                    model_version="current-model",
                    prompt_version="current-prompt",
                    created_at=1.0,
                    title="current",
                ),
                SimpleNamespace(
                    file_id="b",
                    analyzer_key="llm_review",
                    provider="current-provider",
                    model="current-model",
                    model_version="current-model",
                    prompt_version="stale-prompt",
                    created_at=2.0,
                    title="newer but stale",
                ),
                SimpleNamespace(
                    file_id="a",
                    analyzer_key="other",
                    provider="current-provider",
                    model="current-model",
                    model_version="current-model",
                    prompt_version="current-prompt",
                    created_at=3.0,
                    title="ignored",
                ),
            ]

        def load_latest_matching_analysis_insight_results(
            cache_path: str,
            *,
            file_ids: list[str],
            analyzer_key: str,
            provider: str,
            model: str,
            model_version: str,
            prompt_version: str,
            prompt_versions_by_file_id: dict[str, str] | None = None,
        ) -> dict[str, AnalysisInsightMatch]:
            self.assertEqual(cache_path, "/tmp/culvia_scores.sqlite")
            self.assertEqual(analyzer_key, "llm_review")
            self.assertEqual(provider, "current-provider")
            self.assertEqual(model, "current-model")
            self.assertEqual(model_version, "current-model")
            self.assertEqual(prompt_version, "current-prompt")
            self.assertIsNone(prompt_versions_by_file_id)
            calls["matchingInsightFileIds"] = list(file_ids)
            return {
                "a": AnalysisInsightMatch(1.0),
                "b": AnalysisInsightMatch(1.0),
            }

        score_view_dependencies = CurrentScoreViewDependencies(
            normalize_dataframe=lambda value: value.copy(),
            load_matching_results=load_latest_matching_analysis_insight_results,
            llm_review_provider=lambda: "current-provider",
            llm_review_model_name=lambda: "current-model",
            llm_review_prompt_version=lambda: "current-prompt",
            llm_review_result_prompt_version=lambda _context, **_identity: self.fail(
                "image-mode state must not build per-photo prompt identities"
            ),
            llm_review_input_mode=lambda: "image",
        )

        def current_score_view(
            value: pd.DataFrame,
            cache_path: str,
            *,
            allow_persistent_cache: bool,
        ):
            self.assertTrue(allow_persistent_cache)
            return load_current_score_view(value, cache_path, score_view_dependencies)

        def serialize_photo(
            row: pd.Series, insight_by_file_id: dict[str, Any], mark_by_file_id: dict[str, Any]
        ) -> dict[str, Any]:
            file_id = str(row["file_id"])
            insight = insight_by_file_id.get(file_id)
            return {
                "fileId": file_id,
                "insight": getattr(insight, "title", None),
                "llmScore": None
                if pd.isna(row.get("llm_review_overall_0_10"))
                else float(row["llm_review_overall_0_10"]),
                "marked": file_id in mark_by_file_id,
            }

        deps = StatePayloadDependencies(
            app_name="Test Studio",
            app_subtitle="Test Workbench",
            heif_available=True,
            sort_fields=("recommendation_0_10",),
            sort_field_labels={"recommendation_0_10": "推荐"},
            model_agreement_options=({"value": "all", "label": "全部"},),
            manual_status_options=({"value": "all", "label": "全部"},),
            color_label_options=({"value": "all", "label": "全部"},),
            weight_presets={"balanced": {"label": "均衡"}},
            score_labels={"overall": "整体"},
            technical_labels={"sharpness": "清晰度"},
            model_quality_labels={"clip_iqa_overall": "画质"},
            aesthetic_reference_labels={"clip_aesthetic": "参考审美"},
            llm_review_labels={"llm_review_overall": "大模型"},
            current_score_view=current_score_view,
            frame_file_ids=lambda df: [str(value) for value in df.get("file_id", [])],
            load_photo_marks=lambda cache_path, file_ids: marks,
            dataframe_for_display=dataframe_for_display,
            selected_preview_for_display=selected_preview_for_display,
            load_analysis_insights=load_analysis_insights,
            llm_review_score_columns=("llm_review_overall_0_10",),
            serialize_photo=serialize_photo,
            curation_summary=lambda mark_by_file_id, file_ids: {
                "fileIds": list(file_ids),
                "markCount": len(mark_by_file_id),
            },
            application_info=lambda: {
                "version": "9.8.7",
                "serviceVersion": "9.8.7",
                "distribution": "python",
            },
            local_capabilities=lambda: {"desktop": True},
            device_text=lambda: {"key": "device.genericCpu"},
            network_payload=lambda network: {"mode": network["mode"]},
            llm_config_payload=lambda: {"configured": True},
            normalize_selected_models=lambda selected: ["normalized", *(selected or [])],
            model_payload=lambda network, selected: {"network": network["mode"], "selected": list(selected)},
            maintenance_model_payload=lambda network, selected: {
                "network": network["mode"],
                "selected": list(selected),
            },
            summarize_scores=lambda source, filtered, errors, filters: {
                "sourceRows": len(source),
                "showing": len(filtered),
                "errors": len(errors),
                "limit": filters["limit"],
            },
        )

        payload = build_state_payload(store, deps)

        self.assertEqual(calls["matchingInsightFileIds"], ["a", "b"])
        self.assertEqual(calls["insightFileIds"], ["b"])
        self.assertEqual(payload["app"]["name"], "Test Studio")
        self.assertTrue(payload["app"]["heifAvailable"])
        self.assertEqual(payload["app"]["version"], "9.8.7")
        self.assertEqual(payload["app"]["distribution"], "python")
        self.assertEqual(payload["network"], {"mode": "direct"})
        self.assertEqual(payload["llm"], {"configured": True})
        self.assertEqual(payload["model"], {"network": "direct", "selected": ["normalized", "core"]})
        self.assertEqual(payload["sourcePreview"]["total"], 2)
        self.assertTrue(payload["sourcePreview"]["ready"])
        self.assertEqual(
            payload["summary"],
            {"sourceRows": 2, "total": 2, "showing": 1, "errors": 1, "limit": 80, "matched": 1},
        )
        self.assertEqual(
            payload["photos"],
            [{"fileId": "b", "insight": "current", "llmScore": 8.0, "marked": False}],
        )
        self.assertEqual(
            payload["selectedPhotos"],
            [{"fileId": "a", "insight": None, "llmScore": None, "marked": True}],
        )
        self.assertEqual(payload["curation"]["all"]["fileIds"], ["a", "b"])
        self.assertEqual(payload["curation"]["filtered"]["fileIds"], ["b"])
        self.assertEqual(payload["curation"]["visible"]["fileIds"], ["b"])
        self.assertEqual(payload["curation"]["filteredLlmReviewedCount"], 1)
        self.assertEqual(payload["curation"]["selectedPreviewCount"], 1)
        self.assertEqual(
            {key: states["missing"] for key, states in payload["scoreProvenance"]["summary"].items()},
            {"rsinema_aesthetic": 2, "clip_iqa": 2, "clip_aesthetic": 2},
        )

        payload["source"]["folders"].append("/mutated")
        self.assertEqual(store.data["source"]["folders"], ["/photos"])
        payload["sourcePreview"]["folders"].append("/mutated")
        self.assertEqual(store.data["sourcePreview"]["folders"], ["/photos"])

    def count_payload(self, total: int, scored: int, *, matched: int | None = None, limit: int = 80) -> dict[str, Any]:
        source_df = pd.DataFrame(
            [
                {
                    "file_id": f"photo-{index}",
                    "path": f"/photos/photo-{index}.jpg",
                    "recommendation_0_10": 8.0 if index < scored else None,
                    "error": "",
                }
                for index in range(total)
            ],
            columns=["file_id", "path", "recommendation_0_10", "error"],
        )
        marks = {"photo-0": PhotoMark("photo-0", status="pick")} if total else {}
        store = AppStateStore(
            {
                "scores_df": source_df,
                "source": {"mode": "uploads", "cachePath": "/tmp/culvia-counts.sqlite"},
                "sourcePreview": {"total": 999},
                "filters": {"limit": limit},
                "network": {},
                "models": {},
                "job": {"running": False},
            }
        )
        deps = StatePayloadDependencies(
            app_name="Test Studio",
            app_subtitle="",
            heif_available=True,
            sort_fields=(),
            sort_field_labels={},
            model_agreement_options=(),
            manual_status_options=(),
            color_label_options=(),
            weight_presets={},
            score_labels={},
            technical_labels={},
            model_quality_labels={},
            aesthetic_reference_labels={},
            llm_review_labels={},
            current_score_view=lambda df, _cache_path, **_options: CurrentScoreView(df.copy(), {}, frozenset()),
            frame_file_ids=lambda df: df["file_id"].tolist(),
            load_photo_marks=lambda _cache_path, _file_ids: marks,
            dataframe_for_display=lambda df, _filters, _marks: (
                df.copy(),
                df.head(total if matched is None else matched).copy(),
                df.iloc[0:0].copy(),
            ),
            selected_preview_for_display=lambda df, _marks, *, limit: df[df["file_id"].isin(marks)].head(limit),
            load_analysis_insights=lambda *_args, **_kwargs: [],
            llm_review_score_columns=(),
            serialize_photo=lambda row, _insights, _marks: {"fileId": row["file_id"]},
            curation_summary=curation_summary,
            application_info=lambda: {},
            local_capabilities=lambda: {},
            device_text=lambda: {},
            network_payload=lambda _network: {},
            llm_config_payload=lambda: {},
            normalize_selected_models=lambda _selected: [],
            model_payload=lambda _network, _selected: {},
            maintenance_model_payload=lambda _network, _selected: {},
            summarize_scores=lambda source, filtered, errors, filters: summarize_scores(
                source,
                filtered,
                errors,
                filters,
                enrich_scores_for_display=lambda df, _filters: df.copy(),
            ),
        )
        return build_state_payload(store, deps)

    def test_source_total_includes_unscored_photos(self) -> None:
        payload = self.count_payload(2, 0)

        self.assertEqual(payload["summary"]["total"], 2)
        self.assertEqual(payload["summary"]["scored"], 0)
        self.assertEqual(payload["curation"]["all"]["selected"], 1)
        self.assertEqual(payload["source"]["mode"], "uploads")

    def test_source_total_does_not_change_with_score_coverage(self) -> None:
        for scored in (0, 1, 3):
            with self.subTest(scored=scored):
                payload = self.count_payload(3, scored)
                self.assertEqual(payload["summary"]["total"], 3)
                self.assertEqual(payload["summary"]["scored"], scored)

    def test_source_total_is_independent_of_filter_display_limit_and_old_scan(self) -> None:
        payload = self.count_payload(200, 1, matched=100, limit=2)

        self.assertEqual(payload["summary"]["total"], 200)
        self.assertEqual(payload["summary"]["matched"], 100)
        self.assertEqual(payload["summary"]["showing"], 2)
        self.assertEqual(len(payload["photos"]), 2)
        self.assertEqual(payload["sourcePreview"]["total"], 999)

    def test_empty_source_has_zero_total_and_zero_scored_photos(self) -> None:
        payload = self.count_payload(0, 0)

        self.assertEqual(payload["summary"]["total"], 0)
        self.assertEqual(payload["summary"]["scored"], 0)
        self.assertEqual(payload["summary"]["matched"], 0)
        self.assertEqual(payload["photos"], [])


if __name__ == "__main__":
    unittest.main()
