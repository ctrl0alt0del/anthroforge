import unittest
import numpy as np
from core.vcp.free_surface_stations import prepare, remap
from core.vcp.fiber_surface import evaluate_fiber_surface, FiberSurfaceSpec


class MaterialStationTests(unittest.TestCase):
    def test_narrow_two_fiber_chart_has_an_inflatable_interior_row(self):
        from core.vcp.free_surface import prepare_rows
        rows = np.array([[[0, 0, 0], [0, 1, .1], [0, 2, 0]],
                         [[.01, 0, 0], [.01, 1, .1], [.01, 2, 0]]])
        for output in (prepare(rows, [[0, .5, 1]]*2), prepare_rows(rows)):
            output = np.asarray(output)
            self.assertEqual(output.shape, (3, 3, 3))
            np.testing.assert_array_equal(output[[0, -1]], rows)
            np.testing.assert_allclose(output[1], rows.mean(axis=0))

    def test_material_stations_preserve_corresponding_features(self):
        rows = [[[0, 0, 0], [0, .2, 0], [0, 1, 0]], [[1, 0, 0], [1, .8, .3], [1, 1, 0]]]
        result = prepare(rows, [[0, .5, 1], [0, .5, 1]])
        np.testing.assert_allclose(result[0][1], rows[0][1]); np.testing.assert_allclose(result[-1][1], rows[1][1])
        old = evaluate_fiber_surface(rows, FiberSurfaceSpec(exact_samples=True))
        new = evaluate_fiber_surface(rows, FiberSurfaceSpec(exact_samples=True, parameter_stations=((0, .5, 1), (0, .5, 1))))
        self.assertNotEqual(len(old.rows[0]), len(new.rows[0]))

    def test_resampling_retains_material_breakpoint_and_endpoints(self):
        row = dict(sample_ids=['a', 'b', 'c'], stations=[-1, 0, 1], reference_points=[[0, 0, 0], [0, 1, 0], [0, 4, 0]])
        payload = dict(samples=[dict(sample_id=key, co=[0, y, 0]) for key, y in [('a', 0), ('x', .5), ('b', 1), ('y', 2.5), ('c', 4)]])
        np.testing.assert_allclose(remap(row, payload), [-1, -.5, 0, .5, 1])

    def test_invalid_order_and_station_shapes_rejected(self):
        with self.assertRaisesRegex(ValueError, 'STATIONS'): prepare([[[0, 0, 0], [1, 0, 0]]], [[1, 0]])
        row = dict(sample_ids=['a', 'b'], stations=[0, 1], reference_points=[[0, 0, 0], [0, 1, 0]])
        with self.assertRaisesRegex(ValueError, 'STALE'):
            remap(row, dict(samples=[dict(sample_id=i, co=p) for i, p in zip(['b', 'a'], row['reference_points'])]))
