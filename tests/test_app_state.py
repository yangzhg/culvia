from __future__ import annotations

import unittest

from culvia.app_state import AppStateStore, create_initial_state, empty_job


class AppStateStoreTests(unittest.TestCase):
    def test_empty_job_has_stable_idle_shape(self) -> None:
        job = empty_job(now=123.0)

        self.assertEqual(job["jobId"], "")
        self.assertFalse(job["running"])
        self.assertEqual(job["phase"], "idle")
        self.assertEqual(job["title"], "准备就绪")
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


if __name__ == "__main__":
    unittest.main()
