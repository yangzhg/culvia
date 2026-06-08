from __future__ import annotations

import unittest

from culvia.app_state import AppStateStore, create_initial_state, empty_job
from culvia.job_service import ScoringJobService


def make_service() -> ScoringJobService:
    store = AppStateStore(
        create_initial_state(
            scores_df=[],
            default_photo_dirs=[],
            default_cache_path="/tmp/scores.sqlite",
            filter_defaults={},
            default_selected_models=[],
        )
    )
    return ScoringJobService(store)


class ScoringJobServiceTests(unittest.TestCase):
    def test_reserve_claims_a_single_job_slot(self) -> None:
        service = make_service()

        job_id = service.reserve()
        duplicate = service.reserve()

        self.assertTrue(job_id)
        self.assertIsNone(duplicate)
        with service.state_store.lock:
            job = service.state_store.data["job"]
            self.assertTrue(job["running"])
            self.assertEqual(job["phase"], "queued")
            self.assertEqual(job["jobId"], job_id)
        self.assertEqual(service.control["jobId"], job_id)
        self.assertFalse(service.control["pauseRequested"])

    def test_thread_bound_updates_cannot_overwrite_a_new_job(self) -> None:
        service = make_service()
        with service.state_store.lock:
            service.state_store.data["job"] = empty_job()
            service.state_store.data["job"].update({"jobId": "current-job", "running": True, "title": "当前任务"})

        try:
            service.bind_thread_job("stale-job")
            service.update(title="过期任务")
            with service.state_store.lock:
                self.assertEqual(service.state_store.data["job"]["title"], "当前任务")

            service.bind_thread_job("current-job")
            service.update(title="当前线程")
            with service.state_store.lock:
                self.assertEqual(service.state_store.data["job"]["title"], "当前线程")
        finally:
            service.clear_thread_job()

    def test_pause_and_resume_are_bound_to_the_active_job(self) -> None:
        service = make_service()
        self.assertFalse(service.request_pause())

        job_id = service.reserve()
        self.assertTrue(job_id)

        self.assertTrue(service.request_pause())
        self.assertTrue(service.control["pauseRequested"])
        with service.state_store.lock:
            job = service.state_store.data["job"]
            self.assertTrue(job["paused"])
            self.assertEqual(job["phase"], "pausing")

        self.assertTrue(service.request_resume())
        self.assertFalse(service.control["pauseRequested"])
        with service.state_store.lock:
            job = service.state_store.data["job"]
            self.assertFalse(job["paused"])
            self.assertEqual(job["phase"], "scoring")

    def test_reset_control_ignores_stale_job_ids(self) -> None:
        service = make_service()
        job_id = service.reserve()
        self.assertTrue(job_id)

        service.reset_control("other-job")
        self.assertEqual(service.control["jobId"], job_id)

        service.reset_control(job_id)
        self.assertEqual(service.control["jobId"], "")
        self.assertFalse(service.control["pauseRequested"])


if __name__ == "__main__":
    unittest.main()
