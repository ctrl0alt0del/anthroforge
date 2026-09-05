from dataclasses import replace
from pathlib import Path
import ast
import unittest
from unittest.mock import patch

import numpy as np

from core.vcp.v2 import (V2ColliderSnapshot, clear_native_collision_world_cache,
                         clear_triangle_snapshot_cache, clear_v23_route_cache,
                         solve_v22, solve_v23)
from tests.unit.test_fiber_v22 import _generated
from tests.unit.test_fiber_v2_solver import _box_request, _clearance


class FiberV23Tests(unittest.TestCase):
    def setUp(self):
        clear_v23_route_cache(); clear_triangle_snapshot_cache()
        clear_native_collision_world_cache()

    def test_shared_world_matches_v22_output(self):
        request = _generated(_box_request()); expected = solve_v22(request)
        self.setUp(); result = solve_v23(request)
        self.assertEqual(result.result.points, expected.result.points)
        self.assertEqual(result.result.termination, expected.result.termination)
        self.assertTrue(result.result.validated); self.assertTrue(_clearance(result, request).valid)

    def test_one_world_lookup_serves_entire_solve(self):
        request = _generated(_box_request())
        target = "core.vcp.v2.solver_v23.cached_native_collision_world"
        from core.vcp.v2.solver_v23 import cached_native_collision_world as real
        with patch(target, wraps=real) as lookup: result = solve_v23(request)
        self.assertEqual(lookup.call_count, 1); self.assertTrue(result.trace.shared_world)

    def test_closedness_is_computed_once_per_collider(self):
        request = _generated(_box_request())
        with patch("core.vcp.v2.collision._closed_mesh", wraps=_closed_mesh()) as closed:
            result = solve_v23(request)
        self.assertEqual(closed.call_count, len(request.colliders))
        self.assertEqual(result.trace.topology_entries, len(request.colliders))

    def test_array_collider_uses_vectorized_contract_path(self):
        vertices = np.asarray(((0, 0, 0), (1, 0, 0), (0, 1, 0)), dtype=np.float64)
        triangles = np.asarray(((0, 1, 2),), dtype=np.int64)
        with patch("core.vcp.v2.contracts._vec3", side_effect=AssertionError("scalar path")):
            collider = V2ColliderSnapshot("C", "O", vertices, triangles, ("g",))
        self.assertEqual(collider.vertices[1], (1.0, 0.0, 0.0))

    def test_generation_change_invalidates_v23_route(self):
        request = _generated(_box_request()); solve_v23(request); collider = request.colliders[0]
        changed = replace(request, token=2, colliders=(replace(collider, generation=("new",)),))
        result = solve_v23(changed)
        self.assertFalse(result.trace.planner_reused); self.assertFalse(result.trace.snapshot_cache_hit)

    def test_v23_has_no_blender_dependency(self):
        path = Path(__file__).parents[2] / "core" / "vcp" / "v2" / "solver_v23.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = [name.name for node in ast.walk(tree) if isinstance(node, ast.Import) for name in node.names]
        self.assertNotIn("bpy", names)


def _closed_mesh():
    from core.vcp.v2.collision import _closed_mesh as value
    return value


if __name__ == "__main__":
    unittest.main()
