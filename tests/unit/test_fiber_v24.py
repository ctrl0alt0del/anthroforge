from dataclasses import replace
from pathlib import Path
import ast
import unittest
from unittest.mock import patch

import numpy as np

from core.vcp.v2 import (V2ArrayColliderSnapshot, clear_native_collision_world_cache,
                         clear_triangle_snapshot_cache, clear_v23_route_cache,
                         clear_v24_route_cache, solve_v23, solve_v24)
from core.vcp.v2.collision_native import NativeCollisionWorld, native_batch_status
from tests.unit.test_fiber_v22 import _generated
from tests.unit.test_fiber_v2_solver import _box_request, _clearance


@unittest.skipUnless(native_batch_status(), "native V2.4 batch ABI is unavailable")
class FiberV24Tests(unittest.TestCase):
    def setUp(self):
        clear_native_collision_world_cache(); clear_triangle_snapshot_cache()
        clear_v23_route_cache(); clear_v24_route_cache()

    def test_native_batch_matches_v23_exactly(self):
        request = _array_request(); expected = solve_v23(request)
        self.setUp(); result = solve_v24(request)
        self.assertEqual(result.result.points, expected.result.points)
        self.assertEqual(result.result.termination, expected.result.termination)
        self.assertTrue(result.result.validated); self.assertTrue(_clearance(result, request).valid)

    def test_batch_classifies_closed_and_open_meshes(self):
        closed = _array_request().colliders[0]; open_mesh = _open_collider()
        world, flags = NativeCollisionWorld.from_batch(
            (closed.vertices, open_mesh.vertices), (closed.triangles, open_mesh.triangles), (1, 2))
        self.addCleanup(world.close); self.assertEqual(flags, (True, False))

    def test_batch_rejects_nonfinite_or_invalid_meshes(self):
        vertices = np.asarray(((0, 0, 0), (1, 0, 0), (np.nan, 1, 0)), dtype=np.float64)
        triangles = np.asarray(((0, 1, 3),), dtype=np.int64)
        with self.assertRaises(ValueError):
            NativeCollisionWorld.from_batch((vertices,), (triangles,), (1,))

    def test_one_native_batch_call_builds_the_world(self):
        request = _array_request()
        target = "core.vcp.v2.collision.NativeCollisionWorld.from_batch"
        with patch(target, wraps=NativeCollisionWorld.from_batch) as build:
            result = solve_v24(request)
        self.assertEqual(build.call_count, 1); self.assertTrue(result.trace.native_batch)

    def test_generation_change_invalidates_native_batch_cache(self):
        request = _array_request(); solve_v24(request); collider = request.colliders[0]
        changed = replace(request, token=2, colliders=(replace(collider, generation=("new",)),))
        result = solve_v24(changed)
        self.assertFalse(result.trace.planner_reused); self.assertFalse(result.trace.snapshot_cache_hit)

    def test_array_contract_is_read_only(self):
        collider = _array_request().colliders[0]
        self.assertIsInstance(collider.vertices, np.ndarray)
        self.assertFalse(collider.vertices.flags.writeable)
        with self.assertRaises(ValueError): collider.vertices[0, 0] = 2.0

    def test_v24_has_no_blender_dependency(self):
        path = Path(__file__).parents[2] / "core" / "vcp" / "v2" / "solver_v24.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = [name.name for node in ast.walk(tree) if isinstance(node, ast.Import) for name in node.names]
        self.assertNotIn("bpy", names)


def _array_request():
    request = _generated(_box_request())
    colliders = tuple(V2ArrayColliderSnapshot(row.collider_id, row.owner_id, row.vertices,
                      row.triangles, row.generation) for row in request.colliders)
    return replace(request, colliders=colliders)


def _open_collider():
    vertices = np.asarray(((0, 0, 0), (1, 0, 0), (0, 1, 0)), dtype=np.float64)
    triangles = np.asarray(((0, 1, 2),), dtype=np.int64)
    return V2ArrayColliderSnapshot("open", "open", vertices, triangles, ("g",))


if __name__ == "__main__":
    unittest.main()
