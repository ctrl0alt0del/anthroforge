import unittest

import numpy as np

from core.vcp.v2 import (V2Settings, V2Topology, assemble_sampled_contact_matrix,
                         clear_sampled_contact_cache, sample_edge_points,
                         sampled_contact_cache_stats, sampled_contact_energy,
                         solve_sampled_contact)


FACTORS = (0.1, 0.3, 0.5, 0.7, 0.9)


def _inputs(count, cyclic=False):
    rng = np.random.default_rng(8200 + count + int(cyclic))
    reference = rng.normal(size=(count, 3)); current = rng.normal(size=(count, 3))
    settings = V2Settings(topology=V2Topology.CYCLIC if cyclic else V2Topology.OPEN)
    targets = sample_edge_points(current, FACTORS, settings) + 0.1 * rng.normal(
        size=(count if cyclic else count - 1, len(FACTORS), 3))
    return reference, current, targets, settings


def _rhs(reference, targets, settings, weight):
    rhs = settings.fidelity_weight * reference; scale = weight / len(FACTORS)
    for edge, rows in enumerate(targets):
        for factor, target in zip(FACTORS, rows):
            rhs[edge] += scale * (1.0 - factor) * target
            rhs[(edge + 1) % len(rhs)] += scale * factor * target
    return rhs


def _dense(reference, targets, pins, settings, weight):
    matrix = assemble_sampled_contact_matrix(len(reference), settings, weight, FACTORS)
    rhs = _rhs(reference, targets, settings, weight); fixed = np.asarray(sorted(pins))
    free = np.asarray([index for index in range(len(reference)) if index not in pins])
    values = np.asarray([pins[int(index)] for index in fixed]); result = reference.copy()
    result[fixed] = values
    result[free] = np.linalg.solve(matrix[np.ix_(free, free)], rhs[free] - matrix[np.ix_(free, fixed)] @ values)
    return result


class FiberV2SampledContactTests(unittest.TestCase):
    def _assert_dense(self, cyclic):
        reference, _current, targets, settings = _inputs(13, cyclic); weight = 31.0
        pins = {0: (0.2, -0.1, 0.4), 6: (-0.3, 0.6, 0.1)}
        result = solve_sampled_contact(reference, targets, pins, settings, weight, FACTORS)
        expected = _dense(reference, targets, pins, settings, weight)
        np.testing.assert_allclose(result.points, expected, atol=3.0e-11)
        self.assertLess(result.stationarity_residual, 3.0e-10)

    def test_open_samples_match_dense_reference(self):
        self._assert_dense(False)

    def test_cyclic_samples_match_dense_reference(self):
        self._assert_dense(True)

    def test_global_solve_reduces_frozen_sample_energy(self):
        reference, current, targets, settings = _inputs(19); pins = {0: current[0], 18: current[-1]}
        result = solve_sampled_contact(reference, targets, pins, settings, 10.0, FACTORS)
        before = sampled_contact_energy(current, reference, targets, settings, 10.0, FACTORS)
        self.assertLessEqual(result.energy.total, before.total + 1.0e-10)

    def test_sample_energy_uses_total_edges_and_mean_samples(self):
        reference, current, targets, settings = _inputs(9); weight = 7.0
        energy = sampled_contact_energy(current, reference, targets, settings, weight, FACTORS)
        residual = sample_edge_points(current, FACTORS, settings) - targets
        expected = weight * float(np.sum(residual ** 2)) / len(FACTORS)
        self.assertAlmostEqual(energy.edge, expected, places=12)

    def test_sampled_factor_is_reused_deterministically(self):
        clear_sampled_contact_cache(); reference, _current, targets, settings = _inputs(17)
        first = solve_sampled_contact(reference, targets, settings=settings)
        second = solve_sampled_contact(reference, targets, settings=settings)
        self.assertFalse(first.factor_cache_hit); self.assertTrue(second.factor_cache_hit)
        self.assertEqual(sampled_contact_cache_stats()["factor_builds"], 1)
        np.testing.assert_array_equal(first.points, second.points)

    def test_sample_factors_fail_closed(self):
        reference, _current, targets, settings = _inputs(9)
        with self.assertRaises(ValueError):
            solve_sampled_contact(reference, targets, settings=settings, sample_factors=(0.5, 0.5))


if __name__ == "__main__":
    unittest.main()
