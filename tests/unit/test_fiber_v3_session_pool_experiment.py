import threading
import time
import unittest

from core.vcp.v3.session_pool_experiment import (
    V3SessionPoolExperiment, run_v3_sessions_serial)


class FakeSession:
    def __init__(self, steps, delay=0.0):
        self.remaining = int(steps); self.delay = float(delay); self.done = not self.remaining
        self.visits = []

    def step(self):
        self.visits.append(threading.get_ident())
        if self.delay: time.sleep(self.delay)
        self.remaining -= 1; self.done = self.remaining <= 0


class FiberV3SessionPoolExperimentTests(unittest.TestCase):
    def test_pool_completes_every_session_once_per_step(self):
        sessions = (FakeSession(7), FakeSession(5), FakeSession(3))
        report = V3SessionPoolExperiment(2, quantum=2).run(sessions)
        self.assertEqual((report.steps, [len(row.visits) for row in sessions]), (15, [7, 5, 3]))
        self.assertTrue(all(row.done for row in sessions))

    def test_pool_uses_multiple_workers_for_releasable_work(self):
        sessions = tuple(FakeSession(2, .01) for _index in range(4))
        report = V3SessionPoolExperiment(2, quantum=1).run(sessions)
        self.assertEqual(len(report.thread_ids), 2)

    def test_serial_and_pool_reach_same_state(self):
        serial = tuple(FakeSession(value) for value in (4, 6))
        pooled = tuple(FakeSession(value) for value in (4, 6))
        first = run_v3_sessions_serial(serial, 3)
        second = V3SessionPoolExperiment(2, 3).run(pooled)
        self.assertEqual((first.steps, second.steps), (10, 10))

    def test_empty_pool_finishes_without_tasks(self):
        report = V3SessionPoolExperiment(4, 2).run(())
        self.assertEqual((report.steps, report.tasks, report.session_threads), (0, 0, ()))


if __name__ == "__main__":
    unittest.main()
