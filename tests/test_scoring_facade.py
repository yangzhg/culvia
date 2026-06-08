from __future__ import annotations

import sqlite3
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from PIL import Image
from starlette.datastructures import QueryParams

import culvia_app
from culvia import scoring
from culvia import curation as photo_curation


def make_image(path: Path, size: tuple[int, int] = (1600, 900)) -> Path:
    image = Image.new("RGB", size, (96, 128, 180))
    image.save(path, format="JPEG", quality=92)
    return path


def restore_llm_config_layers(layers: dict[str, dict[str, str]]) -> None:
    scoring.clear_session_llm_config()
    scoring.clear_secure_llm_config()
    scoring.set_session_llm_config(layers.get("session", {}), replace=True)
    scoring.set_secure_llm_config(layers.get("keychain", {}))
    scoring.set_persisted_llm_config(layers.get("sqlite", {}))


class CacheSchemaTests(unittest.TestCase):
    def test_sqlite_roundtrip_preserves_new_model_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            source = pd.DataFrame(
                [
                    {
                        "file_id": "image-1",
                        "path": "/photos/a.jpg",
                        "folder": "/photos",
                        "filename": "a.jpg",
                        "error": "",
                        "overall_0_10": 8.2,
                    }
                ]
            )

            scoring.save_cache_records(source, cache_path)
            loaded = scoring.load_cache_records(cache_path)

            self.assertEqual(list(loaded.columns), scoring.CSV_COLUMNS)
            self.assertEqual(loaded.loc[0, "file_id"], "image-1")
            self.assertAlmostEqual(float(loaded.loc[0, "overall_0_10"]), 8.2)
            self.assertTrue(pd.isna(loaded.loc[0, "clip_iqa_overall_0_10"]))

    def test_sqlite_schema_creates_score_and_insight_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            scoring.save_cache_records(pd.DataFrame(), cache_path)

            with sqlite3.connect(cache_path) as conn:
                tables = {
                    row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
                }
                score_columns = {row[1] for row in conn.execute("PRAGMA table_info(culvia_scores)").fetchall()}

            self.assertIn("clip_aesthetic_0_10", score_columns)
            self.assertIn(scoring.INSIGHT_TABLE, tables)

    def test_curation_marks_roundtrip_and_export_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            mark = photo_curation.save_photo_mark(
                cache_path,
                "image-1",
                rating=4,
                status="pick",
                color_label="green",
                source="llm",
                accepted_score=8.1,
            )

            loaded = photo_curation.load_photo_marks(cache_path, ["image-1"])
            self.assertEqual(loaded["image-1"], mark)
            self.assertEqual(
                photo_curation.curation_summary(loaded, ["image-1"]),
                {"selected": 1, "rejected": 0, "rated": 1, "colorLabeled": 1},
            )

            source = pd.DataFrame(
                [
                    {
                        "file_id": "image-1",
                        "path": "/photos/a.jpg",
                        "folder": "/photos",
                        "filename": "a.jpg",
                        "error": "",
                        "overall_0_10": 8.2,
                    }
                ]
            )
            exported = culvia_app.curation_export_dataframe(source, loaded)

            self.assertEqual(exported.loc[0, "manual_rating"], 4)
            self.assertEqual(exported.loc[0, "manual_status_label"], "入选")
            self.assertEqual(exported.loc[0, "manual_color_label"], "green")
            self.assertEqual(exported.loc[0, "manual_color_label_text"], "绿色")
            self.assertEqual(exported.loc[0, "lightroom_rating"], 4)
            self.assertEqual(exported.loc[0, "lightroom_flag"], "Pick")
            self.assertEqual(exported.loc[0, "lightroom_color_label"], "Green")
            self.assertEqual(exported.loc[0, "capture_one_rating"], 4)
            self.assertEqual(exported.loc[0, "capture_one_color_tag"], "Green")
            self.assertEqual(exported.loc[0, "manual_source"], "大模型")

    def test_curation_mark_color_label_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            photo_curation.save_photo_mark(cache_path, "image-1", rating=2)
            photo_curation.save_photo_mark(cache_path, "image-1", color_label="Purple")
            loaded = photo_curation.load_photo_marks(cache_path, ["image-1"])

            self.assertEqual(loaded["image-1"].color_label, "purple")
            self.assertEqual(photo_curation.color_label_text("purple"), "紫色")
            self.assertEqual(photo_curation.normalize_color_label("not-a-label"), "")

    def test_curation_color_update_preserves_existing_acceptance_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            photo_curation.save_photo_mark(
                cache_path,
                "image-1",
                rating=5,
                status="pick",
                source="llm",
                accepted_score=9.1,
            )

            photo_curation.save_photo_mark(cache_path, "image-1", color_label="blue")
            loaded = photo_curation.load_photo_marks(cache_path, ["image-1"])["image-1"]

        self.assertEqual(loaded.rating, 5)
        self.assertEqual(loaded.status, "pick")
        self.assertEqual(loaded.color_label, "blue")
        self.assertAlmostEqual(float(loaded.accepted_score or 0), 9.1)

    def test_dataframe_display_filters_by_manual_color_label(self) -> None:
        source = pd.DataFrame(
            [
                {
                    "file_id": "image-1",
                    "path": "/photos/a.jpg",
                    "folder": "/photos",
                    "filename": "a.jpg",
                    "error": "",
                    "overall_0_10": 8.4,
                },
                {
                    "file_id": "image-2",
                    "path": "/photos/b.jpg",
                    "folder": "/photos",
                    "filename": "b.jpg",
                    "error": "",
                    "overall_0_10": 8.1,
                },
                {
                    "file_id": "image-3",
                    "path": "/photos/c.jpg",
                    "folder": "/photos",
                    "filename": "c.jpg",
                    "error": "",
                    "overall_0_10": 7.8,
                },
            ]
        )
        marks = {
            "image-1": photo_curation.PhotoMark("image-1", color_label="green"),
            "image-2": photo_curation.PhotoMark("image-2", color_label="red"),
        }
        filters = dict(culvia_app.FILTER_DEFAULTS)
        filters.update({"colorLabel": "red", "limit": 1})

        _working, filtered, _errors = culvia_app.dataframe_for_display(source, filters, marks)

        self.assertEqual(filtered["file_id"].tolist(), ["image-2"])

        filters["colorLabel"] = "none"
        _working, filtered, _errors = culvia_app.dataframe_for_display(source, filters, marks)

        self.assertEqual(filtered["file_id"].tolist(), ["image-3"])

    def test_analysis_insights_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            insight = scoring.AnalysisInsight(
                file_id="image-1",
                analyzer_key="llm_evaluator",
                provider="local-test",
                model="mock-vlm",
                model_version="0.1",
                prompt_version="portrait-v1",
                score=6.5,
                confidence=0.72,
                title="光线略平",
                summary="主体清楚，但光线缺少层次。",
                explanation="背景亮度接近主体，视觉重心不够稳定。",
                suggestions=("提高侧光层次", "裁掉右侧空白"),
                raw_json={"source": "unit-test"},
            )

            scoring.save_analysis_insights([insight], cache_path)
            loaded = scoring.load_analysis_insights(cache_path, file_ids=["image-1"])

            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].prompt_version, "portrait-v1")
            self.assertEqual(loaded[0].suggestions, ("提高侧光层次", "裁掉右侧空白"))
            self.assertEqual(dict(loaded[0].raw_json or {}).get("source"), "unit-test")

    def test_llm_config_sqlite_roundtrip_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"

            saved = scoring.save_llm_config_to_sqlite(
                {
                    "api_key": "sqlite-key",
                    "base_url": "https://example.test/v1",
                    "model": "mock-vlm",
                    "prompt_preset": "technical",
                    "custom_prompt": "重点检查曝光",
                },
                cache_path,
            )
            self.assertNotIn("api_key", saved)

            loaded = scoring.load_llm_config_from_sqlite(cache_path)

            self.assertNotIn("api_key", loaded)
            self.assertEqual(loaded["model"], "mock-vlm")
            self.assertEqual(loaded["prompt_preset"], "technical")

            scoring.save_llm_config_to_sqlite({"api_key": ""}, cache_path)
            loaded = scoring.load_llm_config_from_sqlite(cache_path)

            self.assertNotIn("api_key", loaded)

    def test_llm_config_sqlite_does_not_persist_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            scoring.save_llm_config_to_sqlite(
                {"model": "mock-vlm", "api_key": "secret", "base_url": "https://example.test/v1"},
                cache_path,
            )
            with sqlite3.connect(cache_path) as conn:
                keys = {row[0] for row in conn.execute(f'SELECT "key" FROM {scoring.APP_CONFIG_TABLE}').fetchall()}

            self.assertNotIn("api_key", keys)
            self.assertNotIn("llm_api_key", keys)

    def test_llm_config_priority_env_session_sqlite(self) -> None:
        original_layers = scoring.llm_config_layers()
        self.addCleanup(restore_llm_config_layers, original_layers)
        env_keys = [
            scoring.ENV_LLM_API_KEY,
            "OPENAI_API_KEY",
            scoring.ENV_LLM_BASE_URL,
            scoring.ENV_LLM_ENDPOINT,
            scoring.ENV_LLM_MODEL,
            scoring.ENV_LLM_INPUT_MODE,
            scoring.ENV_LLM_PROMPT_PRESET,
            scoring.ENV_LLM_CUSTOM_PROMPT,
        ]
        original_env = {key: os.environ.get(key) for key in env_keys}
        try:
            for key in env_keys:
                os.environ.pop(key, None)
            scoring.clear_session_llm_config()
            scoring.clear_secure_llm_config()
            scoring.set_persisted_llm_config(
                {"api_key": "sqlite-key", "model": "sqlite-model", "prompt_preset": "retouching"}
            )
            scoring.set_secure_llm_config({"api_key": "keychain-key"})
            scoring.set_session_llm_config({"api_key": "session-key", "base_url": "https://session.test/v1"})
            os.environ[scoring.ENV_LLM_MODEL] = "env-model"

            self.assertEqual(scoring.llm_review_api_key(), "session-key")
            self.assertEqual(scoring.llm_review_model_name(), "env-model")
            self.assertEqual(scoring.llm_review_prompt_preset(), "retouching")
            self.assertEqual(scoring.llm_config_source("api_key"), "当前会话")
            self.assertEqual(scoring.llm_config_source("model"), "环境变量")
            self.assertEqual(scoring.llm_config_layers()["keychain"]["api_key"], "keychain-key")
            self.assertNotIn("api_key", scoring.llm_config_layers()["sqlite"])
        finally:
            scoring.clear_session_llm_config()
            scoring.clear_secure_llm_config()
            scoring.set_persisted_llm_config({})
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_apply_llm_config_persists_api_key_to_keychain_not_sqlite(self) -> None:
        original_layers = scoring.llm_config_layers()
        self.addCleanup(restore_llm_config_layers, original_layers)
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            scoring.clear_session_llm_config()
            scoring.clear_secure_llm_config()
            scoring.set_persisted_llm_config({})
            with patch("culvia_app.save_llm_api_key") as save_key:
                culvia_app.apply_llm_config(
                    {
                        "apiKey": "unit-key",
                        "baseUrl": "https://example.test/v1",
                        "model": "mock-vlm",
                        "promptPreset": "balanced",
                        "persist": True,
                    },
                    cache_path,
                )

            save_key.assert_called_once_with("unit-key")
            loaded = scoring.load_llm_config_from_sqlite(cache_path)
            self.assertNotIn("api_key", loaded)
            self.assertEqual(loaded["model"], "mock-vlm")
            self.assertEqual(scoring.llm_config_layers()["keychain"]["api_key"], "unit-key")

    def test_refresh_persisted_llm_config_loads_keychain_api_key(self) -> None:
        original_layers = scoring.llm_config_layers()
        self.addCleanup(restore_llm_config_layers, original_layers)
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            scoring.save_llm_config_to_sqlite({"model": "mock-vlm"}, cache_path)
            scoring.clear_session_llm_config()
            scoring.clear_secure_llm_config()
            scoring.set_persisted_llm_config({})

            with patch("culvia_app.load_llm_api_key", return_value="keychain-key"):
                culvia_app.refresh_persisted_llm_config(cache_path)

            self.assertEqual(scoring.llm_review_api_key(), "keychain-key")
            self.assertEqual(scoring.llm_config_source("api_key"), "系统钥匙串")
            self.assertEqual(scoring.llm_review_model_name(), "mock-vlm")

    def test_apply_llm_config_clear_key_deletes_keychain_secret(self) -> None:
        original_layers = scoring.llm_config_layers()
        self.addCleanup(restore_llm_config_layers, original_layers)
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            scoring.clear_session_llm_config()
            scoring.clear_secure_llm_config()
            scoring.set_session_llm_config({"api_key": "session-key"})
            scoring.set_secure_llm_config({"api_key": "keychain-key"})

            with patch("culvia_app.delete_llm_api_key") as delete_key:
                culvia_app.apply_llm_config(
                    {"clearKey": True, "promptPreset": "balanced", "persist": True},
                    cache_path,
                )

            delete_key.assert_called_once_with()
            self.assertNotIn("api_key", scoring.llm_config_layers()["session"])
            self.assertNotIn("api_key", scoring.llm_config_layers()["keychain"])

    def test_apply_llm_config_falls_back_to_session_when_keychain_unavailable(self) -> None:
        original_layers = scoring.llm_config_layers()
        self.addCleanup(restore_llm_config_layers, original_layers)
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "scores.sqlite"
            scoring.clear_session_llm_config()
            scoring.clear_secure_llm_config()
            scoring.set_persisted_llm_config({})

            with patch(
                "culvia_app.save_llm_api_key",
                side_effect=culvia_app.SecretStoreUnavailable("missing"),
            ):
                culvia_app.apply_llm_config(
                    {"apiKey": "session-only-key", "promptPreset": "balanced", "persist": True},
                    cache_path,
                )

            self.assertEqual(scoring.llm_review_api_key(), "session-only-key")
            self.assertEqual(scoring.llm_config_source("api_key"), "当前会话")
            self.assertNotIn("api_key", scoring.llm_config_layers()["keychain"])
            self.assertNotIn("api_key", scoring.load_llm_config_from_sqlite(cache_path))

    def test_mask_llm_api_key_keeps_prefix_and_suffix_only(self) -> None:
        masked = scoring.mask_llm_api_key("unit-test-api-key-0000000000003931")

        self.assertEqual(masked, "unit****3931")
        self.assertNotIn("test-api-key-000000000000", masked)


