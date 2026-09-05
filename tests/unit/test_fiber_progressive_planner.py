import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.vcp.fiber_planner import PlannerAnchor
from core.vcp.fiber_planner_progressive import (
    advance_progressive_plan, begin_progressive_plan,
)


class _Point:
    def __init__(self, value):
        self.value = float(value)

    def copy(self):
        return _Point(self.value)

    @property
    def x(self):
        return self.value

    y = z = 0.0

    @property
    def length(self):
        return abs(self.value)

    def __add__(self, other):
        return _Point(self.value + other.value)

    def __sub__(self, other):
        return _Point(self.value - other.value)

    def __mul__(self, scale):
        return _Point(self.value * float(scale))


class _Oracle:
    margin = 0.0
    clearance = 0.0

    def active_colliders_for_segment(self, *_args, **_kwargs):
        return ()

    def segment_visible(self, *_args, **_kwargs):
        return True


class _DetourOracle:
    margin, clearance = 0.0, 0.01

    def active_colliders_for_segment(self, *_args, **_kwargs):
        return ({"sid": "A"},)

    def active_colliders_for_polyline(self, points, padding=0.0):
        _ = padding
        ids = ("A", "B") if max(point.value for point in points) > 1.0 else ("A",)
        return tuple({"sid": sid} for sid in ids)

    def segment_visible(self, a, b, owners=(), colliders=None):
        _ = owners
        ids = {collider["sid"] for collider in tuple(colliders or ())}
        return not (("A" in ids and max(a.value, b.value) <= 1.0) or
                    ("B" in ids and max(a.value, b.value) <= 2.0))

    def shell_nodes(self, collider, dense=False):
        _ = dense
        return [_Point(1.5 if collider["sid"] == "A" else 2.5)]


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

    def test_detour_expands_collision_set(self):
        anchors = (PlannerAnchor(_Point(0.0)), PlannerAnchor(_Point(1.0)))
        planner = begin_progressive_plan(_DetourOracle(), anchors, False)
        with patch("core.vcp.fiber_planner_progressive._segment_clear",
                   side_effect=_segment_clear):
            while not advance_progressive_plan(planner, 0.0):
                pass
        self.assertEqual(planner.result.active_ids, ("A", "B"))


def _segment_clear(oracle, collider, a, b, owners):
    return oracle.segment_visible(a, b, owners, (collider,))


if __name__ == "__main__":
    unittest.main()
