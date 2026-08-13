import unittest
from unittest.mock import patch

import numpy as np
import core.vcp.fiber_solver_v2 as solver_v2

from core.vcp.fiber_solver_v2 import (
    CYCLIC,
    OPEN,
    FiberFactorCache,
    StaticFiberSettings,
    assemble_normal_matrix,
    factor_key,
    smooth_coefficients,
    solve_static_fiber,
)


def _seed(count):
    t = np.linspace(0.0, 1.0, count)
    return np.column_stack((t, 0.25 * np.sin(2.0 * np.pi * t),
                            0.1 * np.sin(4.0 * np.pi * t)))


def _cyclic_seed(count):
    t = np.arange(count, dtype=float) / count
    return np.column_stack((np.cos(2.0 * np.pi * t), np.sin(2.0 * np.pi * t),
                            0.1 * np.sin(6.0 * np.pi * t)))


def _dense_operators(count, topology):
    cyclic = topology == CYCLIC
    d1 = np.zeros((count if cyclic else count - 1, count))
    rows = np.arange(len(d1)); d1[rows, rows] = -1.0; d1[rows, (rows + 1) % count] = 1.0
    d2 = np.zeros((count if cyclic else count - 2, count))
    rows = np.arange(len(d2))
    if cyclic:
        d2[rows, (rows - 1) % count] = 1.0; d2[rows, rows] = -2.0; d2[rows, (rows + 1) % count] = 1.0
    else:
        d2[rows, rows] = 1.0; d2[rows, rows + 1] = -2.0; d2[rows, rows + 2] = 1.0
    return d1, d2


def _dense_matrix(count, settings):
    d1, d2 = _dense_operators(count, settings.topology)
    _h, length_scale, bend_scale = smooth_coefficients(count, settings)
    return settings.rho * np.eye(count) + length_scale * d1.T @ d1 + bend_scale * d2.T @ d2


def _dense_pinned(seed, pins, settings):
    matrix = _dense_matrix(len(seed), settings)
    pinned = np.asarray(sorted(pins), dtype=int)
    free = np.asarray([index for index in range(len(seed)) if index not in pins], dtype=int)
    targets = np.asarray([pins[index] for index in pinned])
    result = seed.copy(); result[pinned] = targets
    rhs = settings.rho * seed[free] - matrix[np.ix_(free, pinned)] @ targets
    result[free] = np.linalg.solve(matrix[np.ix_(free, free)], rhs)
    return result


def _resample_at(source_t, source, target_t):
    return np.column_stack([np.interp(target_t, source_t, source[:, axis]) for axis in range(3)])


def _smooth_arc(count):
    t = np.linspace(0.0, 1.0, count)
    return np.column_stack((t, 0.05 * np.sin(np.pi * t), np.zeros(count)))


def _path_length(points):
    return float(np.sum(np.linalg.norm(np.diff(points, axis=0), axis=1)))


def _curvature_measure(points):
    return float(np.sum(np.diff(points, n=2, axis=0) ** 2))


def _arc_resample(points, count):
    spans = np.linalg.norm(np.diff(points, axis=0), axis=1)
    distances = np.concatenate(([0.0], np.cumsum(spans)))
    targets = np.linspace(0.0, distances[-1], count)
    return np.column_stack([np.interp(targets, distances, points[:, axis]) for axis in range(3)])


def _converged_clear(seed, tolerance=1.0e-5, min_iters=3, max_iters=180):
    points, count = seed.copy(), len(seed)
    pins = {0: seed[0].copy(), count - 1: seed[-1].copy()}
    settings, cache = StaticFiberSettings(0.9, 0.02), FiberFactorCache()
    for iteration in range(max_iters):
        solved = solve_static_fiber(points, pins, settings, cache).points
        displacement = np.max(np.linalg.norm(solved - points, axis=1))
        points = solved
        if iteration + 1 >= min_iters and displacement < tolerance:
            return points, iteration + 1
    return points, max_iters


