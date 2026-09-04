from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd

from culvia.app_state import AppStateStore
from culvia.insight_store import AnalysisInsightMatch
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
            "refreshed": [],
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
        ) -> dict[str, AnalysisInsightMatch]:
            self.assertEqual(cache_path, "/tmp/culvia_scores.sqlite")
            self.assertEqual(analyzer_key, "llm_review")
            self.assertEqual(provider, "current-provider")
            self.assertEqual(model, "current-model")
            self.assertEqual(model_version, "current-model")
            self.assertEqual(prompt_version, "current-prompt")
            calls["matchingInsightFileIds"] = list(file_ids)
            return {
                "a": AnalysisInsightMatch(1.0),
                "b": AnalysisInsightMatch(1.0),
            }

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
            default_cache_path=Path("/tmp/default.sqlite"),
            heif_available=True,
            model_llm_review="llm_review",
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
            normalize_score_dataframe=lambda value: value.copy(),
            refresh_persisted_llm_config=lambda cache_path: calls["refreshed"].append(cache_path),
            frame_file_ids=lambda df: [str(value) for value in df.get("file_id", [])],
            load_photo_marks=lambda cache_path, file_ids: marks,
            dataframe_for_display=dataframe_for_display,
            selected_preview_for_display=selected_preview_for_display,
            load_latest_matching_analysis_insight_results=load_latest_matching_analysis_insight_results,
            load_analysis_insights=load_analysis_insights,
            llm_review_score_columns=("llm_review_overall_0_10",),
            llm_review_generation_column="llm_review_generation",
            llm_review_provider=lambda: "current-provider",
            llm_review_model_name=lambda: "current-model",
            llm_review_prompt_version=lambda: "current-prompt",
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

        self.assertEqual(calls["refreshed"], ["/tmp/culvia_scores.sqlite"])
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
            {"sourceRows": 2, "showing": 1, "errors": 1, "limit": 80, "matched": 1},
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

        payload["source"]["folders"].append("/mutated")
        self.assertEqual(store.data["source"]["folders"], ["/photos"])
        payload["sourcePreview"]["folders"].append("/mutated")
        self.assertEqual(store.data["sourcePreview"]["folders"], ["/photos"])


if __name__ == "__main__":
    unittest.main()
