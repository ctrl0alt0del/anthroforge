import unittest

import numpy as np

from core.vcp.v2.contact_unilateral import (UnilateralConstraint,
                                             solve_unilateral_contact)
from core.vcp.v2.contracts import V2Settings
from core.vcp.v2 import structural as base
from core.vcp.v2.structural import assemble_normal_matrix, solve_structural


def _settings():
    return V2Settings(length_weight=.2, curvature_weight=.01, fidelity_weight=1.0)


def _reference():
    return np.asarray(((0, 0, 0), (.5, -1, 0), (1, 0, 0)), dtype=np.float64)


def _pins():
    return {0: (0, 0, 0), 2: (1, 0, 0)}


def _node_constraint(offset, tag=""):
    return UnilateralConstraint((1,), (1.0,), (0.0, 1.0, 0.0), offset, tag)


class FiberV2UnilateralContactTests(unittest.TestCase):
    def test_active_constraint_is_satisfied_exactly(self):
        result = solve_unilateral_contact(_reference(), (_node_constraint(.25),), _pins(), _settings())
        self.assertTrue(result.feasible); self.assertAlmostEqual(result.points[1, 1], .25, places=10)
        self.assertEqual(result.active_indices, (0,)); self.assertLess(result.stationarity_residual, 1.0e-9)

    def test_redundant_inequality_keeps_only_strict_plane(self):
        rows = (_node_constraint(.10, "loose"), _node_constraint(.25, "strict"))
        result = solve_unilateral_contact(_reference(), rows, _pins(), _settings())
        self.assertTrue(result.feasible); self.assertEqual(result.active_indices, (1,))
        self.assertGreaterEqual(float(np.min(result.gaps)), -1.0e-9)

    def test_active_hint_survives_appended_constraint(self):
        first = solve_unilateral_contact(_reference(), (_node_constraint(.25),), _pins(), _settings())
        rows = (_node_constraint(.25), _node_constraint(.10))
        second = solve_unilateral_contact(_reference(), rows, _pins(), _settings(), active_hint=first.active_indices)
        self.assertTrue(second.feasible); self.assertEqual(second.active_indices, (0,))

    def test_edge_sample_constraint_uses_both_nodes(self):
        reference = np.asarray(((0, 0, 0), (.3, -.4, 0), (.7, -.4, 0), (1, 0, 0)))
        row = UnilateralConstraint((1, 2), (.25, .75), (0, 1, 0), .15)
        result = solve_unilateral_contact(reference, (row,), {0: reference[0], 3: reference[3]}, _settings())
        sample = .25 * result.points[1] + .75 * result.points[2]
        self.assertTrue(result.feasible); self.assertAlmostEqual(sample[1], .15, places=9)

    def test_pin_only_violation_is_infeasible(self):
        reference = np.asarray(((0, 0, 0), (1, 0, 0)), dtype=np.float64)
        row = UnilateralConstraint((0,), (1,), (0, 1, 0), 1.0)
        result = solve_unilateral_contact(reference, (row,), {0: reference[0], 1: reference[1]}, _settings())
        self.assertFalse(result.feasible); self.assertAlmostEqual(result.primal_residual, 1.0)

    def test_single_constraint_matches_dense_kkt_reference(self):
        row = _node_constraint(.25); settings = _settings(); unconstrained = solve_structural(_reference(), _pins(), settings)
        matrix = assemble_normal_matrix(3, settings=base._static_settings(settings))
        free = np.asarray((1,)); response = np.linalg.solve(matrix[np.ix_(free, free)], np.asarray((1.0,)))
        multiplier = (.25 - unconstrained.points[1, 1]) / response[0]
        expected = unconstrained.points[1, 1] + response[0] * multiplier
        result = solve_unilateral_contact(_reference(), (row,), _pins(), settings)
        self.assertAlmostEqual(result.points[1, 1], expected, places=10)


if __name__ == "__main__":
    unittest.main()