def _scene_tolerance(points):
    diagonal = float(np.linalg.norm(np.ptp(np.asarray(points), axis=0)))
    return max(1.0e-7, 1.0e-6 * diagonal)


class StaticFiberSolverV2Tests(unittest.TestCase):
    def test_open_matrix_matches_independent_dense_assembly(self):
        settings = StaticFiberSettings(0.07, 0.0004, 1.0, OPEN)
        np.testing.assert_allclose(assemble_normal_matrix(11, settings),
                                   _dense_matrix(11, settings), atol=1.0e-13)

    def test_cyclic_matrix_matches_independent_dense_assembly(self):
        settings = StaticFiberSettings(0.03, 0.0002, 1.5, CYCLIC)
        np.testing.assert_allclose(assemble_normal_matrix(12, settings),
                                   _dense_matrix(12, settings), atol=1.0e-13)

    def test_open_pinned_solution_matches_dense_reference(self):
        seed = _seed(17); pins = {0: (0.0, 0.2, 0.0), 8: (0.5, -0.1, 0.2), 16: (1.0, 0.0, 0.0)}
        settings = StaticFiberSettings(0.08, 0.0007, 1.0, OPEN)
        result = solve_static_fiber(seed, pins, settings, FiberFactorCache())
        np.testing.assert_allclose(result.points, _dense_pinned(seed, pins, settings), atol=2.0e-12)
        self.assertLess(result.stationarity_residual, 2.0e-11)

    def test_cyclic_pinned_solution_matches_dense_reference(self):
        seed = _cyclic_seed(18); pins = {2: seed[2] + (0.1, 0.0, 0.0), 11: seed[11]}
        settings = StaticFiberSettings(0.02, 0.0001, 1.0, CYCLIC)
        result = solve_static_fiber(seed, pins, settings, FiberFactorCache())
        np.testing.assert_allclose(result.points, _dense_pinned(seed, pins, settings), atol=2.0e-12)
        np.testing.assert_array_equal(result.points[sorted(pins)], np.asarray([pins[i] for i in sorted(pins)]))

    def test_random_pin_masks_match_dense_reference(self):
        rng = np.random.default_rng(817)
        for topology in (OPEN, CYCLIC):
            for count in (3, 4, 9, 17, 31):
                seed = rng.normal(size=(count, 3))
                chosen = rng.choice(count, size=max(1, count // 4), replace=False)
                pins = {int(index): rng.normal(size=3) for index in chosen}
                settings = StaticFiberSettings(0.013, 0.00017, 1.3, topology)
                with self.subTest(topology=topology, count=count):
                    solved = solve_static_fiber(seed, pins, settings, FiberFactorCache()).points
                    np.testing.assert_allclose(solved, _dense_pinned(seed, pins, settings), atol=2.0e-10)

    def test_factor_build_never_assembles_a_dense_matrix(self):
        seed = _seed(64); cache = FiberFactorCache()
        with patch.object(solver_v2, "assemble_normal_matrix", side_effect=AssertionError("dense")):
            result = solve_static_fiber(seed, {0: seed[0], 63: seed[-1]}, factor_cache=cache)
        self.assertEqual((len(result.points), cache.stats()["factor_builds"]), (64, 1))

    def test_factor_storage_scales_linearly_for_open_and_cyclic(self):
        sizes = {}
        for topology in (OPEN, CYCLIC):
            for count in (512, 1024):
                cache = FiberFactorCache()
                solve_static_fiber(_seed(count), {0: (0, 0, 0)},
                                   StaticFiberSettings(topology=topology), cache)
                sizes[topology, count] = cache.stats()["bytes"]
            self.assertLess(sizes[topology, 1024], 2.1 * sizes[topology, 512])
        self.assertLess(sizes[CYCLIC, 1024], 100_000)

    def test_unpinned_cyclic_system_uses_rho_to_remove_nullspace(self):
        seed = _cyclic_seed(15); settings = StaticFiberSettings(0.04, 0.0003, 1.0, CYCLIC)
        result = solve_static_fiber(seed, settings=settings, factor_cache=FiberFactorCache())
        expected = np.linalg.solve(_dense_matrix(len(seed), settings), settings.rho * seed)
        np.testing.assert_allclose(result.points, expected, atol=2.0e-12)
        self.assertTrue(np.isfinite(result.points).all())

    def test_all_hard_pins_are_bit_exact_without_a_factor(self):
        seed = _seed(5); pins = {index: seed[index] + index for index in range(5)}
        cache = FiberFactorCache(); result = solve_static_fiber(seed, pins, factor_cache=cache)
        np.testing.assert_array_equal(result.points, np.asarray([pins[i] for i in range(5)]))
        self.assertEqual((result.factor_cache_hit, cache.stats()["factor_builds"]), (False, 0))

    def test_length_and_bend_weights_produce_distinct_solutions(self):
        seed = _seed(31); pins = {0: seed[0], 30: seed[-1]}
        length = solve_static_fiber(seed, pins, StaticFiberSettings(0.2, 0.0)).points
        bend = solve_static_fiber(seed, pins, StaticFiberSettings(0.0, 0.002)).points
        self.assertGreater(np.max(np.linalg.norm(length - bend, axis=1)), 0.01)

    def test_length_weight_monotonically_shortens_the_path(self):
        seed = _seed(64); pins = {0: seed[0], 63: seed[-1]}
        weights = (0.0, 0.001, 0.01, 0.1)
        lengths = [_path_length(solve_static_fiber(
            seed, pins, StaticFiberSettings(weight, 0.0001)).points) for weight in weights]
        self.assertTrue(all(right < left for left, right in zip(lengths, lengths[1:])))

    def test_bend_weight_monotonically_reduces_curvature(self):
        seed = _seed(64); pins = {0: seed[0], 63: seed[-1]}
        weights = (0.0, 0.000001, 0.0001, 0.001)
        values = [_curvature_measure(solve_static_fiber(
            seed, pins, StaticFiberSettings(0.01, weight)).points) for weight in weights]
        self.assertTrue(all(right < left for left, right in zip(values, values[1:])))

    def test_repeated_solve_is_deterministic_and_reuses_factor(self):
        seed = _seed(25); pins = {0: seed[0], 24: seed[-1]}; cache = FiberFactorCache()
        first = solve_static_fiber(seed, pins, factor_cache=cache)
        second = solve_static_fiber(seed, pins, factor_cache=cache)
        np.testing.assert_array_equal(first.points, second.points)
        self.assertEqual((first.factor_cache_hit, second.factor_cache_hit), (False, True))
        self.assertEqual(cache.stats()["factor_builds"], 1)

    def test_cold_and_factor_warm_outputs_are_bit_exact(self):
        seed = _smooth_arc(64); pins = {0: seed[0], 63: seed[-1]}
        settings, warm_cache = StaticFiberSettings(0.9, 0.02), FiberFactorCache()
        cold = solve_static_fiber(seed, pins, settings, FiberFactorCache()).points
        solve_static_fiber(seed, pins, settings, warm_cache)
        warm = solve_static_fiber(seed, pins, settings, warm_cache)
        np.testing.assert_array_equal(cold, warm.points)
        self.assertTrue(warm.factor_cache_hit)

    @unittest.expectedFailure
    def test_warm_seed_and_cold_outputs_meet_scene_tolerance(self):
        seed = _smooth_arc(64)
        cold, _cold_iters = _converged_clear(seed)
        warm, _warm_iters = _converged_clear(cold)
        tolerance = _scene_tolerance(np.vstack((seed, cold, warm)))
        np.testing.assert_allclose(warm, cold, rtol=0.0, atol=tolerance)

    def test_factor_key_covers_topology_mask_count_weights_and_rho(self):
        base = StaticFiberSettings(0.1, 0.001, 1.0, OPEN)
        keys = {factor_key(8, pins, settings) for pins, settings in (
            ((0, 7), base), ((0, 6), base), ((0, 7), StaticFiberSettings(0.2, 0.001, 1.0, OPEN)),
            ((0, 7), StaticFiberSettings(0.1, 0.002, 1.0, OPEN)),
            ((0, 7), StaticFiberSettings(0.1, 0.001, 2.0, OPEN)),
            ((0, 7), StaticFiberSettings(0.1, 0.001, 1.0, CYCLIC)))}
        keys.add(factor_key(9, (0, 8), base))
        self.assertEqual(len(keys), 7)

    def test_factor_cache_is_lru_bounded(self):
        cache = FiberFactorCache(max_entries=2, max_bytes=1024 * 1024)
        for weight in (0.01, 0.02, 0.03):
            solve_static_fiber(_seed(12), {0: (0, 0, 0)}, StaticFiberSettings(weight, 0.0), cache)
        stats = cache.stats()
        self.assertEqual((stats["entries"], stats["factor_builds"], stats["evictions"]), (2, 3, 1))

    def test_normalization_converges_across_node_counts(self):
        settings = StaticFiberSettings(0.01, 0.0001)
        results = [solve_static_fiber(_seed(count), {0: (0, 0, 0), count - 1: (1, 0, 0)}, settings).points
                   for count in (17, 33, 65)]
        coarse = np.max(np.linalg.norm(results[0] - _resample_at(np.linspace(0, 1, 33), results[1], np.linspace(0, 1, 17)), axis=1))
        fine = np.max(np.linalg.norm(results[1] - _resample_at(np.linspace(0, 1, 65), results[2], np.linspace(0, 1, 33)), axis=1))
        self.assertLess(fine, coarse)
        self.assertLess(fine, 0.006)

    def test_converged_64_and_128_solutions_meet_release_gate(self):
        coarse, _coarse_iters = _converged_clear(_smooth_arc(64))
        fine, _fine_iters = _converged_clear(_smooth_arc(128))
        coarse_sample = _arc_resample(coarse, 256)
        fine_sample = _arc_resample(fine, 256)
        difference = np.max(np.linalg.norm(coarse_sample - fine_sample, axis=1))
        length_delta = abs(_path_length(coarse) - _path_length(fine)) / _path_length(fine)
        self.assertLessEqual(difference, 0.1 * 0.002)
        self.assertLess(length_delta, 0.01)

    def test_hard_pins_meet_scene_scale_tolerance(self):
        seed = 10.0 * _seed(128)
        pins = {0: seed[0], 63: np.array((4.8, -1.2, 0.7)), 127: seed[-1]}
        result = solve_static_fiber(seed, pins, StaticFiberSettings(0.1, 0.001))
        tolerance = _scene_tolerance(np.vstack((seed, tuple(pins.values()))))
        errors = [np.linalg.norm(result.points[index] - target) for index, target in pins.items()]
        self.assertLessEqual(max(errors), tolerance)

    def test_spacing_coefficients_follow_open_and_cyclic_contract(self):
        opened = smooth_coefficients(5, StaticFiberSettings(2.0, 3.0, topology=OPEN))
        cyclic = smooth_coefficients(5, StaticFiberSettings(2.0, 3.0, topology=CYCLIC))
        np.testing.assert_allclose(opened, (0.25, 8.0, 192.0))
        np.testing.assert_allclose(cyclic, (0.2, 10.0, 375.0))

    def test_invalid_inputs_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "shape"):
            solve_static_fiber(np.zeros((4, 2)))
        with self.assertRaisesRegex(ValueError, "out of range"):
            solve_static_fiber(_seed(4), {4: (0, 0, 0)})
        with self.assertRaisesRegex(ValueError, "rho"):
            solve_static_fiber(_seed(4), settings=StaticFiberSettings(rho=0.0))


if __name__ == "__main__":
    unittest.main()
