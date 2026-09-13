"""Planner subdivision must preserve the solver's pin layout and safe corners."""
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import numpy as np
from core.vcp.v2 import planner
from core.vcp.v2.contact_core import _planner_seed
from core.vcp.v2.contracts import V2Termination, V2Topology
from tests.unit.test_fiber_v2_planner import _request, _anchors, _box


def _route(points):
    return planner._SegmentRoute(tuple(points), planner.V2PlannerMode.ROADMAP, planner.V2PlannerBranch.ROADMAP)


def _state(indices, count=9):
    anchors = _anchors(((0,0,0),(1,1,0),(5,1,0)))
    return SimpleNamespace(request=_request(anchors,count=count), fixed_pin_indices=indices)


class PlannerHandoffTests(unittest.TestCase):
    def test_omitted_layout_does_not_use_fixed_handoff(self):
        with patch.object(planner, '_fixed_pin_handoff', side_effect=AssertionError('opt-in only')):
            result = planner.plan_reference_v43(_state(()).request)
        self.assertTrue(result.succeeded)

    def test_iterable_pin_layout_is_captured_before_validation(self):
        result = planner.plan_reference_v43(_state(()).request, pin_indices=iter((0, 4, 8)))
        self.assertTrue(result.succeeded)
        self.assertEqual(result.pin_indices, (0, 4, 8))

    def test_fixed_layout_preserves_turn_that_resampling_cuts(self):
        routes=(_route(((0,0,0),(0,1,0),(1,1,0))),_route(((1,1,0),(5,1,0))))
        old=planner._subdivide_routes(routes,planner._edge_allocations(routes,8),False)
        expected=(0,3,8); resampled=_planner_seed(SimpleNamespace(reference=old[0],pin_indices=old[1]),expected,9)
        self.assertFalse(any(np.array_equal(row,(0,1,0)) for row in resampled))
        fixed=planner._fixed_pin_handoff(_state(expected),routes)
        self.assertEqual(fixed[1],expected); self.assertIn((0,1,0),fixed[0])
        np.testing.assert_array_equal(_planner_seed(SimpleNamespace(reference=fixed[0],pin_indices=fixed[1]),expected,9),fixed[0])

    def test_open_fixed_handoff_uses_existing_collision_validator(self):
        request=_request(_anchors(((-1,0,0),(1,0,0),(1,2,0))),(_box(),),17,.05)
        result=planner.plan_reference_v43(request,pin_indices=(0,9,16))
        self.assertTrue(result.succeeded);self.assertEqual(result.pin_indices,(0,9,16))
        checked=planner.validate_static_clearance(result.reference,planner.build_triangle_snapshot(request.colliders),
            .05,result.contacts,slack=request.tolerances.clearance_slack)
        self.assertTrue(checked.valid);self.assertEqual(len(result.reference),17)

    def test_cyclic_fixed_handoff_preserves_closing_span(self):
        points=((1,0,0),(-.5,.8,0),(-.5,-.8,0))
        request=_request(_anchors(points),count=20,topology=V2Topology.CYCLIC)
        result=planner.plan_reference_v43(request,pin_indices=(0,5,12))
        self.assertTrue(result.succeeded);self.assertEqual(result.pin_indices,(0,5,12))
        self.assertEqual(tuple(result.reference[i] for i in result.pin_indices),points)
        self.assertEqual(tuple(row.edge_count for row in result.spans),(5,7,8))

    def test_unsafe_corner_cannot_be_removed_to_fit_span(self):
        routes=(_route(((0,0,0),(0,1,0),(1,1,0))),_route(((1,1,0),(5,1,0))))
        with patch.object(planner,'_edge_clear',return_value=False):
            self.assertIsNone(planner._fixed_pin_handoff(_state((0,1,8)),routes))

    def test_safe_removal_retains_exact_pin_order(self):
        routes=(_route(((0,0,0),(0,1,0),(1,1,0))),_route(((1,1,0),(5,1,0))))
        with patch.object(planner,'_edge_clear',return_value=True) as checked:
            result=planner._fixed_pin_handoff(_state((0,1,8)),routes)
        self.assertTrue(checked.called);self.assertEqual(result[1],(0,1,8))
        self.assertEqual((result[0][0],result[0][1],result[0][-1]),((0,0,0),(1,1,0),(5,1,0)))

    def test_invalid_pin_layout_is_configuration_failure(self):
        request=_state(()).request
        for indices in ((0,4,9),(1,4,8),(0,4,4),(0,8),(0,4.0,8),(0,False,8)):
            with self.subTest(indices=indices):
                result=planner.plan_reference_v43(request,pin_indices=indices)
                self.assertEqual(result.termination,V2Termination.INVALID_CONFIGURATION)

    def test_fixed_handoff_does_not_modify_request_or_objective(self):
        request=_state(()).request; before=request.signature()
        planner.plan_reference_v43(request,pin_indices=(0,4,8))
        self.assertEqual(request.signature(),before)


if __name__=='__main__':unittest.main()
