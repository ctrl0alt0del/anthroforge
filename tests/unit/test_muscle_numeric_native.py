import unittest

import numpy as np

from core.vcp.muscle_numeric import MuscleNumericSpec, make_muscle_request, resolve_muscle_backend
from core.vcp.muscle_numeric_native import execute_native_muscle_batch, native_muscle_status
from core.vcp.v2.collision_native import load_native


def _spec(**changes):
    values = dict(target_count=3, densify=False, closed_u=False, close_across_fibers=False,
        topology_flip_normals=False, inflation_enabled=False, inflation_mode="DISTRIBUTED",
        inflation_max_value=0.05, inflation_falloff_type="GAUSSIAN",
        inflation_falloff_radius=0.2, inflation_direction_depth=0.05,
        inflation_boundary_strength=0.7, inflation_boundary_band=2.0,
        inflation_boundary_power=1.5, inflation_length_taper_band=0.2,
        closed_v=False, flip_normals=False, control_world=(0.0, 0.0, 0.0))
    values.update(changes); return MuscleNumericSpec(**values)


def _points(rows=2, columns=3):
    return np.asarray([[(float(j), float(i), 0.0) for j in range(columns)]
                       for i in range(rows)], dtype=np.float64)


class MuscleNumericNativeTests(unittest.TestCase):
    def test_native_backend_is_packaged(self):
        self.assertTrue(native_muscle_status())

    def test_uninflated_grid_and_topology_are_exact(self):
        request = make_muscle_request("M", _points(), _spec())
        result = execute_native_muscle_batch((request,)).results[0]
        self.assertTrue(np.array_equal(result.base_vertices, result.inflated_vertices))
        self.assertEqual((result.row_count, result.column_count, result.faces.tolist()),
                         (2, 3, [[0, 3, 4, 1], [1, 4, 5, 2]]))

    def test_parallel_batch_preserves_indexed_results(self):
        requests = tuple(make_muscle_request(str(i), _points(8, 64), _spec(target_count=64)) for i in range(12))
        batch = execute_native_muscle_batch(requests)
        self.assertEqual(tuple(row.muscle_id for row in batch.results), tuple(str(i) for i in range(12)))
        self.assertTrue(batch.parallel); self.assertEqual(batch.workers, 4)

    def test_openmp_matches_serial_bitwise(self):
        requests = tuple(make_muscle_request(str(i), _points(8, 64), _spec(target_count=64)) for i in range(12))
        library = load_native(); original = library.af_fiber_worker_threads()
        try:
            library.af_fiber_set_worker_threads(1); serial = execute_native_muscle_batch(requests)
            library.af_fiber_set_worker_threads(4); parallel = execute_native_muscle_batch(requests)
        finally: library.af_fiber_set_worker_threads(original)
        for first, second in zip(serial.results, parallel.results):
            self.assertTrue(np.array_equal(first.base_vertices, second.base_vertices))
            self.assertTrue(np.array_equal(first.inflated_vertices, second.inflated_vertices))

    def test_backend_selector(self):
        self.assertEqual(resolve_muscle_backend(environment={}).value, "NATIVE")
        self.assertEqual(resolve_muscle_backend(environment={"AF_MUSCLE_NUMERIC_BACKEND": "NATIVE"}).value, "NATIVE")
        with self.assertRaises(ValueError): resolve_muscle_backend(environment={"AF_MUSCLE_NUMERIC_BACKEND": "CUDA"})


if __name__ == "__main__":
    unittest.main()
