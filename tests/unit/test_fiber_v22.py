from dataclasses import replace
from pathlib import Path
import ast
import unittest
from unittest.mock import patch

from core.vcp.v2 import (V2Request, clear_triangle_snapshot_cache, clear_v22_route_cache,
                         solve_package61, solve_v22, triangle_snapshot_cache_stats,
                         v22_request_signature, v22_snapshot_key)
from tests.unit.test_fiber_v2_solver import (_bent_request, _box_request,
                                              _clearance, _sphere_request)


def _generated(request):
    rows = tuple(replace(item, generation=("fixture", str(index)))
                 for index, item in enumerate(request.colliders))
    return replace(request, colliders=rows)


def _moved_middle(request):
    anchors = list(request.anchors); point = anchors[1].point
    anchors[1] = replace(anchors[1], point=(point[0], point[1] + .001, point[2]))
    return replace(request, token=2, anchors=tuple(anchors))


class FiberV22Tests(unittest.TestCase):
    def setUp(self):
        clear_v22_route_cache(); clear_triangle_snapshot_cache()

    def test_compact_signature_does_not_serialize_geometry(self):
        request = _generated(_box_request())
        with patch.object(V2Request, "signature", side_effect=AssertionError("full signature")):
            self.assertEqual(len(v22_request_signature(request)), 64)

    def test_missing_generation_falls_back_to_full_signature(self):
        request = _box_request()
        with patch.object(V2Request, "signature", wraps=request.signature) as full:
            self.assertEqual(len(v22_request_signature(request)), 64)
        self.assertEqual(full.call_count, 1); self.assertFalse(v22_snapshot_key(request))

    def test_persistent_snapshot_is_reused(self):
        request = _generated(_box_request()); first = solve_v22(request); second = solve_v22(request)
        self.assertFalse(first.trace.snapshot_cache_hit); self.assertTrue(second.trace.snapshot_cache_hit)
        self.assertEqual(triangle_snapshot_cache_stats()["entries"], 1)

    def test_two_fibers_share_one_snapshot_generation(self):
        request = _generated(_box_request()); solve_v22(request)
        second = solve_v22(replace(request, token=2, source_revision="OTHER_FIBER"))
        self.assertTrue(second.trace.snapshot_cache_hit)
        self.assertEqual(triangle_snapshot_cache_stats(), {"entries": 1, "hits": 1, "misses": 1})

    def test_baseline_matches_package61(self):
        request = _generated(_box_request()); expected = solve_package61(request); result = solve_v22(request)
        self.assertEqual(result.result.points, expected.result.points)
        self.assertTrue(result.result.validated); self.assertTrue(_clearance(result, request).valid)

    def test_property_change_reuses_non_surface_final(self):
        request = _generated(_bent_request()); solve_v22(request)
        settings = replace(request.settings, curvature_weight=request.settings.curvature_weight * 1.1)
        result = solve_v22(replace(request, token=2, settings=settings))
        self.assertTrue(result.trace.planner_reused); self.assertEqual(result.trace.planner_full_runs, 0)

    def test_surface_property_change_requires_fresh_plan(self):
        request = _generated(_sphere_request()); settings = replace(
            request.settings, curvature_weight=request.settings.curvature_weight * 1.1)
        with patch("core.vcp.v2.solver_v22._wide_direct", return_value=False):
            solve_v22(request); result = solve_v22(replace(request, token=2, settings=settings))
        self.assertFalse(result.trace.planner_reused); self.assertGreater(result.trace.planner_full_runs, 0)

    def test_preview_warp_requires_fresh_final(self):
        request = _generated(_bent_request()); solve_v22(request); changed = _moved_middle(request)
        preview = solve_v22(changed, preview=True); final = solve_v22(changed)
        self.assertTrue(preview.trace.preview_warp); self.assertFalse(preview.trace.fresh_planner)
        self.assertTrue(final.trace.final_refresh); self.assertTrue(final.trace.fresh_planner)

    def test_generation_change_invalidates_snapshot_and_route(self):
        request = _generated(_box_request()); solve_v22(request); item = request.colliders[0]
        changed = replace(request, token=2, colliders=(replace(item, generation=("fixture", "new")),))
        result = solve_v22(changed)
        self.assertFalse(result.trace.planner_reused); self.assertFalse(result.trace.snapshot_cache_hit)

    def test_v22_has_no_blender_dependency(self):
        path = Path(__file__).parents[2] / "core" / "vcp" / "v2" / "solver_v22.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = [name.name for node in ast.walk(tree) if isinstance(node, ast.Import) for name in node.names]
        self.assertNotIn("bpy", names)


if __name__ == "__main__":
    unittest.main()
