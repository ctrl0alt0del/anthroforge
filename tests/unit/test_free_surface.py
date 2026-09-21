import unittest
import numpy as np
from core.vcp.free_surface import prepare_rows, check_budget, union_stations
from core.vcp.fiber_surface import FiberSurfaceSpec, evaluate_fiber_surface
from core.vcp.free_curve import allocation


class FreeSurfaceTests(unittest.TestCase):
    def test_union_preserves_every_unequal_row_corner(self):
        first = [(0, 0, 0), (.12, 0, .3), (1, 0, 0)]
        second = [(0, 1, 0), (.4, 1, .2), (.6, 1, .5), (1, 1, 0)]
        rows = np.asarray(prepare_rows([first, second], densify=False))
        for row, original in zip(rows, (first, second)):
            for point in original: self.assertLess(np.linalg.norm(row - point, axis=1).min(), 1e-12)
        result = evaluate_fiber_surface([first, second], FiberSurfaceSpec(exact_samples=True))
        self.assertGreater(len(result.faces), 0)

    def test_loop_closure_has_no_duplicate_closing_vertex(self):
        rows = prepare_rows([[(0, 0, 0), (1, 0, 0), (0, 1, 0)], [(0, 0, 1), (1, 0, 1), (0, 1, 1)]], True, False)
        self.assertEqual(len(rows[0]), 3); self.assertNotEqual(rows[0][0], rows[0][-1])

    def test_budget_rejects_without_allocation(self):
        with self.assertRaisesRegex(ValueError, 'FREE_OUTPUT_BUDGET'): check_budget(262145, 2)
        with self.assertRaisesRegex(ValueError, 'FREE_STATION_BUDGET'):
            union_stations([np.column_stack((np.arange(16385), np.zeros(16385), np.zeros(16385)))])

    def test_explicit_sampling_retains_knots(self):
        self.assertEqual(sum(allocation([1, 2, 3], 63)), 63)
        with self.assertRaises(ValueError): allocation([1, 2, 3], 2)
