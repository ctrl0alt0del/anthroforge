"""Runtime consumes planner microbatches inside, not across, its existing budget."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch
from anthroforge.core.vcp import fiber_v2_runtime as runtime


def fixture():
    planner = SimpleNamespace(done=False)
    return SimpleNamespace(done=False, core_session=SimpleNamespace(planner_session=planner))


class PlannerSliceBudgetTests(unittest.TestCase):
    def test_microbatches_share_one_deadline(self):
        session = fixture()
        with patch.object(runtime, '_solve') as solve:
            with patch.object(runtime, 'perf_counter', side_effect=(0., .004, .008, .013)):
                runtime._advance_solve(session, .012)
        self.assertEqual(solve.call_count, 4)

    def test_stops_at_planner_completion_without_running_solver(self):
        session = fixture()
        def advance(value): value.core_session.planner_session = None
        with patch.object(runtime, '_solve', side_effect=advance) as solve:
            runtime._advance_solve(session, float('inf'))
        self.assertEqual(solve.call_count, 1)

    def test_cancelled_session_cannot_drain_more_batches(self):
        session = fixture()
        def advance(value): value.done = True
        with patch.object(runtime, '_solve', side_effect=advance) as solve:
            runtime._advance_solve(session, float('inf'))
        self.assertEqual(solve.call_count, 1)

    def test_atomic_overrun_yields_without_another_phase(self):
        session = fixture()
        with patch.object(runtime, '_solve') as solve:
            with patch.object(runtime, 'perf_counter', return_value=.025):
                runtime._advance_solve(session, .012)
        self.assertEqual(solve.call_count, 1)
