from pathlib import Path
import sys
import unittest

import numpy as np

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path: sys.path.insert(0, value)

from core.vcp.muscle_numeric import (MuscleNumericSpec, execute_muscle_batch,
                                     make_muscle_request)


def _spec(mode, **changes):
    values = dict(target_count=8, densify=True, closed_u=False, close_across_fibers=False,
        topology_flip_normals=False, inflation_enabled=True, inflation_mode=mode,
        inflation_max_value=0.12, inflation_falloff_type="GAUSSIAN",
        inflation_falloff_radius=2.0, inflation_direction_depth=0.3,
        inflation_boundary_strength=0.7, inflation_boundary_band=2.0,
        inflation_boundary_power=1.5, inflation_length_taper_band=0.2,
        closed_v=False, flip_normals=False, control_world=(0.5, 0.5, 0.2))
    values.update(changes); return MuscleNumericSpec(**values)


def _grid(rows=4, columns=8):
    values = [[(j * 0.2, i * 0.5, 0.1 * np.sin(i + j * 0.4)) for j in range(columns)] for i in range(rows)]
    return np.asarray(values, dtype=np.float64)


def _compare(test, mode, **changes):
    request = make_muscle_request("M", _grid(), _spec(mode, **changes))
    python = execute_muscle_batch((request,), "PYTHON").results[0]
    native = execute_muscle_batch((request,), "NATIVE").results[0]
    test.assertTrue(np.array_equal(python.faces, native.faces))
    test.assertLess(float(np.max(np.abs(python.base_vertices - native.base_vertices))), 1.0e-7)
    test.assertLess(float(np.max(np.abs(python.inflated_vertices - native.inflated_vertices))), 1.0e-6)


class MuscleNumericBackendTests(unittest.TestCase):
    def test_distributed_matches_python_reference(self):
        _compare(self, "DISTRIBUTED")

    def test_control_point_matches_python_reference(self):
        _compare(self, "CTRL_POINT", densify=False, topology_flip_normals=True)

    def test_zero_control_matches_python_reference(self):
        _compare(self, "CTRL_POINT", control_world=(0.0, 0.0, 0.0), initialize_control=True)

    def test_authored_origin_matches_python_without_initialization(self):
        _compare(self, "CTRL_POINT", control_world=(0.0, 0.0, 0.0), initialize_control=False)

    def test_offcentre_control_matches_python_without_initialization(self):
        _compare(self, "CTRL_POINT", control_world=(1.13, 0.77, 0.03), initialize_control=False)

    def test_closed_surface_matches_python_reference(self):
        _compare(self, "DISTRIBUTED", closed_u=True, close_across_fibers=True, closed_v=True)


if __name__ == "__main__":
    unittest.main()
