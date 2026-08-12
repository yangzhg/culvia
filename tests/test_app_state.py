from __future__ import annotations

import unittest
import threading

import pandas as pd
from unittest.mock import patch

import culvia.app_state as app_state

from culvia.app_state import AppStateStore, StaleMediaStateError, create_initial_state, empty_job


class AppStateStoreTests(unittest.TestCase):
    def test_empty_job_has_stable_idle_shape(self) -> None:
        job = empty_job(now=123.0)

        self.assertEqual(job["jobId"], "")
        self.assertFalse(job["running"])
        self.assertEqual(job["phase"], "idle")
        self.assertEqual(job["title"], "")
        self.assertEqual(job["titleText"], {"key": "jobText.idleReady"})
        self.assertEqual(job["detailText"], {"key": "jobText.idleChooseSource"})
        self.assertEqual(job["updatedAt"], 123.0)
        self.assertEqual(job["completedEvaluations"], [])

    def test_initial_state_copies_mutable_defaults(self) -> None:
        filters = {"customWeights": {"aesthetic": 0.6}, "limit": 80}
        state = create_initial_state(
            scores_df=[],
            default_photo_dirs=["/photos"],
            default_cache_path="/cache.sqlite",
            filter_defaults=filters,
            default_selected_models=["core"],
        )

        state["filters"]["customWeights"]["aesthetic"] = 0.1
        state["source"]["folders"].append("/other")
        state["models"]["selected"].append("llm")

        self.assertEqual(filters["customWeights"]["aesthetic"], 0.6)
        self.assertEqual(state["source"]["folders"], ["/photos", "/other"])
        self.assertEqual(state["models"]["selected"], ["core", "llm"])

    def test_state_store_snapshot_and_reset_are_isolated(self) -> None:
        store = AppStateStore({"source": {"folders": ["/a"]}, "filters": {"limit": 80}})
        snapshot = store.snapshot()
        snapshot["source"]["folders"].append("/b")

        self.assertEqual(store.data["source"]["folders"], ["/a"])

        next_state = {"source": {"folders": ["/next"]}, "filters": {"limit": 20}}
        store.reset(next_state)
        next_state["source"]["folders"].append("/mutated")

        self.assertEqual(store.data["source"]["folders"], ["/next"])
        self.assertEqual(store.data["filters"]["limit"], 20)

    def test_reset_can_preserve_a_matching_maintenance_job(self) -> None:
        state = create_initial_state(
            scores_df=[],
            default_photo_dirs=[],
            default_cache_path="/old.sqlite",
            filter_defaults={},
            default_selected_models=[],
        )
        state["job"].update({"jobId": "maintenance", "kind": "maintenance", "running": True})
        store = AppStateStore(state)
        next_state = create_initial_state(
            scores_df=[],
            default_photo_dirs=[],
            default_cache_path="/new.sqlite",
            filter_defaults={},
            default_selected_models=[],
        )

        store.reset(next_state, expected_job_id="maintenance", preserve_job=True)

        self.assertEqual(store.data["source"]["cachePath"], "/new.sqlite")
        self.assertEqual(store.data["job"]["jobId"], "maintenance")
        self.assertTrue(store.data["job"]["running"])

    def test_media_state_publication_replaces_catalog_atomically(self) -> None:
        store = AppStateStore(
            create_initial_state(
                scores_df=pd.DataFrame([{"file_id": "old", "path": "/photos/old.jpg", "score": 1}]),
                default_photo_dirs=["/photos"],
                default_cache_path="/cache.sqlite",
                filter_defaults={},
                default_selected_models=[],
            )
        )
        before = store.media_catalog_snapshot()

        store.publish_media_state(
            scores_df=pd.DataFrame([{"file_id": "new", "path": "/other/new.jpg", "score": 2}]),
            source_patch={"folders": ["/other"]},
        )
        after = store.media_catalog_snapshot()

        self.assertEqual(after.revision, before.revision + 1)
        self.assertNotIn("old", after.by_file_id)
        self.assertEqual(after.by_file_id["new"], "/other/new.jpg")

    def test_score_only_publication_preserves_catalog_and_rejects_stale_revision(self) -> None:
        original = pd.DataFrame([{"file_id": "photo", "path": "/photos/photo.jpg", "score": 1}])
        store = AppStateStore(
            create_initial_state(
                scores_df=original,
                default_photo_dirs=["/photos"],
                default_cache_path="/cache.sqlite",
                filter_defaults={},
                default_selected_models=[],
            )
        )
        catalog = store.media_catalog_snapshot()

        store.publish_score_values(
            pd.DataFrame([{"file_id": "photo", "path": "/photos/photo.jpg", "score": 9}]),
            expected_media_revision=catalog.revision,
        )

        self.assertIs(store.media_catalog_snapshot(), catalog)
        store.publish_media_state(source_patch={"folders": ["/other"]})
        with self.assertRaisesRegex(StaleMediaStateError, "catalog changed"):
            store.publish_score_values(
                pd.DataFrame([{"file_id": "photo", "path": "/photos/photo.jpg", "score": 8}]),
                expected_media_revision=catalog.revision,
            )

    def test_media_catalog_build_does_not_hold_the_state_lock(self) -> None:
        store = AppStateStore(
            create_initial_state(
                scores_df=pd.DataFrame([{"file_id": "old", "path": "/old.jpg"}]),
                default_photo_dirs=["/old"],
                default_cache_path="/cache.sqlite",
                filter_defaults={},
                default_selected_models=[],
            )
        )
        started = threading.Event()
        release = threading.Event()
        real_build = app_state.build_media_catalog

        def blocked_build(*args, **kwargs):
            started.set()
            self.assertTrue(release.wait(timeout=1))
            return real_build(*args, **kwargs)

        with patch.object(app_state, "build_media_catalog", side_effect=blocked_build):
            thread = threading.Thread(
                target=store.publish_media_state,
                kwargs={
                    "scores_df": pd.DataFrame([{"file_id": "new", "path": "/new.jpg"}]),
                    "source_patch": {"folders": ["/new"]},
                },
            )
            thread.start()
            self.assertTrue(started.wait(timeout=1))
            self.assertEqual(store.snapshot()["source"]["folders"], ["/old"])
            self.assertEqual(store.media_catalog_snapshot().by_file_id["old"], "/old.jpg")
            release.set()
            thread.join(timeout=1)

        self.assertFalse(thread.is_alive())
        self.assertEqual(store.media_catalog_snapshot().by_file_id["new"], "/new.jpg")

    def test_reset_rejects_a_late_background_media_result(self) -> None:
        store = AppStateStore(
            create_initial_state(
                scores_df=pd.DataFrame([{"file_id": "old", "path": "/old.jpg"}]),
                default_photo_dirs=["/old"],
                default_cache_path="/old.sqlite",
                filter_defaults={},
                default_selected_models=[],
            )
        )
        expected_revision = store.current_media_revision()
        replacement = create_initial_state(
            scores_df=pd.DataFrame(columns=["file_id", "path"]),
            default_photo_dirs=[],
            default_cache_path="/new.sqlite",
            filter_defaults={},
            default_selected_models=[],
        )
        store.reset(replacement)

        with self.assertRaisesRegex(StaleMediaStateError, "catalog changed"):
            store.publish_media_state(
                scores_df=pd.DataFrame([{"file_id": "late", "path": "/late.jpg"}]),
                expected_media_revision=expected_revision,
            )

        self.assertNotIn("late", store.media_catalog_snapshot().by_file_id)

    def test_reset_during_catalog_build_rejects_the_obsolete_commit(self) -> None:
        store = AppStateStore(
            create_initial_state(
                scores_df=pd.DataFrame([{"file_id": "old", "path": "/old.jpg"}]),
                default_photo_dirs=["/old"],
                default_cache_path="/old.sqlite",
                filter_defaults={},
                default_selected_models=[],
            )
        )
        expected_revision = store.current_media_revision()
        started = threading.Event()
        release = threading.Event()
        errors: list[BaseException] = []
        real_build = app_state.build_media_catalog
        build_calls = 0

        def blocked_build(*args, **kwargs):
            nonlocal build_calls
            build_calls += 1
            if build_calls == 1:
                started.set()
                self.assertTrue(release.wait(timeout=1))
            return real_build(*args, **kwargs)

        def publish_late_result() -> None:
            try:
                store.publish_media_state(
                    scores_df=pd.DataFrame([{"file_id": "late", "path": "/late.jpg"}]),
                    expected_media_revision=expected_revision,
                )
            except BaseException as exc:
                errors.append(exc)

        with patch.object(app_state, "build_media_catalog", side_effect=blocked_build):
            thread = threading.Thread(target=publish_late_result)
            thread.start()
            self.assertTrue(started.wait(timeout=1))
            store.reset(
                create_initial_state(
                    scores_df=pd.DataFrame([{"file_id": "replacement", "path": "/replacement.jpg"}]),
                    default_photo_dirs=["/replacement"],
                    default_cache_path="/replacement.sqlite",
                    filter_defaults={},
                    default_selected_models=[],
                )
            )
            release.set()
            thread.join(timeout=1)

        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], StaleMediaStateError)
        self.assertIn("replacement", store.media_catalog_snapshot().by_file_id)
        self.assertNotIn("late", store.media_catalog_snapshot().by_file_id)

    def test_replaced_job_rejects_a_late_result_at_the_same_revision(self) -> None:
        state = create_initial_state(
            scores_df=pd.DataFrame(columns=["file_id", "path"]),
            default_photo_dirs=[],
            default_cache_path="/cache.sqlite",
            filter_defaults={},
            default_selected_models=[],
        )
        state["job"]["jobId"] = "new-job"
        store = AppStateStore(state)

        with self.assertRaisesRegex(StaleMediaStateError, "job changed"):
            store.publish_media_state(
                scores_df=pd.DataFrame([{"file_id": "late", "path": "/late.jpg"}]),
                expected_media_revision=store.current_media_revision(),
                expected_job_id="old-job",
            )

        self.assertNotIn("late", store.media_catalog_snapshot().by_file_id)

    def test_score_update_during_catalog_build_is_not_overwritten(self) -> None:
        original = pd.DataFrame([{"file_id": "photo", "path": "/photo.jpg", "score": 1}])
        store = AppStateStore(
            create_initial_state(
                scores_df=original,
                default_photo_dirs=["/"],
                default_cache_path="/cache.sqlite",
                filter_defaults={},
                default_selected_models=[],
            )
        )
        revision = store.current_media_revision()
        started = threading.Event()
        release = threading.Event()
        real_build = app_state.build_media_catalog
        build_calls = 0

        def blocked_first_build(*args, **kwargs):
            nonlocal build_calls
            build_calls += 1
            if build_calls == 1:
                started.set()
                self.assertTrue(release.wait(timeout=1))
            return real_build(*args, **kwargs)

        with patch.object(app_state, "build_media_catalog", side_effect=blocked_first_build):
            thread = threading.Thread(
                target=store.publish_media_state,
                kwargs={"source_patch": {"cachePath": "/next.sqlite"}},
            )
            thread.start()
            self.assertTrue(started.wait(timeout=1))
            updated = original.copy()
            updated.loc[0, "score"] = 9
            store.publish_score_values(updated, expected_media_revision=revision)
            release.set()
            thread.join(timeout=1)

        self.assertFalse(thread.is_alive())
        self.assertEqual(int(store.data["scores_df"].iloc[0]["score"]), 9)
        self.assertGreaterEqual(build_calls, 2)


if __name__ == "__main__":
    unittest.main()
