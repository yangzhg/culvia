from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from culvia import scoring
from culvia.app_state import AppStateStore, create_initial_state
from culvia.insight_store import AnalysisInsight, AnalysisInsightMatch
from culvia.job_service import ScoringJobService
from culvia.llm_review_runner import LlmReviewRunnerDependencies, run_llm_review_job
from culvia.llm_runtime import AnalyzerOutput
from culvia.schema import (
    CORE_AESTHETIC_GROUP,
    LLM_REVIEW_FIELDS,
    LLM_REVIEW_GENERATION_COLUMN,
    MODEL_CORE_AESTHETIC,
    MODEL_LLM_REVIEW,
    MODEL_RESULT_VERSION_COLUMNS,
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

    @contextmanager
    def open_checkpoint_writer(cache_path: str | Path):
        class Writer:
            def upsert(self, df: pd.DataFrame) -> None:
                calls.setdefault("cache_saves", []).append((df.copy(), str(cache_path)))

        yield Writer()

    def save_analysis_insights(insights: Sequence[AnalysisInsight], cache_path: str | Path) -> None:
        calls.setdefault("insight_saves", []).append((tuple(insights), str(cache_path)))

    return LlmReviewRunnerDependencies(
        default_cache_path="/tmp/default.sqlite",
        refresh_persisted_llm_config=lambda cache_path: calls.setdefault("refreshed", []).append(cache_path),
        llm_review_configured=lambda: configured,
        llm_review_status=lambda: {"provider": "unit", "model": "mock-vlm", "promptVersion": "prompt-v1"},
        llm_review_result_prompt_version=lambda _context: "prompt-v1",
        sanitize_uploaded_paths=lambda value: [Path(item) for item in value or []],
        scan_image_paths=lambda folders: ([], []),
        build_file_id=lambda path: f"id:{Path(path).name}",
        normalize_score_dataframe=normalize_score_dataframe,
        score_llm_review_image=score_llm_review_image,
        apply_llm_review_scores=apply_llm_review_scores,
        load_cache_records=lambda cache_path: pd.DataFrame(),
        open_checkpoint_writer=open_checkpoint_writer,
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
                    "prompt_versions_by_file_id": None,
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

        def save_analysis_insights_before_state_update(
            insights: Sequence[AnalysisInsight], cache_path: str | Path
        ) -> None:
            with store.lock:
                current = store.data["scores_df"]
                pending = current[current["file_id"] == "pending"].iloc[0]
                self.assertTrue(pd.isna(pending[score_column("llm_review_overall", "0_10")]))
            calls.setdefault("insight_saves", []).append((tuple(insights), str(cache_path)))

        run_llm_review_job(
            str(job_id),
            {"mode": "folders", "folders": ["/photos"], "cachePath": cache_path},
            store,
            service,
            replace(base_dependencies, save_analysis_insights=save_analysis_insights_before_state_update),
        )

        self.assertEqual([call[1] for call in calls["reviewed"]], ["pending"])
        self.assertEqual(len(calls["cache_saves"]), 1)
        self.assertEqual(calls["cache_saves"][0][0]["file_id"].tolist(), ["pending"])
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
            self.assertEqual(float(failed_row[LLM_REVIEW_GENERATION_COLUMN]), 1.0)
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

    def test_text_review_masks_stale_local_context_without_clearing_cached_values(self) -> None:
        cache_path = "/tmp/llm-review-stale-local.sqlite"
        stale_version = "score-v1:old"
        row = make_row("stale-local", "/photos/stale-local.jpg")
        row.update({column: 9.0 for column in CORE_AESTHETIC_GROUP.cache_columns})
        row[MODEL_RESULT_VERSION_COLUMNS[MODEL_CORE_AESTHETIC]] = stale_version
        row[LLM_REVIEW_GENERATION_COLUMN] = 1.0
        row.update({score_column(field, "0_10"): 8.0 for field in LLM_REVIEW_FIELDS})
        store = make_store(cache_path, normalize_score_dataframe(pd.DataFrame([row])))
        service = ScoringJobService(store)
        job_id = service.reserve(kind="llm_review")
        self.assertTrue(job_id)
        calls: dict[str, Any] = {}

        def load_matching(_cache_path: str, **identity: object) -> dict[str, AnalysisInsightMatch]:
            calls["matching_identity"] = identity
            return {}

        dependencies = replace(
            make_dependencies(calls),
            llm_review_status=lambda: {
                "provider": "unit",
                "model": "mock-vlm",
                "promptVersion": "prompt-v1",
                "inputMode": "text",
            },
            llm_review_result_prompt_version=lambda _context, **_identity: "prompt-v1:context:current",
            load_latest_matching_analysis_insight_results=load_matching,
        )

        run_llm_review_job(
            str(job_id),
            {"mode": "folders", "folders": ["/photos"], "cachePath": cache_path},
            store,
            service,
            dependencies,
        )

        context = calls["reviewed"][0][2]
        self.assertTrue(pd.isna(context["overall_0_10"]))
        self.assertEqual(
            calls["matching_identity"]["prompt_versions_by_file_id"],
            {"stale-local": "prompt-v1:context:current"},
        )
        saved = calls["cache_saves"][0][0].set_index("file_id").loc["stale-local"]
        self.assertEqual(float(saved["overall_0_10"]), 9.0)
        self.assertEqual(saved[MODEL_RESULT_VERSION_COLUMNS[MODEL_CORE_AESTHETIC]], stale_version)

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


class LlmReviewCheckpointTests(unittest.TestCase):
    @staticmethod
    def local_record(file_id: str, path: str, value: float) -> dict[str, object]:
        return {
            **make_row(file_id, path),
            **{column: value for column in CORE_AESTHETIC_GROUP.cache_columns},
            MODEL_RESULT_VERSION_COLUMNS[MODEL_CORE_AESTHETIC]: scoring.MODEL_CAPABILITIES[
                MODEL_CORE_AESTHETIC
            ].result_version,
        }

    @staticmethod
    def dependencies(calls: dict[str, Any]) -> LlmReviewRunnerDependencies:
        return replace(
            make_dependencies(calls),
            load_cache_records=scoring.load_cache_records,
            open_checkpoint_writer=scoring.open_score_checkpoint_writer,
            load_latest_matching_analysis_insight_results=scoring.load_latest_matching_analysis_insight_results,
            save_analysis_insights=scoring.save_analysis_insights,
        )

    def test_latest_checkpoint_supplies_context_for_existing_and_new_sources(self) -> None:
        for new_source in (False, True):
            with self.subTest(new_source=new_source), tempfile.TemporaryDirectory() as tmp:
                cache_path = str(Path(tmp) / "scores.sqlite")
                source_path = Path("/var/photos/review.jpg")
                cached = self.local_record("review", "/private/var/photos/review.jpg", 9.0)
                outside = self.local_record("outside", "/photos/outside.jpg", 6.0)
                scoring.save_cache_records(pd.DataFrame([cached, outside]), cache_path)
                preview = pd.DataFrame() if new_source else pd.DataFrame([make_row("review", str(source_path))])
                store = make_store(cache_path, normalize_score_dataframe(preview))
                service = ScoringJobService(store)
                calls: dict[str, Any] = {}
                base = self.dependencies(calls)

                def review(path: str | Path, file_id: str, context: Mapping[str, object] | None) -> AnalyzerOutput:
                    output = base.score_llm_review_image(path, file_id, context)
                    prompt = scoring.llm_review_result_prompt_version(
                        context, prompt_version="prompt-v1", input_mode="text"
                    )
                    return replace(output, insights=(replace(output.insights[0], prompt_version=prompt),))

                dependencies = replace(
                    base,
                    scan_image_paths=lambda _folders: ([source_path], []),
                    build_file_id=lambda _path: "review",
                    llm_review_status=lambda: {
                        "provider": "unit",
                        "model": "mock-vlm",
                        "promptVersion": "prompt-v1",
                        "inputMode": "text",
                    },
                    llm_review_result_prompt_version=scoring.llm_review_result_prompt_version,
                    score_llm_review_image=review,
                )
                run_llm_review_job(
                    str(service.reserve(kind="llm_review")),
                    {"mode": "folders", "folders": ["/var/photos"], "cachePath": cache_path},
                    store,
                    service,
                    dependencies,
                )

                self.assertEqual(store.data["job"]["phase"], "done")
                self.assertFalse(pd.isna(calls["reviewed"][0][2]["overall_0_10"]))
                self.assertEqual(float(calls["reviewed"][0][2]["overall_0_10"]), 9.0)
                persisted = scoring.load_cache_records(cache_path).set_index("file_id")
                self.assertEqual(float(persisted.loc["review", "overall_0_10"]), 9.0)
                self.assertEqual(persisted.loc["review", "path"], str(source_path))
                self.assertEqual(store.data["scores_df"]["file_id"].tolist(), ["review"])
                self.assertEqual(store.data["scores_df"]["path"].tolist(), [str(source_path)])
                self.assertEqual(float(persisted.loc["outside", "overall_0_10"]), 6.0)
                insight = scoring.load_analysis_insights(cache_path, file_ids=["review"])[0]
                self.assertEqual(
                    insight.prompt_version,
                    scoring.llm_review_result_prompt_version(
                        scoring.normalize_score_dataframe(pd.DataFrame([cached])).iloc[0].to_dict(),
                        prompt_version="prompt-v1",
                        input_mode="text",
                    ),
                )

    def test_cancelled_review_does_not_rewrite_unprocessed_or_outside_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = str(Path(tmp) / "scores.sqlite")
            rows = [self.local_record(name, f"/photos/{name}.jpg", 5.0) for name in ("first", "second", "outside")]
            scoring.save_cache_records(pd.DataFrame(rows), cache_path)
            store = make_store(cache_path, normalize_score_dataframe(pd.DataFrame(rows[:2])))
            service = ScoringJobService(store)
            calls: dict[str, Any] = {}
            base = self.dependencies(calls)

            def review(path: str | Path, file_id: str, context: Mapping[str, object] | None) -> AnalyzerOutput:
                scoring.SCORE_CACHE_STORE.upsert(
                    pd.DataFrame(
                        [
                            self.local_record("second", "/photos/second.jpg", 9.0),
                            self.local_record("outside", "/photos/outside.jpg", 8.0),
                        ]
                    ),
                    cache_path,
                )
                service.request_cancel()
                return base.score_llm_review_image(path, file_id, context)

            run_llm_review_job(
                str(service.reserve(kind="llm_review")),
                {"mode": "folders", "folders": ["/photos"], "cachePath": cache_path},
                store,
                service,
                replace(base, score_llm_review_image=review),
            )

            self.assertEqual(store.data["job"]["phase"], "cancelled")
            self.assertEqual([call[1] for call in calls["reviewed"]], ["first"])
            persisted = scoring.load_cache_records(cache_path).set_index("file_id")
            self.assertEqual(float(persisted.loc["first", LLM_REVIEW_GENERATION_COLUMN]), 2.0)
            self.assertEqual(float(persisted.loc["second", "overall_0_10"]), 9.0)
            self.assertEqual(float(persisted.loc["outside", "overall_0_10"]), 8.0)

    def test_cached_nulls_and_stale_local_values_replace_older_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = str(Path(tmp) / "scores.sqlite")
            cleared = make_row("cleared", "/photos/cleared.jpg")
            stale = self.local_record("stale", "/photos/stale.jpg", 8.0)
            version_column = MODEL_RESULT_VERSION_COLUMNS[MODEL_CORE_AESTHETIC]
            stale[version_column] = "score-v1:old"
            scoring.save_cache_records(pd.DataFrame([cleared, stale]), cache_path)
            preview = [self.local_record(name, f"/photos/{name}.jpg", 9.0) for name in ("cleared", "stale")]
            store = make_store(cache_path, normalize_score_dataframe(pd.DataFrame(preview)))
            service = ScoringJobService(store)
            calls: dict[str, Any] = {}
            run_llm_review_job(
                str(service.reserve(kind="llm_review")),
                {"mode": "folders", "folders": ["/photos"], "cachePath": cache_path},
                store,
                service,
                self.dependencies(calls),
            )

            self.assertEqual(store.data["job"]["phase"], "done")
            self.assertTrue(all(pd.isna(call[2]["overall_0_10"]) for call in calls["reviewed"]))
            for frame in (scoring.load_cache_records(cache_path), store.data["scores_df"]):
                rows = frame.set_index("file_id")
                self.assertTrue(pd.isna(rows.loc["cleared", "overall_0_10"]))
                self.assertEqual(rows.loc["cleared", version_column], "")
                self.assertEqual(float(rows.loc["stale", "overall_0_10"]), 8.0)
                self.assertEqual(rows.loc["stale", version_column], "score-v1:old")

    def test_current_cached_review_is_reused_when_memory_is_unscored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = str(Path(tmp) / "scores.sqlite")
            path = "/photos/current.jpg"
            record = self.local_record("current", path, 9.0)
            output = make_dependencies({}).score_llm_review_image(path, "current", record)
            record = apply_llm_review_scores(record, output.scores, generation=2.0)
            scoring.save_cache_records(pd.DataFrame([record]), cache_path)
            scoring.save_analysis_insights(output.insights, cache_path)
            store = make_store(cache_path, normalize_score_dataframe(pd.DataFrame([make_row("current", path)])))
            service = ScoringJobService(store)
            calls: dict[str, Any] = {}
            run_llm_review_job(
                str(service.reserve(kind="llm_review")),
                {"mode": "folders", "folders": ["/photos"], "cachePath": cache_path},
                store,
                service,
                self.dependencies(calls),
            )

            self.assertNotIn("reviewed", calls)
            self.assertEqual(store.data["job"]["phase"], "done")
            self.assertEqual(store.data["job"]["total"], 0)
            row = store.data["scores_df"].iloc[0]
            self.assertEqual(float(row["overall_0_10"]), 9.0)
            self.assertEqual(float(row[LLM_REVIEW_GENERATION_COLUMN]), 2.0)

    def test_failed_checkpoint_does_not_publish_scores_or_insights(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = str(Path(tmp) / "scores.sqlite")
            record = self.local_record("current", "/photos/current.jpg", 9.0)
            scoring.save_cache_records(pd.DataFrame([record]), cache_path)
            with sqlite3.connect(cache_path) as conn:
                conn.execute(
                    "CREATE TRIGGER reject_score BEFORE INSERT ON culvia_scores "
                    "BEGIN SELECT RAISE(ABORT, 'score write failure'); END"
                )
            store = make_store(cache_path, normalize_score_dataframe(pd.DataFrame([record])))
            service = ScoringJobService(store)
            run_llm_review_job(
                str(service.reserve(kind="llm_review")),
                {"mode": "folders", "folders": ["/photos"], "cachePath": cache_path},
                store,
                service,
                self.dependencies({}),
            )

            self.assertEqual(store.data["job"]["phase"], "error")
            self.assertEqual(scoring.load_analysis_insights(cache_path, file_ids=["current"]), [])
            for frame in (scoring.load_cache_records(cache_path), store.data["scores_df"]):
                self.assertTrue(pd.isna(frame.iloc[0][LLM_REVIEW_GENERATION_COLUMN]))
                self.assertEqual(float(frame.iloc[0]["overall_0_10"]), 9.0)

    def test_failed_insight_write_never_publishes_the_new_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = str(Path(tmp) / "scores.sqlite")
            record = make_row("current", "/photos/current.jpg", scored=True)
            record[score_column("llm_cleanliness")] = pd.NA
            scoring.save_cache_records(pd.DataFrame([record]), cache_path)
            scoring.save_analysis_insights(
                [
                    AnalysisInsight(
                        file_id="current",
                        analyzer_key=MODEL_LLM_REVIEW,
                        provider="unit",
                        model="mock-vlm",
                        model_version="mock-vlm",
                        prompt_version="prompt-v1",
                        score=8.0,
                        created_at=1.0,
                    )
                ],
                cache_path,
            )
            with sqlite3.connect(cache_path) as conn:
                conn.execute(
                    "CREATE TRIGGER reject_insight BEFORE INSERT ON photo_analysis_insights "
                    "BEGIN SELECT RAISE(ABORT, 'insight write failure'); END"
                )
            store = make_store(cache_path, normalize_score_dataframe(pd.DataFrame([record])))
            service = ScoringJobService(store)
            run_llm_review_job(
                str(service.reserve(kind="llm_review")),
                {"mode": "folders", "folders": ["/photos"], "cachePath": cache_path},
                store,
                service,
                self.dependencies({}),
            )

            self.assertEqual(store.data["job"]["phase"], "error")
            self.assertEqual(float(store.data["scores_df"].iloc[0][LLM_REVIEW_GENERATION_COLUMN]), 1.0)
            self.assertEqual(scoring.load_analysis_insights(cache_path, file_ids=["current"])[0].created_at, 1.0)
            self.assertEqual(float(scoring.load_cache_records(cache_path).iloc[0][LLM_REVIEW_GENERATION_COLUMN]), 2.0)

            with sqlite3.connect(cache_path) as conn:
                conn.execute("DROP TRIGGER reject_insight")
            run_llm_review_job(
                str(service.reserve(kind="llm_review")),
                {"mode": "folders", "folders": ["/photos"], "cachePath": cache_path},
                store,
                service,
                self.dependencies({}),
            )
            self.assertEqual(store.data["job"]["phase"], "done")
            self.assertEqual(float(store.data["scores_df"].iloc[0][LLM_REVIEW_GENERATION_COLUMN]), 2.0)
            self.assertEqual(scoring.load_analysis_insights(cache_path, file_ids=["current"])[0].created_at, 2.0)


if __name__ == "__main__":
    unittest.main()
