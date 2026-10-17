"""Actual C++ partial solves: motion budget, structural pins, CCD and exact samples."""
import unittest
from unittest.mock import patch
import numpy as np
from core.vcp.v3.tightening import tighten, lengths, validate_result
from tests.unit.test_fiber_v2_planner import _request, _anchors, _box


def arc(count=33, scale=1.):
    u = np.linspace(0., 1., count)
    return scale*np.column_stack((2*u-1, .5*np.sin(np.pi*u), np.zeros(count)))


def solve(points, pins=None, owners=None, **options):
    pins = (0, len(points)-1) if pins is None else pins
    request = options.pop('request', _request(_anchors(points[list(pins)].tolist()), count=len(points), radius=.001))
    return tighten(request, points, pins, owners or ('',)*len(pins), **options)


class FiberTighteningTests(unittest.TestCase):
    def test_small_motion_budget_in_native_solver(self):
        before = arc()
        for steps in (1, 2, 4, 8):
            after, report = solve(before, accepted_steps=steps, max_displacement=.005)
            self.assertTrue(report['validated']); self.assertGreater(report['length_reduction'], 0)
            self.assertLessEqual(report['max_displacement'], .0050000001)
            np.testing.assert_array_equal(after[[0, -1]], before[[0, -1]])
            self.assertLessEqual(sum(s['accepted_steps'] for s in report['spans']), steps)

    def test_sampling_and_scale_do_not_break_bound(self):
        for count, scale in ((8, .1), (33, 1.), (257, 10.)):
            before = arc(count, scale); after, report = solve(before, max_displacement=.003*scale)
            self.assertEqual(after.shape, before.shape)
            self.assertLessEqual(report['max_displacement'], .003*scale+1e-10)
            self.assertGreater(report['length_reduction'], 0)

    def test_original_nonuniform_midpoint_index_is_retained(self):
        before = arc(38); pins = (0, 7, 37)
        after, report = solve(before, pins, accepted_steps=2, max_displacement=.01)
        np.testing.assert_array_equal(before[list(pins)], after[list(pins)])
        self.assertEqual(len(report['spans']), 2)
        self.assertTrue(all(s['accepted_steps'] <= 2 for s in report['spans']))

    def test_loop_keeps_closing_span_and_pins(self):
        theta = np.arange(48)*2*np.pi/48
        before = np.column_stack((np.cos(theta), np.sin(theta), np.zeros(48)))
        after, report = solve(before, (0, 12, 25, 37), cyclic=True, max_displacement=.01)
        np.testing.assert_array_equal(before[[0, 12, 25, 37]], after[[0, 12, 25, 37]])
        self.assertEqual(len(after), 48); self.assertEqual(len(report['spans']), 4)
        self.assertLess(lengths(after, True).sum(), lengths(before, True).sum())

    def test_no_planner_or_python_optimizer(self):
        with patch('core.vcp.v3.solver.begin_plan_reference_v43', side_effect=AssertionError('planner')):
            with patch('core.vcp.v2.contact_core.solve_trust_sqp', side_effect=AssertionError('Python optimizer')):
                self.assertTrue(solve(arc(), max_displacement=.01)[1]['validated'])

    def test_native_collision_prevents_straight_chord(self):
        before = arc(49); before[:, 1] *= 2
        request = _request(_anchors(before[[0, -1]].tolist()), (_box(),), count=49, radius=.02)
        after, report = solve(before, request=request, accepted_steps=16, max_displacement=.7)
        self.assertTrue(report['validated']); self.assertGreater(after[24, 1], .3)
        self.assertLess(report['length_after'], report['length_before'])

    def test_unsafe_seed_is_not_silently_repaired(self):
        before = arc(); before[:, 1] = 0
        request = _request(_anchors(before[[0, -1]].tolist()), (_box(),), count=len(before))
        with self.assertRaisesRegex(ValueError, 'UNSAFE_SEED'): solve(before, request=request, max_displacement=.01)

    def test_invalid_options_are_rejected_before_solve(self):
        for options in (dict(accepted_steps=0), dict(accepted_steps=True), dict(accepted_steps=1.5),
                        dict(max_displacement=0), dict(max_displacement=float('nan'))):
            with self.assertRaises(ValueError): solve(arc(), **options)
        for pins in ((0, 32, 7), (0, 7, 7, 32), (1, 32)):
            with self.assertRaises(ValueError): solve(arc(), pins)

    def test_straight_fiber_is_valid_noop(self):
        before = arc(); before[:, 1] = 0
        after, report = solve(before, max_displacement=.001)
        self.assertLess(abs(report['length_reduction']), 1e-9)
        self.assertLess(report['max_displacement'], 1e-8)

    def test_adjacent_pins_and_two_sample_span_remain_exact(self):
        for points, pins in ((arc(2), (0, 1)), (arc(), (0, 1, 32))):
            after, report = solve(points, pins, max_displacement=.01)
            np.testing.assert_array_equal(points[list(pins)], after[list(pins)])
            self.assertTrue(report['validated'])

    def test_result_checks_refuse_pin_drift_and_lengthening(self):
        before = arc(); after = before.copy(); after[0, 2] += .1
        with self.assertRaisesRegex(ValueError, 'PIN_MOVED'): validate_result(before, after, (0, 32), 1., False)
        after = before.copy(); after[16, 1] += 1.
        with self.assertRaisesRegex(ValueError, 'LENGTH_INCREASED'): validate_result(before, after, (0, 32), 2., False)


if __name__ == '__main__': unittest.main()
