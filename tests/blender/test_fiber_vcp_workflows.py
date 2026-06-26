from pathlib import Path
import sys
import json
from unittest.mock import patch

import bmesh

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy
from mathutils import Vector

from _helpers import BlenderTestCase, empty_object, find_flagged, mesh_object, root, scp_with_object, select_only
from anthroforge.core.attachment_codec import encode_fiber_mesh_anchor
from anthroforge.core.vcp.runtime_state import (
    fiber_active_colliders,
    fiber_planner_ms,
    fiber_recompute_ms,
    fiber_recompute_status,
    fiber_refine_ms,
    fiber_route_mode,
    set_fiber_eps_disp,
    set_fiber_eps_pen,
    set_fiber_recompute_ms,
    set_fiber_recompute_status,
)
from anthroforge.core.visualization import fiber_sync_runtime as fiber_runtime
from anthroforge.core.visualization.fiber_sync import register_fiber_sync
from anthroforge.core.visualization.fiber_sync_helpers import endpoint_world, mark_endpoint_handle, mark_touch_handle


def _fiber_setup():
    root_obj = root()
    origin = scp_with_object(root_obj, "Origin", mesh_object("Origin"))
    insert = scp_with_object(root_obj, "Insert", mesh_object("Insert", (2.0, 0.0, 0.0)))
    bpy.context.scene.af_new_fiber_origin_obj = origin.geometry_object_ref
    bpy.context.scene.af_new_fiber_insertion_obj = insert.geometry_object_ref
    bpy.ops.af.add_fiber_vcp()
    return root_obj, root_obj.af_vcp_system.fibers[0], origin, insert


def _fiber_setup_direct():
    root_obj = root()
    origin_obj = mesh_object("Origin")
    insert_obj = mesh_object("Insert", (2.0, 0.0, 0.0))
    origin_obj.rotation_euler.y = 1.57079632679
    insert_obj.rotation_euler.y = 1.57079632679
    origin = scp_with_object(root_obj, "Origin", origin_obj)
    insert = scp_with_object(root_obj, "Insert", insert_obj)
    bpy.context.scene.af_new_fiber_origin_obj = origin.geometry_object_ref
    bpy.context.scene.af_new_fiber_insertion_obj = insert.geometry_object_ref
    bpy.ops.af.add_fiber_vcp()
    return root_obj, root_obj.af_vcp_system.fibers[0], origin, insert


def _clear_selection():
    for obj in tuple(bpy.context.selected_objects):
        obj.select_set(False)
    bpy.context.view_layer.objects.active = None


def _sync_active_fiber(root_obj, fiber):
    _clear_selection()
    with patch.object(fiber_runtime, "_active_fiber_id", return_value=fiber.id):
        register_fiber_sync().sync_root_to_scene(root=root_obj, scene=bpy.context.scene)


def _cube_scp(root_obj, name, location=(0.0, 0.0, 0.0), size=1.0):
    bpy.ops.mesh.primitive_cube_add(size=size, location=location)
    return scp_with_object(root_obj, name, bpy.context.active_object), bpy.context.active_object


def _fiber_points_world(fiber):
    proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
    return json.loads(proxy["af_fiber_points_world"])


