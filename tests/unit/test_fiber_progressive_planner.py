import unittest
from types import SimpleNamespace

from core.vcp.fiber_planner import PlannerAnchor
from core.vcp.fiber_planner_progressive import (
    advance_progressive_plan, begin_progressive_plan,
)


class _Point:
    def __init__(self, value):
        self.value = float(value)

    def copy(self):
        return _Point(self.value)


class _Oracle:
    margin = 0.0
    clearance = 0.0

    def active_colliders_for_segment(self, *_args, **_kwargs):
        return ()

    def segment_visible(self, *_args, **_kwargs):
        return True


class ProgressivePlannerTests(unittest.TestCase):
    def test_direct_plan_completes_resumably(self):
        anchors = (PlannerAnchor(_Point(0.0)), PlannerAnchor(_Point(1.0)))
        planner = begin_progressive_plan(_Oracle(), anchors)
        self.assertTrue(advance_progressive_plan(planner, 0.0))
        self.assertEqual(([p.value for p in planner.result.points], planner.result.mode),
                         ([0.0, 1.0], "DIRECT"))

    def test_empty_anchor_plan_is_stable(self):
        planner = begin_progressive_plan(_Oracle(), ())
        self.assertTrue(advance_progressive_plan(planner, 0.0))
        self.assertEqual((planner.result.points, planner.result.active_ids), ([], ()))


if __name__ == "__main__":
    unittest.main()
