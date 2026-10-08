"""Material attachment equations preserve source interpolation without nearest-vertex snapping."""
import unittest
import numpy as np
from types import SimpleNamespace
from core.muscle_stacking.constraints import chart, fixed_indices, MaterialConstraint


class ExactConstraints(unittest.TestCase):
    def test_controlled_double_resampling_matches_canonical_grid(self):
        from core.muscle_stacking.constraint_layout import ordinary
        from core.vcp.fiber_surface import prepare_loft_rows
        rows = [[[0, y, 0], [.1, y, .5], [1, y, .1], [2, y, 0]] for y in (0, .4)]
        source = SimpleNamespace(construction_mode='LOFT'); fibers = [SimpleNamespace(fiber_mode='CONTROLLED')]*2
        request = SimpleNamespace(spec=SimpleNamespace(closed_u=False, target_count=9, densify=False))
        _, _, _, grid = ordinary(source, fibers, rows, request)
        expected = prepare_loft_rows(prepare_loft_rows(rows, 9), 9, densify=False)
        np.testing.assert_allclose(grid, expected)

    def test_cyclic_free_alignment_preserves_original_sample_identity(self):
        from core.muscle_stacking.constraint_layout import free_closed
        from core.vcp.free_surface import prepare_rows
        theta = np.arange(8)*np.pi/4; a = np.c_[np.cos(theta), np.sin(theta), np.zeros(8)]
        b = np.roll(a[::-1]+(0, 0, .3), 3, axis=0); across, along, knots, grid = free_closed([a, b])
        np.testing.assert_allclose(grid, prepare_rows([a, b], True))
        mapping = np.arange(grid.size//3).reshape(grid.shape[:2]); mapping = np.c_[mapping, mapping[:, 0]]
        c = chart(np.arange(len(grid)), np.r_[along, 1.], mapping, [[across[1], knots[1][2]]], ['loop'])
        np.testing.assert_allclose(np.asarray(c[0].weights) @ grid.reshape(-1, 3)[list(c[0].indices)], b[2])

    def test_interior_attachment_uses_all_contributing_variables(self):
        rows = chart([0, 1], [0, 1], np.array([[0, 1], [2, 3]]), [[.25, .5]], ['binding'])
        self.assertEqual(rows[0].indices, (0, 2, 3, 1))
        np.testing.assert_allclose(rows[0].weights, (.375, .125, .125, .375))
        np.testing.assert_array_equal(fixed_indices(rows, 4), [0, 1, 2, 3])

    def test_vertex_constraint_does_not_fix_zero_weight_neighbors(self):
        rows = chart([0, 1], [0, 1], np.array([[0, 1], [2, 3]]), [[0, 1]], ['binding'])
        np.testing.assert_array_equal(fixed_indices(rows, 4), [1])

    def test_bad_chart_and_negative_weights_are_rejected(self):
        with self.assertRaises(ValueError): chart([0, 0], [0, 1], np.arange(4).reshape(2, 2), [[0, .5]], ['binding'])
        with self.assertRaises(ValueError): fixed_indices([MaterialConstraint('bad', (0, 1), (-1, 2))], 2)

    def test_no_attachments_means_no_implicit_perimeter_pins(self):
        np.testing.assert_array_equal(fixed_indices([], 4), [])
