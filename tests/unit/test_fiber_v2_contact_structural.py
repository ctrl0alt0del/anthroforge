from dataclasses import replace
import unittest

import numpy as np

from core.vcp.v2 import (V2Settings, V2Topology, assemble_contact_matrix,
                         clear_contact_factor_cache, contact_factor_cache_stats,
                         contact_slot_energy, solve_contact_structural)


def _inputs(count, cyclic=False):
    rng = np.random.default_rng(8100 + count + int(cyclic))
    reference = rng.normal(size=(count, 3)); current = rng.normal(size=(count, 3))
    nodes = current + 0.1 * rng.normal(size=(count, 3)); edge_count = count if cyclic else count - 1
    edges = 0.5 * (current[:edge_count] + np.roll(current, -1, axis=0)[:edge_count])
    edges += 0.1 * rng.normal(size=(edge_count, 3))
    settings = V2Settings(topology=V2Topology.CYCLIC if cyclic else V2Topology.OPEN)
    return reference, current, nodes, edges, settings


def _rhs(reference, nodes, edges, settings, node_weight, edge_weight):
    rhs = settings.fidelity_weight * reference + node_weight * nodes
    for edge, target in enumerate(edges):
        rhs[edge] += 0.5 * edge_weight * target
        rhs[(edge + 1) % len(rhs)] += 0.5 * edge_weight * target
    return rhs


def _dense(reference, nodes, edges, pins, settings, node_weight, edge_weight):
    matrix = assemble_contact_matrix(len(reference), settings, node_weight, edge_weight)
    rhs = _rhs(reference, nodes, edges, settings, node_weight, edge_weight)
    fixed = np.asarray(sorted(pins)); free = np.asarray([i for i in range(len(reference)) if i not in pins])
    targets = np.asarray([pins[int(index)] for index in fixed]); result = reference.copy()
    result[fixed] = targets; result[free] = np.linalg.solve(matrix[np.ix_(free, free)], rhs[free] - matrix[np.ix_(free, fixed)] @ targets)
    return result


class FiberV2ContactStructuralTests(unittest.TestCase):
    def _assert_dense(self, cyclic):
        reference, current, nodes, edges, settings = _inputs(11, cyclic)
        pins = {0: (0.2, -0.1, 0.4), 5: (-0.3, 0.6, 0.1)}; weights = (37.0, 19.0)
        result = solve_contact_structural(reference, current, nodes, edges, pins, settings, *weights)
        expected = _dense(reference, nodes, edges, pins, settings, *weights)
        np.testing.assert_allclose(result.points, expected, atol=2.0e-11)
        self.assertLess(result.stationarity_residual, 2.0e-10)

    def test_open_contact_slots_match_dense_reference(self):
        self._assert_dense(False)

    def test_cyclic_contact_slots_match_dense_reference(self):
        self._assert_dense(True)

    def test_global_solve_reduces_frozen_local_energy(self):
        reference, current, nodes, edges, settings = _inputs(19)
        pins = {0: current[0], 18: current[-1]}; weights = (10.0, 10.0)
        result = solve_contact_structural(reference, current, nodes, edges, pins, settings, *weights)
        before = contact_slot_energy(current, reference, nodes, edges, settings, *weights)
        self.assertLessEqual(result.energy.total, before.total + 1.0e-10)

    def test_factor_is_reused_without_changing_result(self):
        clear_contact_factor_cache(); values = _inputs(17)
        first = solve_contact_structural(*values[:4], settings=values[4])
        second = solve_contact_structural(*values[:4], settings=values[4])
        self.assertFalse(first.factor_cache_hit); self.assertTrue(second.factor_cache_hit)
        self.assertEqual(contact_factor_cache_stats()["factor_builds"], 1)
        np.testing.assert_array_equal(first.points, second.points)

    def test_weight_validation_is_fail_closed(self):
        values = _inputs(9)
        with self.assertRaises(ValueError):
            solve_contact_structural(*values[:4], settings=values[4], node_weight=0.0)


if __name__ == "__main__":
    unittest.main()
