import ast
from dataclasses import replace
from pathlib import Path
import unittest

import numpy as np

from core.vcp.v2 import (
    StructuralFactorCache, V2Quality, V2Settings, V2Topology,
    solve_structural, structural_energy,
)


def _reference(count):
    t = np.linspace(0.0, 1.0, count)
    return np.column_stack((t, 0.2 * np.sin(2.0 * np.pi * t),
                            0.08 * np.sin(4.0 * np.pi * t)))


def _d1(count, cyclic):
    rows = count if cyclic else count - 1
    matrix = np.zeros((rows, count))
    indices = np.arange(rows)
    matrix[indices, indices] = -1.0
    matrix[indices, (indices + 1) % count] = 1.0
    return matrix


def _d2(count, cyclic):
    rows = count if cyclic else count - 2
    matrix = np.zeros((rows, count)); indices = np.arange(rows)
    matrix[indices, (indices - 1) % count if cyclic else indices] = 1.0
    matrix[indices, indices if cyclic else indices + 1] = -2.0
    matrix[indices, (indices + 1) % count if cyclic else indices + 2] = 1.0
    return matrix


def _dense_matrix(count, settings):
    cyclic = settings.topology is V2Topology.CYCLIC
    spacing = 1.0 / (count if cyclic else count - 1)
    first, second = _d1(count, cyclic), _d2(count, cyclic)
    return (settings.fidelity_weight * np.eye(count) +
            (settings.length_weight / spacing) * first.T @ first +
            (settings.curvature_weight / spacing ** 3) * second.T @ second)


def _dense_solution(reference, pins, settings):
    matrix = _dense_matrix(len(reference), settings)
    pinned = np.asarray(sorted(pins), dtype=int)
    free = np.asarray([i for i in range(len(reference)) if i not in pins], dtype=int)
    targets = np.asarray([pins[index] for index in pinned]); result = reference.copy()
    result[pinned] = targets
    rhs = settings.fidelity_weight * reference[free] - matrix[np.ix_(free, pinned)] @ targets
    result[free] = np.linalg.solve(matrix[np.ix_(free, free)], rhs)
    return result


def _path_length(points):
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())


def _curvature(points):
    return float(np.square(np.diff(points, n=2, axis=0)).sum())


class FiberV2StructuralTests(unittest.TestCase):
    def test_open_solution_matches_independent_dense_reference(self):
        reference = _reference(19); pins = {0: reference[0], 9: (0.5, -0.1, 0.2), 18: reference[-1]}
        settings = V2Settings(node_count=19, length_weight=0.08, curvature_weight=0.0007)
        solved = solve_structural(reference, pins, settings, StructuralFactorCache())
        np.testing.assert_allclose(solved.points, _dense_solution(reference, pins, settings), atol=2.0e-12)
        self.assertLess(solved.stationarity_residual, 2.0e-11)

    def test_cyclic_solution_matches_independent_dense_reference(self):
        reference = _reference(18); pins = {2: reference[2] + (0.1, 0, 0), 11: reference[11]}
        settings = V2Settings(topology=V2Topology.CYCLIC, node_count=18,
                              length_weight=0.02, curvature_weight=0.0001)
        solved = solve_structural(reference, pins, settings, StructuralFactorCache())
        np.testing.assert_allclose(solved.points, _dense_solution(reference, pins, settings), atol=2.0e-12)

    def test_hard_pins_are_bit_exact(self):
        reference = _reference(32); pins = {0: (0, 1, 2), 12: (3, 4, 5), 31: (6, 7, 8)}
        result = solve_structural(reference, pins, V2Settings(node_count=32))
        np.testing.assert_array_equal(result.points[list(pins)], np.asarray(list(pins.values())))

    def test_length_and_curvature_controls_are_distinct(self):
        reference = _reference(64); pins = {0: reference[0], 63: reference[-1]}
        length = solve_structural(reference, pins, V2Settings(node_count=64, length_weight=0.2, curvature_weight=0)).points
        bend = solve_structural(reference, pins, V2Settings(node_count=64, length_weight=0, curvature_weight=0.002)).points
        self.assertGreater(np.max(np.linalg.norm(length - bend, axis=1)), 0.01)

    def test_weight_effects_are_monotonic(self):
        reference = _reference(64); pins = {0: reference[0], 63: reference[-1]}
        lengths = [_path_length(solve_structural(reference, pins, V2Settings(node_count=64, length_weight=w)).points)
                   for w in (0.0, 0.001, 0.01, 0.1)]
        curves = [_curvature(solve_structural(reference, pins, V2Settings(node_count=64, curvature_weight=w)).points)
                  for w in (0.0, 0.000001, 0.0001, 0.001)]
        self.assertTrue(all(b < a for a, b in zip(lengths, lengths[1:])))
        self.assertTrue(all(b < a for a, b in zip(curves, curves[1:])))

    def test_execution_budget_and_quality_do_not_change_objective(self):
        reference = _reference(40); pins = {0: reference[0], 39: reference[-1]}
        base = V2Settings(node_count=40)
        final = replace(base, quality=V2Quality.FINAL, max_accepted_steps=999)
        np.testing.assert_array_equal(solve_structural(reference, pins, base).points,
                                      solve_structural(reference, pins, final).points)

    def test_output_is_read_only_and_reference_is_unchanged(self):
        reference = _reference(16); original = reference.copy()
        result = solve_structural(reference, {0: reference[0], 15: reference[-1]})
        np.testing.assert_array_equal(reference, original)
        self.assertFalse(result.points.flags.writeable)
        with self.assertRaises(ValueError):
            result.points[0, 0] = 9.0

    def test_energy_components_sum_to_total(self):
        reference = _reference(24); result = solve_structural(reference)
        measured = structural_energy(result.points, reference)
        self.assertAlmostEqual(measured.total, measured.fidelity + measured.length + measured.curvature)
        self.assertAlmostEqual(result.energy.total, measured.total)

    def test_factor_cache_storage_scales_linearly(self):
        sizes = []
        for count in (512, 1024):
            cache = StructuralFactorCache()
            solve_structural(_reference(count), {0: (0, 0, 0)}, V2Settings(node_count=count), cache)
            sizes.append(cache.stats()["bytes"])
        self.assertLess(sizes[1], 2.1 * sizes[0])
        self.assertLess(sizes[1], 100_000)

    def test_structural_module_does_not_import_blender_or_v1_solver(self):
        path = Path(__file__).parents[2] / "core" / "vcp" / "v2" / "structural.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        names = [name.name for node in ast.walk(tree) if isinstance(node, ast.Import) for name in node.names]
        self.assertNotIn("bpy", names)
        self.assertFalse(any("fiber_solver_v2" in str(module) for module in modules))


if __name__ == "__main__":
    unittest.main()
