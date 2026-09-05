from pathlib import Path
import json
import sys
from types import SimpleNamespace
from unittest.mock import patch

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy

from _helpers import BlenderTestCase, capture_world_attachment, mesh_object, root, scp_with_object
from anthroforge.app.queries.action_library import quick_fiber_panel_state
from anthroforge.app.use_cases.action_library_quick_fiber import QuickFiberPoint, commit_quick_fiber
from anthroforge.core.visualization.fiber_refinement import (
    RefinementRequest,
    drain_fiber_refinements,
    fiber_refinement_state,
)
from anthroforge.core.vcp.runtime_state import fiber_eps_pen
from anthroforge.operators import action_library_quick_fiber as modal_ops


def _point(root_obj, scp, vertex=0):
    obj = scp.geometry_object_ref
    world = obj.matrix_world @ obj.data.vertices[int(vertex)].co
    raw = capture_world_attachment(root_obj, scp.id, world)
    return QuickFiberPoint(scp.id, raw, world.copy(), world.copy(), scp.name)


def _view_context(area_type="VIEW_3D"):
    return SimpleNamespace(scene=bpy.context.scene, view_layer=bpy.context.view_layer,
                           area=SimpleNamespace(type=area_type))


class QuickFiberTests(BlenderTestCase):
    def test_panel_requires_view3d_root_and_visible_surface(self):
        self.assertFalse(quick_fiber_panel_state(_view_context()).can_create)
        root_obj = root()
        scp = scp_with_object(root_obj, "Surface", mesh_object("Surface"))
        self.assertFalse(quick_fiber_panel_state(_view_context("PROPERTIES")).can_create)
        self.assertTrue(quick_fiber_panel_state(_view_context()).can_create)
        scp.geometry_object_ref.hide_set(True)
        self.assertFalse(quick_fiber_panel_state(_view_context()).can_create)

    def test_commit_creates_guided_preview_then_refines_exact_count(self):
        root_obj = root()
        origin = scp_with_object(root_obj, "Origin", mesh_object("Origin"))
        guide = scp_with_object(root_obj, "Guide", mesh_object("Guide", (1.0, 1.0, 0.0)))
        insert = scp_with_object(root_obj, "Insert", mesh_object("Insert", (2.0, 0.0, 0.0)))
        result = commit_quick_fiber(bpy.context, (_point(root_obj, origin), _point(root_obj, guide), _point(root_obj, insert)))
        self.assertTrue(result.ok)
        fiber, proxy = result.value.fiber, result.value.proxy
        self.assertEqual((len(fiber.mid_touches), fiber.mid_touches[0].parent_id), (1, guide.id))
        self.assertEqual(fiber_refinement_state(bpy.context.scene, fiber.id), "REFINING")
        self.assertNotIn("af_fiber_points_world", proxy)
        self.assertLess(len(proxy.data.splines[0].points), fiber.node_count)
        self.assertTrue(drain_fiber_refinements())
        self.assertTrue(fiber.use_segment_collisions)
        self.assertLess(fiber_eps_pen(fiber), 1.0e-5)
        self.assertEqual(len(json.loads(proxy["af_fiber_points_world"])), fiber.node_count)
        self.assertEqual(len(proxy.data.splines[0].points), fiber.node_count)
        self.assertEqual((bpy.context.active_object, tuple(bpy.context.selected_objects)), (proxy, (proxy,)))

    def test_commit_rolls_back_fiber_and_runtime_objects_on_preview_failure(self):
        root_obj = root()
        origin = scp_with_object(root_obj, "Origin", mesh_object("Origin"))
        insert = scp_with_object(root_obj, "Insert", mesh_object("Insert", (2.0, 0.0, 0.0)))
        failed = RefinementRequest(False, "No safe route")
        with patch("anthroforge.app.use_cases.action_library_quick_fiber.request_fiber_refinement", return_value=failed):
            result = commit_quick_fiber(bpy.context, (_point(root_obj, origin), _point(root_obj, insert)))
        self.assertFalse(result.ok)
        self.assertEqual(len(root_obj.af_vcp_system.fibers), 0)
        self.assertFalse(any(obj.get("af_fiber_proxy") for obj in bpy.context.scene.objects))

    def test_quick_fiber_requests_interactive_quality(self):
        root_obj = root()
        origin = scp_with_object(root_obj, "Origin", mesh_object("Origin"))
        insert = scp_with_object(root_obj, "Insert", mesh_object("Insert", (2.0, 0.0, 0.0)))
        failed = RefinementRequest(False, "stop")
        with patch("anthroforge.app.use_cases.action_library_quick_fiber.request_fiber_refinement",
                   return_value=failed) as request:
            commit_quick_fiber(bpy.context, (_point(root_obj, origin), _point(root_obj, insert)))
        self.assertEqual(request.call_args.kwargs["quality"], "INTERACTIVE")

    def test_modal_backspace_navigation_and_coincident_rejection(self):
        point = QuickFiberPoint("S1", "raw", bpy.context.scene.cursor.location.copy(),
                                bpy.context.scene.cursor.location.copy(), "Surface")
        operator = SimpleNamespace(_quick_fiber_points=[point, point], _quick_fiber_hover=None,
                                   _quick_fiber_armed=True)
        self.assertTrue(modal_ops._point_rejected(operator, point))
        modal_ops._remove_last(operator, bpy.context)
        self.assertEqual(operator._quick_fiber_points, [point])
        event = SimpleNamespace(type="MIDDLEMOUSE", value="PRESS")
        self.assertEqual(modal_ops.modal_quick_fiber(operator, bpy.context, event), {"PASS_THROUGH"})

    def test_successful_modal_commit_finishes_and_schedules_relaunch(self):
        operator = SimpleNamespace(_quick_fiber_points=[])
        insertion, scheduled = SimpleNamespace(), []
        result = SimpleNamespace(ok=True, level="INFO", message="")
        with patch.object(modal_ops, "commit_quick_fiber", return_value=result):
            with patch.object(modal_ops, "_relaunch_spec", return_value=("Scene", 1, 2, 3)):
                with patch.object(modal_ops, "_end_modal"):
                    with patch.object(modal_ops, "_schedule_relaunch", side_effect=scheduled.append):
                        status = modal_ops._commit(operator, bpy.context, insertion)
        self.assertEqual(status, {"FINISHED"})
        self.assertEqual(scheduled, [("Scene", 1, 2, 3)])


if __name__ == "__main__":
    import unittest
    unittest.main()