class ModelPlanningTests(unittest.TestCase):
    def test_llm_models_url_uses_openai_compatible_base_url(self) -> None:
        self.assertEqual(
            culvia_app.llm_models_url(
                "https://dashscope.aliyuncs.com/compatible-mode/v1/",
                "https://ignored.test/v1/chat/completions",
            ),
            "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
        )
        self.assertEqual(
            culvia_app.llm_models_url("", "https://api.openai.com/v1/chat/completions"),
            "https://api.openai.com/v1/models",
        )

    def test_parse_llm_model_list_pins_current_model_and_deduplicates(self) -> None:
        models = culvia_app.parse_llm_model_list(
            {
                "data": [
                    {"id": "qwen-plus"},
                    {"id": "qwen3.7-plus"},
                    {"id": "qwen-plus"},
                    {"id": ""},
                ]
            },
            "qwen3.7-plus",
        )

        self.assertEqual([item["value"] for item in models], ["qwen3.7-plus", "qwen-plus"])
        self.assertEqual(models[0]["source"], "current")

    def test_media_paths_are_limited_to_current_source_or_scores(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "photos"
            root.mkdir()
            allowed = make_image(root / "allowed.jpg")
            outside = make_image(Path(tmp) / "outside.jpg")
            with culvia_app.STATE_LOCK:
                original_source = dict(culvia_app.STATE["source"])
                original_scores = culvia_app.STATE["scores_df"].copy()

            try:
                with culvia_app.STATE_LOCK:
                    culvia_app.STATE["source"].update({"mode": "folders", "folders": [str(root)], "uploadedPaths": []})
                    culvia_app.STATE["scores_df"] = pd.DataFrame(columns=scoring.CSV_COLUMNS)

                allowed_path, allowed_status = culvia_app.media_path_from_request(
                    SimpleNamespace(query_params=QueryParams({"path": str(allowed)}))
                )
                denied_path, denied_status = culvia_app.media_path_from_request(
                    SimpleNamespace(query_params=QueryParams({"path": str(outside)}))
                )

                self.assertEqual(allowed_path, allowed.resolve())
                self.assertEqual(allowed_status, 200)
                self.assertIsNone(denied_path)
                self.assertEqual(denied_status, 403)

                file_id = "cached-image"
                with culvia_app.STATE_LOCK:
                    culvia_app.STATE["source"].update({"mode": "folders", "folders": []})
                    culvia_app.STATE["scores_df"] = pd.DataFrame(
                        [
                            {
                                "file_id": file_id,
                                "path": str(outside),
                                "folder": str(outside.parent),
                                "filename": outside.name,
                                "error": "",
                            }
                        ]
                    )

                cached_path, cached_status = culvia_app.media_path_from_request(
                    SimpleNamespace(query_params=QueryParams({"file_id": file_id}))
                )

                self.assertEqual(cached_path, outside.resolve())
                self.assertEqual(cached_status, 200)
            finally:
                with culvia_app.STATE_LOCK:
                    culvia_app.STATE["source"].clear()
                    culvia_app.STATE["source"].update(original_source)
                    culvia_app.STATE["scores_df"] = original_scores

    def test_upload_paths_must_stay_inside_upload_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_upload_dir = culvia_app.UPLOAD_CACHE_DIR
            upload_root = Path(tmp) / "uploads"
            upload_root.mkdir()
            try:
                culvia_app.UPLOAD_CACHE_DIR = upload_root
                (upload_root / "batch").mkdir()
                inside = make_image(upload_root / "batch" / "inside.jpg")
                outside = make_image(Path(tmp) / "outside.jpg")

                sanitized = culvia_app.sanitize_uploaded_paths([inside, outside, inside])

                self.assertEqual(sanitized, [inside.resolve()])
            finally:
                culvia_app.UPLOAD_CACHE_DIR = original_upload_dir

    def test_model_recompute_plan_only_marks_missing_outputs(self) -> None:
        record = {"file_id": "image-1"}
        for column in scoring.model_output_columns(scoring.MODEL_CORE_AESTHETIC):
            record[column] = 8.0
        for column in scoring.model_output_columns(scoring.MODEL_BASIC_TECHNICAL):
            record[column] = 7.0

        plan = scoring.model_recompute_plan(record, scoring.DEFAULT_SELECTED_MODELS)

        self.assertFalse(plan[scoring.MODEL_CORE_AESTHETIC])
        self.assertFalse(plan[scoring.MODEL_BASIC_TECHNICAL])
        self.assertTrue(plan[scoring.MODEL_CLIP_IQA])
        self.assertTrue(plan[scoring.MODEL_CLIP_AESTHETIC])

        for column in scoring.model_output_columns(scoring.MODEL_CLIP_IQA):
            record[column] = 6.0
        plan = scoring.model_recompute_plan(record, [scoring.MODEL_CLIP_AESTHETIC])

        self.assertFalse(plan[scoring.MODEL_CLIP_IQA])
        self.assertTrue(plan[scoring.MODEL_CLIP_AESTHETIC])

    def test_llm_review_model_is_optional_and_adds_columns(self) -> None:
        self.assertNotIn(scoring.MODEL_LLM_REVIEW, scoring.DEFAULT_SELECTED_MODELS)
        self.assertIn("llm_review_overall_0_10", scoring.CSV_COLUMNS)
        self.assertIn("llm_aesthetic_overall_0_10", scoring.CSV_COLUMNS)
        self.assertIn("llm_composition_0_10", scoring.CSV_COLUMNS)
        self.assertIn("llm_technical_overall_0_10", scoring.CSV_COLUMNS)
        self.assertIn("llm_sharpness_0_10", scoring.CSV_COLUMNS)

        plan = scoring.model_recompute_plan({}, [scoring.MODEL_LLM_REVIEW])

        self.assertTrue(plan[scoring.MODEL_LLM_REVIEW])
        self.assertFalse(plan[scoring.MODEL_CORE_AESTHETIC])

    def test_score_image_paths_persists_llm_insight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = make_image(Path(tmp) / "source.jpg")
            cache_path = Path(tmp) / "scores.sqlite"
            original = scoring.score_llm_review_image

            def fake_review(
                path: Path,
                file_id: str = "",
                score_context: dict[str, object] | None = None,
            ) -> scoring.AnalyzerOutput:
                return scoring.AnalyzerOutput(
                    scores={
                        "llm_review_overall": 6.9,
                        "llm_aesthetic_overall": 7.2,
                        "llm_quality": 6.7,
                        "llm_composition": 7.5,
                        "llm_lighting": 6.8,
                        "llm_color": 7.0,
                        "llm_depth_of_field": 6.9,
                        "llm_content": 7.1,
                        "llm_technical_overall": 6.4,
                        "llm_sharpness": 6.2,
                        "llm_exposure": 6.5,
                        "llm_contrast": 6.6,
                        "llm_cleanliness": 6.1,
                    },
                    insights=(
                        scoring.AnalysisInsight(
                            file_id=file_id,
                            analyzer_key=scoring.MODEL_LLM_REVIEW,
                            provider="unit-test",
                            model="mock-vlm",
                            title="层次不错",
                            summary="主体明确，后期可加强明暗层次。",
                            suggestions=("修图：压暗背景",),
                            raw_json={"retouching_suggestions": ["压暗背景"]},
                        ),
                    ),
                )

            scoring.score_llm_review_image = fake_review
            try:
                df, _device = scoring.score_image_paths(
                    [image_path],
                    cache_path=cache_path,
                    use_cache=False,
                    selected_models=[scoring.MODEL_LLM_REVIEW],
                )
            finally:
                scoring.score_llm_review_image = original

            self.assertAlmostEqual(float(df.loc[0, "llm_aesthetic_overall_0_10"]), 7.2)
            self.assertAlmostEqual(float(df.loc[0, "llm_review_overall_0_10"]), 6.9)
            self.assertAlmostEqual(float(df.loc[0, "llm_sharpness_0_10"]), 6.2)
            insights = scoring.load_analysis_insights(cache_path, file_ids=[df.loc[0, "file_id"]])
            self.assertEqual(len(insights), 1)
            self.assertEqual(insights[0].model, "mock-vlm")

    def test_llm_review_cache_depends_on_prompt_signature(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = make_image(Path(tmp) / "source.jpg")
            cache_path = Path(tmp) / "scores.sqlite"
            file_id = scoring.build_file_id(image_path)
            stale_record = {
                "file_id": file_id,
                "path": str(image_path),
                "folder": str(image_path.parent),
                "filename": image_path.name,
                "error": "",
            }
            for field in scoring.LLM_REVIEW_FIELDS:
                stale_record[f"{field}_0_10"] = 4.0
            scoring.save_cache_records(pd.DataFrame([stale_record]), cache_path)
            scoring.save_analysis_insights(
                [
                    scoring.AnalysisInsight(
                        file_id=file_id,
                        analyzer_key=scoring.MODEL_LLM_REVIEW,
                        provider=scoring.llm_review_provider(),
                        model=scoring.llm_review_model_name(),
                        model_version=scoring.llm_review_model_name(),
                        prompt_version="old-prompt",
                        score=4.0,
                    )
                ],
                cache_path,
            )

            original = scoring.score_llm_review_image
            calls = {"count": 0}

            def fake_review(
                path: Path,
                file_id: str = "",
                score_context: dict[str, object] | None = None,
            ) -> scoring.AnalyzerOutput:
                calls["count"] += 1
                return scoring.AnalyzerOutput(
                    scores={field: 8.0 for field in scoring.LLM_REVIEW_FIELDS},
                    insights=(
                        scoring.AnalysisInsight(
                            file_id=file_id,
                            analyzer_key=scoring.MODEL_LLM_REVIEW,
                            provider=scoring.llm_review_provider(),
                            model=scoring.llm_review_model_name(),
                            model_version=scoring.llm_review_model_name(),
                            prompt_version=scoring.llm_review_prompt_version(),
                            score=8.0,
                        ),
                    ),
                )

            scoring.score_llm_review_image = fake_review
            try:
                df, _device = scoring.score_image_paths(
                    [image_path],
                    cache_path=cache_path,
                    use_cache=True,
                    selected_models=[scoring.MODEL_LLM_REVIEW],
                )
                scoring.score_image_paths(
                    [image_path],
                    cache_path=cache_path,
                    use_cache=True,
                    selected_models=[scoring.MODEL_LLM_REVIEW],
                )
            finally:
                scoring.score_llm_review_image = original

            self.assertEqual(calls["count"], 1)
            self.assertAlmostEqual(float(df.loc[0, "llm_review_overall_0_10"]), 8.0)


class LlmReviewParsingTests(unittest.TestCase):
    def test_llm_prompt_respects_intentional_lighting_style(self) -> None:
        prompt = scoring.LLM_REVIEW_USER_PROMPT
        balanced_prompt = str(scoring.LLM_PROMPT_PRESETS["balanced"]["prompt"])
        technical_prompt = str(scoring.LLM_PROMPT_PRESETS["technical"]["prompt"])

        self.assertIn("光影是否均匀不是固定好坏标准", prompt)
        self.assertIn("艺术性", prompt)
        self.assertIn("情绪感染力", prompt)
        self.assertIn("75%", prompt)
        self.assertIn("技术项作为辅助判断", prompt)
        self.assertIn("艺术性", balanced_prompt)
        self.assertIn("技术项压过有意图的审美表达", balanced_prompt)
        self.assertIn("不要把强反差、局部光或不均匀光影本身视为缺陷", technical_prompt)

    def test_extract_json_mapping_accepts_fenced_json(self) -> None:
        parsed = scoring._extract_json_mapping('```json\n{"aesthetic_score": 7.5, "technical_score": 6.0}\n```')

        self.assertEqual(parsed["aesthetic_score"], 7.5)

    def test_llm_suggestions_keep_photography_and_retouching_context(self) -> None:
        suggestions = scoring._llm_suggestions(
            {
                "photography_suggestions": ["换侧光"],
                "retouching_suggestions": ["降低高光"],
            }
        )

        self.assertEqual(suggestions, ("拍摄：换侧光", "修图：降低高光"))

    def test_llm_review_scores_parse_nested_aesthetic_and_technical_dimensions(self) -> None:
        scores = scoring._llm_review_scores(
            {
                "scores": {
                    "overall": 7.4,
                    "aesthetic": {
                        "overall": 7.6,
                        "quality": 7.0,
                        "composition": 8.0,
                        "lighting": 7.2,
                        "color": 7.5,
                        "depth_of_field": 7.1,
                        "content": 7.8,
                    },
                    "technical": {
                        "overall": 6.8,
                        "sharpness": 6.6,
                        "exposure": 7.0,
                        "contrast": 6.7,
                        "cleanliness": 6.9,
                    },
                }
            }
        )

        self.assertAlmostEqual(scores["llm_review_overall"], 7.4)
        self.assertAlmostEqual(scores["llm_composition"], 8.0)
        self.assertAlmostEqual(scores["llm_sharpness"], 6.6)

    def test_llm_review_overall_fallback_prioritizes_aesthetic_expression(self) -> None:
        scores = scoring._llm_review_scores(
            {
                "scores": {
                    "aesthetic": {"overall": 8.0},
                    "technical": {"overall": 4.0},
                }
            }
        )

        self.assertAlmostEqual(scores["llm_review_overall"], 7.0)

    def test_deepseek_configuration_defaults_to_direct_image_payload(self) -> None:
        original_session = scoring.llm_config_layers()["session"]
        original_persisted = scoring.llm_config_layers()["sqlite"]
        try:
            scoring.clear_session_llm_config()
            scoring.set_persisted_llm_config({})
            with tempfile.TemporaryDirectory() as tmp:
                image_path = make_image(Path(tmp) / "photo.jpg", size=(640, 480))
                original_cache_dir = scoring.ANALYSIS_IMAGE_CACHE_DIR
                scoring.ANALYSIS_IMAGE_CACHE_DIR = Path(tmp) / "analysis"
                try:
                    scoring.set_session_llm_config(
                        {
                            "api_key": "test-key",
                            "base_url": "https://api.deepseek.com",
                            "model": "deepseek-v4-flash",
                        }
                    )

                    payload = scoring._llm_request_payload(
                        image_path,
                        score_context={"overall_0_10": 7.0, "technical_overall_0_10": 6.2},
                    )
                    user_content = payload["messages"][1]["content"]

                    self.assertEqual(scoring.llm_review_input_mode(), "image")
                    self.assertIsInstance(user_content, list)
                    self.assertTrue(
                        any(isinstance(item, dict) and item.get("type") == "image_url" for item in user_content)
                    )
                finally:
                    scoring.ANALYSIS_IMAGE_CACHE_DIR = original_cache_dir
        finally:
            scoring.clear_session_llm_config()
            scoring.set_session_llm_config(original_session)
            scoring.set_persisted_llm_config(original_persisted)

    def test_explicit_text_input_mode_uses_score_context_without_image_url(self) -> None:
        original_session = scoring.llm_config_layers()["session"]
        original_persisted = scoring.llm_config_layers()["sqlite"]
        try:
            scoring.clear_session_llm_config()
            scoring.set_persisted_llm_config({})
            scoring.set_session_llm_config(
                {
                    "api_key": "test-key",
                    "base_url": "https://api.deepseek.com",
                    "model": "deepseek-v4-flash",
                    "input_mode": "text",
                }
            )

            payload = scoring._llm_request_payload(
                Path("/tmp/photo.jpg"),
                score_context={"overall_0_10": 7.0, "technical_overall_0_10": 6.2},
            )
            user_content = payload["messages"][1]["content"]

            self.assertEqual(scoring.llm_review_input_mode(), "text")
            self.assertIsInstance(user_content, str)
            self.assertNotIn("image_url", user_content)
            self.assertIn("总分", user_content)
        finally:
            scoring.clear_session_llm_config()
            scoring.set_session_llm_config(original_session)
            scoring.set_persisted_llm_config(original_persisted)


class ImageCacheTests(unittest.TestCase):
    def test_analysis_image_cache_creates_bounded_cached_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_cache_dir = scoring.ANALYSIS_IMAGE_CACHE_DIR
            scoring.ANALYSIS_IMAGE_CACHE_DIR = Path(tmp) / "analysis"
            try:
                image_path = make_image(Path(tmp) / "source.jpg")
                cached = scoring.cached_resized_image_path(image_path, max_size=300)
                cached_again = scoring.cached_resized_image_path(image_path, max_size=300)

                self.assertEqual(cached, cached_again)
                self.assertTrue(cached.exists())
                with Image.open(cached) as image:
                    self.assertLessEqual(max(image.size), 300)
            finally:
                scoring.ANALYSIS_IMAGE_CACHE_DIR = original_cache_dir

    def test_thumbnail_cache_uses_shared_resize_helper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_cache_dir = culvia_app.THUMBNAIL_CACHE_DIR
            culvia_app.THUMBNAIL_CACHE_DIR = Path(tmp) / "thumbs"
            try:
                image_path = make_image(Path(tmp) / "source.jpg")
                cached = culvia_app.ensure_thumbnail_file(image_path, 120)
                cached_again = culvia_app.ensure_thumbnail_file(image_path, 120)

                self.assertEqual(cached, cached_again)
                self.assertTrue(cached.exists())
                with Image.open(cached) as image:
                    self.assertLessEqual(max(image.size), 120)
            finally:
                culvia_app.THUMBNAIL_CACHE_DIR = original_cache_dir


class TorchFeatureHelperTests(unittest.TestCase):
    def test_torch_feature_tensor_extracts_common_transformer_outputs(self) -> None:
        import torch

        tensor = torch.ones((2, 3))
        self.assertIs(scoring._torch_feature_tensor(tensor), tensor)
        self.assertIs(scoring._torch_feature_tensor(SimpleNamespace(image_embeds=tensor)), tensor)
        self.assertIs(scoring._torch_feature_tensor((torch.ones(1), tensor)), tensor)

        hidden = torch.ones((2, 4, 3))
        pooled = scoring._torch_feature_tensor(SimpleNamespace(last_hidden_state=hidden))
        self.assertEqual(tuple(pooled.shape), (2, 3))

        normalized = scoring._normalize_torch_features(SimpleNamespace(pooler_output=tensor))
        norms = torch.linalg.vector_norm(normalized, dim=-1)
        self.assertTrue(torch.allclose(norms, torch.ones_like(norms)))


if __name__ == "__main__":
    unittest.main()
