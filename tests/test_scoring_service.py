from __future__ import annotations

import unittest
from typing import Any

import pandas as pd

from culvia.app_state import AppStateStore, create_initial_state
from culvia.job_service import ScoringJobService
from culvia.scoring_service import ScoringStartError, start_llm_review_job_action, start_scoring_job_action


def make_store() -> AppStateStore:
    return AppStateStore(
        create_initial_state(
            scores_df=pd.DataFrame(columns=["file_id", "path", "error"]),
            default_photo_dirs=[],
            default_cache_path="/tmp/scores.sqlite",
            filter_defaults={},
            default_selected_models=["core"],
        )
    )


class FakeThread:
    created: list["FakeThread"] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs
        self.started = False
        FakeThread.created.append(self)

    def start(self) -> None:
        self.started = True


class ScoringServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeThread.created = []

    def test_start_scoring_job_action_reserves_slot_and_starts_thread(self) -> None:
        store = make_store()
        service = ScoringJobService(store)
        payload = {"mode": "folders", "folders": ["/photos"]}
        calls: list[tuple[str, dict[str, Any], AppStateStore, ScoringJobService]] = []

        def run_scoring_job(
            job_id: str,
            job_payload: dict[str, Any],
            state_store: AppStateStore,
            job_service: ScoringJobService,
        ) -> None:
            calls.append((job_id, job_payload, state_store, job_service))

        result = start_scoring_job_action(
            payload,
            store,
            service,
            run_scoring_job=run_scoring_job,
            thread_factory=FakeThread,
        )

        self.assertEqual(result.to_payload(), {"started": True, "jobId": result.job_id})
        self.assertTrue(result.job_id)
        self.assertEqual(len(FakeThread.created), 1)
        self.assertTrue(FakeThread.created[0].started)
        self.assertIs(FakeThread.created[0].kwargs["target"], run_scoring_job)
        self.assertEqual(FakeThread.created[0].kwargs["args"], (result.job_id, payload, store, service))
        self.assertTrue(FakeThread.created[0].kwargs["daemon"])
        self.assertEqual(calls, [])
        with store.lock:
            self.assertTrue(store.data["job"]["running"])
            self.assertEqual(store.data["job"]["kind"], "scoring")
            self.assertEqual(store.data["job"]["phase"], "queued")
            self.assertEqual(store.data["job"]["jobId"], result.job_id)

    def test_start_scoring_job_action_rejects_second_job_without_starting_thread(self) -> None:
        store = make_store()
        service = ScoringJobService(store)
        payload = {"mode": "folders", "folders": ["/photos"]}

        first = start_scoring_job_action(
            payload,
            store,
            service,
            run_scoring_job=lambda *_args: None,
            thread_factory=FakeThread,
        )
        self.assertTrue(first.job_id)

        with self.assertRaises(ScoringStartError) as error:
            start_scoring_job_action(
                payload,
                store,
                service,
                run_scoring_job=lambda *_args: None,
                thread_factory=FakeThread,
            )

        self.assertEqual(error.exception.error_code, "scoringAlreadyRunning")
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(len(FakeThread.created), 1)

    def test_start_llm_review_job_action_reserves_labeled_job(self) -> None:
        store = make_store()
        service = ScoringJobService(store)
        payload = {"mode": "folders", "folders": ["/photos"]}

        result = start_llm_review_job_action(
            payload,
            store,
            service,
            run_llm_review_job=lambda *_args: None,
            thread_factory=FakeThread,
        )

        self.assertTrue(result.job_id)
        self.assertEqual(len(FakeThread.created), 1)
        self.assertTrue(FakeThread.created[0].started)
        with store.lock:
            self.assertTrue(store.data["job"]["running"])
            self.assertEqual(store.data["job"]["kind"], "llm_review")
            self.assertEqual(store.data["job"]["phase"], "queued")
            self.assertEqual(store.data["job"]["title"], "准备开始大模型评审")


if __name__ == "__main__":
    unittest.main()
