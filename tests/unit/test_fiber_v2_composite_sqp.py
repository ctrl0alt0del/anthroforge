import unittest

import numpy as np

from core.vcp.v2.contact_core import V2Contact, V2ContactExperiment, solve_contact_core
from core.vcp.v2.trust_sqp import second_order_correction, solve_composite_sqp
from tests.unit.test_fiber_v2_solver import _box_request


def _contact(gap=-.05):
    return V2Contact(4, .5, "C", 0, "DISTANCE", (0.0, 1.0, 0.0), gap, multiplier=1.0)


def _projected_gap(source, candidate, contact):
    delta = np.asarray(candidate) - np.asarray(source)
    movement = (1.0 - contact.factor) * delta[contact.edge]
    movement += contact.factor * delta[contact.edge + 1]
    return contact.gap + float(np.dot(contact.normal, movement))


def _direct_points(request):
    first, last = request.anchors[0].point, request.anchors[-1].point
    return np.linspace(first, last, request.settings.node_count)


class FiberV2CompositeSqpTests(unittest.TestCase):
    def test_tangential_ablation_does_not_fake_normal_feasibility(self):
        request = _box_request(); points = _direct_points(request)
        pins = {0: points[0], len(points) - 1: points[-1]}; contact = _contact()
        step = solve_composite_sqp(points, points, request.settings, (contact,), pins, .2, "TANGENTIAL")
        self.assertLess(_projected_gap(points, step.points, contact), 0.0)
        self.assertEqual(step.normal_fraction, 0.0)

    def test_composite_step_prioritizes_normal_feasibility(self):
        request = _box_request(); points = _direct_points(request)
        pins = {0: points[0], len(points) - 1: points[-1]}; contact = _contact()
        step = solve_composite_sqp(points, points, request.settings, (contact,), pins, .2, "COMPOSITE")
        self.assertGreater(_projected_gap(points, step.points, contact), -.01)
        np.testing.assert_array_equal(step.points[[0, -1]], points[[0, -1]])

    def test_soc_cancels_nonlinear_constraint_defect(self):
        points = np.zeros((10, 3)); contact = _contact(); before = _projected_gap(points, points, contact)
        corrected, norm, _condition = second_order_correction(points, (contact,), {}, .2)
        self.assertGreater(norm, 0.0)
        self.assertGreater(_projected_gap(points, corrected, contact), before)
        self.assertGreater(_projected_gap(points, corrected, contact), -1.0e-8)

    def test_each_ablation_runs_through_same_validating_core(self):
        request = _box_request(); outputs = {}
        for name in ("BASE", "TANGENTIAL", "COMPOSITE", "COMPOSITE_SOC"):
            experiment = V2ContactExperiment(sqp_variant=name)
            outputs[name] = solve_contact_core(request, use_planner=False,
                use_filter_sqp=True, experiment=experiment)
        self.assertTrue(all(package.result.validated for package in outputs.values()))
        self.assertEqual(outputs["COMPOSITE_SOC"].result.termination.value, "CONVERGED")


if __name__ == "__main__":
    unittest.main()