def _edit_select_vertex(obj, *indices):
    select_only(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    for vert in bm.verts:
        vert.select_set(False)
    bm.select_history.clear()
    for index in indices:
        _select_edit_vert(bm, index)
    bmesh.update_edit_mesh(obj.data)


def _select_edit_vert(bm, index):
    vert = bm.verts[int(index)]
    vert.select_set(True)
    bm.select_history.add(vert)


def _handle_count(fiber_id):
    return sum(bool(obj.get("af_fiber_id") == fiber_id and (obj.get("af_fiber_endpoint_handle") or obj.get("af_fiber_touch_handle"))) for obj in bpy.context.scene.objects)


class FiberVcpWorkflowTests(BlenderTestCase):
    def test_add_fiber_operator_selects_proxy_and_shows_endpoint_handles(self):
        root_obj, fiber, origin, insert = _fiber_setup()
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        count = sum(bool(obj.get("af_fiber_endpoint_handle") and obj.get("af_fiber_id") == fiber.id) for obj in bpy.context.scene.objects)
        self.assertEqual((fiber.a_parent_id, fiber.b_parent_id, proxy is not None), (origin.id, insert.id, True))
        self.assertEqual((bpy.context.active_object, count), (proxy, 2))

    def test_add_fiber_operator_creates_proxy_and_endpoint_handles(self):
        root_obj, fiber, origin, insert = _fiber_setup()
        _sync_active_fiber(root_obj, fiber)
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        count = sum(bool(obj.get("af_fiber_endpoint_handle") and obj.get("af_fiber_id") == fiber.id) for obj in bpy.context.scene.objects)
        self.assertEqual((fiber.a_parent_id, fiber.b_parent_id, proxy is not None), (origin.id, insert.id, True))
        self.assertEqual((bool(fiber.a_attach_param), bool(fiber.b_attach_param), count), (True, True, 2))

    def test_touch_tools_and_clear_warm_start_update_runtime_fields(self):
        root_obj, fiber, origin, _insert = _fiber_setup()
        select_only(origin.geometry_object_ref)
        self.assertEqual(bpy.ops.af.add_fiber_touch_point(), {"FINISHED"})
        set_fiber_recompute_status(fiber, "CONVERGED")
        set_fiber_recompute_ms(fiber, 9.0)
        set_fiber_eps_disp(fiber, 3.0)
        set_fiber_eps_pen(fiber, 4.0)
        bpy.ops.af.clear_fiber_warm_start()
        self.assertEqual((fiber_recompute_status(fiber), fiber_recompute_ms(fiber)), ("UNKNOWN", 0.0))
        bpy.ops.af.remove_fiber_touch_point(touch_index=0)
        self.assertEqual(len(fiber.mid_touches), 0)

    def test_add_fiber_touch_point_uses_selected_geometry_vertex(self):
        root_obj, fiber, origin, _insert = _fiber_setup()
        _edit_select_vertex(origin.geometry_object_ref, 1)
        self.assertEqual(bpy.ops.af.add_fiber_touch_point(fiber_id=fiber.id), {"FINISHED"})
        self.assertEqual((len(fiber.mid_touches), fiber.mid_touches[0].parent_id), (1, origin.id))
        target = origin.geometry_object_ref.matrix_world @ origin.geometry_object_ref.data.vertices[1].co
        actual = endpoint_world(root_obj, bpy.context.scene, {}, fiber.mid_touches[0].parent_id, fiber.mid_touches[0].attach_param)
        self.assertLess((actual - target).length, 1.0e-6)

    def test_recompute_fiber_sets_status_and_elapsed_time(self):
        _root_obj, fiber, _origin, _insert = _fiber_setup()
        bpy.ops.af.recompute_fiber()
        self.assertIn(fiber_recompute_status(fiber), {"CONVERGED", "NOT_CONVERGED"})
        self.assertGreaterEqual(fiber_recompute_ms(fiber), 0.0)

    def test_recompute_fiber_preserves_requested_node_count(self):
        _root_obj, fiber, _origin, _insert = _fiber_setup()
        fiber.node_count = 96
        bpy.ops.af.recompute_fiber()
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        self.assertEqual(len(json.loads(proxy["af_fiber_points_world"])), 96)

    def test_recompute_fiber_direct_mode_records_planner_metrics(self):
        _root_obj, fiber, _origin, _insert = _fiber_setup_direct()
        bpy.ops.af.recompute_fiber()
        self.assertEqual(fiber_route_mode(fiber), "DIRECT")
        self.assertGreaterEqual(fiber_planner_ms(fiber), 0.0)
        self.assertGreaterEqual(fiber_refine_ms(fiber), 0.0)

    def test_recompute_fiber_roadmap_mode_detours_around_blocker(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        _cube_scp(root_obj, "Blocker", (1.0, 0.0, 0.0), 0.8)
        bpy.ops.af.recompute_fiber()
        points = _fiber_points_world(fiber)
        self.assertEqual(fiber_route_mode(fiber), "ROADMAP")
        self.assertTrue(any(abs(p[1]) > 1.0e-4 or abs(p[2]) > 1.0e-4 for p in points[1:-1]))

    def test_interactive_sync_skips_roadmap_planner(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        _cube_scp(root_obj, "Blocker", (1.0, 0.0, 0.0), 0.8)
        register_fiber_sync().sync_root_to_scene(root=root_obj, scene=bpy.context.scene, bake=False)
        self.assertEqual(fiber_route_mode(fiber), "LOCAL_FALLBACK")
        self.assertEqual(fiber_planner_ms(fiber), 0.0)

    def test_recompute_fiber_preserves_mid_touch_anchor(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        blocker, blocker_obj = _cube_scp(root_obj, "TouchBlocker", (1.0, 0.0, 0.0), 0.8)
        target_local = Vector((0.0, 0.0, 0.4))
        touch = fiber.mid_touches.add()
        touch.parent_id = blocker.id
        touch.attach_param = encode_fiber_mesh_anchor(target_local)
        bpy.ops.af.recompute_fiber()
        target_world = blocker_obj.matrix_world @ target_local
        points = [Vector(value) for value in _fiber_points_world(fiber)]
        self.assertLess(min((point - target_world).length for point in points), 1.0e-6)

    def test_recompute_fiber_active_collider_metric_filters_far_blockers(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        for i in range(8):
            _cube_scp(root_obj, f"Far{i}", (20.0, float(i) * 2.0, 0.0), 0.8)
        bpy.ops.af.recompute_fiber()
        self.assertLess(fiber_active_colliders(fiber), 5)

    def test_new_fiber_defaults_warm_start_on(self):
        _root_obj, fiber, _origin, _insert = _fiber_setup()
        self.assertTrue(hasattr(fiber, "use_warm_start"))
        self.assertTrue(fiber.use_warm_start)

    def test_endpoint_handle_update_uses_conflict_resolution(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        _sync_active_fiber(root_obj, fiber)
        sync = register_fiber_sync()
        handle = mark_endpoint_handle(empty_object("Endpoint"), root_obj, fiber.id, "A")
        with patch.object(fiber_runtime, "resolve_conflict", return_value="ENDPOINT_RAW"):
            fiber_runtime.apply_fiber_control_update(sync, root_obj, bpy.context.scene, handle, bpy.context.evaluated_depsgraph_get())
        self.assertEqual(fiber.a_attach_param, "ENDPOINT_RAW")

    def test_touch_handle_update_uses_conflict_resolution(self):
        root_obj, fiber, origin, _insert = _fiber_setup()
        select_only(origin.geometry_object_ref)
        bpy.ops.af.add_fiber_touch_point()
        _sync_active_fiber(root_obj, fiber)
        sync = register_fiber_sync()
        handle = mark_touch_handle(empty_object("Touch"), root_obj, fiber.id, 0)
        with patch.object(fiber_runtime, "resolve_conflict", return_value="TOUCH_RAW"):
            fiber_runtime.apply_fiber_control_update(sync, root_obj, bpy.context.scene, handle, bpy.context.evaluated_depsgraph_get())
        self.assertEqual(fiber.mid_touches[0].attach_param, "TOUCH_RAW")

    def test_delete_fiber_in_tree_removes_proxy_and_handles(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        _sync_active_fiber(root_obj, fiber)
        self.assertEqual(bpy.ops.af.delete_vcp_in_tree(node_id=fiber.id, node_type="FIBER"), {"FINISHED"})
        self.assertEqual((len(root_obj.af_vcp_system.fibers), find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")), (0, None))
        self.assertEqual((root_obj.af_vcp_system.active_vcp_type, _handle_count(fiber.id)), ("NONE", 0))
