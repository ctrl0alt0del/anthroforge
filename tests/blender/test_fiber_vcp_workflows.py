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

from _helpers import BlenderTestCase, capture_mesh_attachment, capture_world_attachment, empty_object, find_flagged, mesh_object, root, scp_with_object, select_only
from anthroforge.app.use_cases.fiber_tools import recompute_fiber as recompute_fiber_action
from anthroforge.core.attachment_codec import encode_fiber_mesh_anchor, encode_fiber_shape_param, encode_fiber_vertex_index, parse_fiber_attach_param
from anthroforge.core.vcp.fiber_solver import FiberSolver
from anthroforge.core.vcp.runtime_state import (
    fiber_active_colliders,
    fiber_invalid_reason,
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
from anthroforge.core.visualization.fiber_sync_helpers import endpoint_world, mark_endpoint_handle, mark_touch_handle, touch_world


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


def _touch_handle(fiber_id, index=0):
    return next(obj for obj in bpy.context.scene.objects if obj.get("af_fiber_touch_handle") and obj.get("af_fiber_id") == fiber_id and int(obj.get("af_fiber_touch_index", -1)) == index)


def _loop_mesh_object(name, location=(0.0, 0.0, 0.0)):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    return obj


def _loop_setup():
    root_obj = root()
    loop = scp_with_object(root_obj, "Loop", _loop_mesh_object("Loop"))
    _edit_select_vertex(loop.geometry_object_ref, 0, 1, 2, 3)
    bpy.ops.af.create_loop_fiber_from_selected_vertices()
    return root_obj, root_obj.af_vcp_system.fibers[0], loop


def _fiber_world_vectors(fiber):
    return [Vector(value) for value in _fiber_points_world(fiber)]


def _point_in_box(point, center, half_extent):
    return all(abs(point[i] - center[i]) < float(half_extent) for i in range(3))


def _polyline_hits_box(points, center, half_extent, steps=6):
    for i in range(len(points) - 1):
        for step in range(steps + 2):
            point = points[i].lerp(points[i + 1], step / float(steps + 1))
            if _point_in_box(point, center, half_extent):
                return True
    return False


def _rollback_hit(point):
    return abs(point.x - 1.0) < 0.2 and abs(point.z) < 0.05


class _RollbackOracle:
    def push_out_point(self, point, colliders):
        _ = colliders
        return point.copy(), 1.0 if _rollback_hit(point) else 0.0


def _sticky_hit(point):
    return abs(point.x - 1.0) < 0.2 and abs(point.z) < 0.07


class _StickyRollbackOracle:
    def push_out_point(self, point, colliders):
        _ = colliders
        return point.copy(), 1.0 if _sticky_hit(point) else 0.0


class FiberVcpWorkflowTests(BlenderTestCase):
    def test_fiber_proxy_object_color_matches_material(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        register_fiber_sync().sync_root_to_scene(root=root_obj, scene=bpy.context.scene)
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        want = tuple(round(float(v), 4) for v in proxy.data.materials[0].diffuse_color)
        self.assertEqual(tuple(round(float(v), 4) for v in proxy.color), want)

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
        self.assertEqual(parse_fiber_attach_param(fiber.mid_touches[0].attach_param)[0], "surface_param_v2")
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

    def test_interactive_planner_preview_renders_raw_planner_route(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        fiber.preview_planner_route = True
        _cube_scp(root_obj, "Blocker", (1.0, 0.0, 0.0), 0.8)
        register_fiber_sync().sync_root_to_scene(root=root_obj, scene=bpy.context.scene, bake=False)
        points = _fiber_world_vectors(fiber)
        a_world = endpoint_world(root_obj, bpy.context.scene, {}, fiber.a_parent_id, fiber.a_attach_param)
        b_world = endpoint_world(root_obj, bpy.context.scene, {}, fiber.b_parent_id, fiber.b_attach_param)
        self.assertEqual(fiber_route_mode(fiber), "ROADMAP")
        self.assertGreater(fiber_planner_ms(fiber), 0.0)
        self.assertLess(len(points), fiber.node_count)
        self.assertLess((points[0] - a_world).length, 1.0e-6)
        self.assertLess((points[-1] - b_world).length, 1.0e-6)
        self.assertTrue(any(abs(p.y) > 1.0e-4 or abs(p.z) > 1.0e-4 for p in points[1:-1]))

    def test_segment_collision_toggle_catches_thin_blocker_in_interactive_mode(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        fiber.node_count, fiber.iterations_interactive = 8, 20
        _cube_scp(root_obj, "ThinBlocker", (1.0, 0.0, 0.0), 0.1)
        sync = register_fiber_sync()
        sync.clear_solver_cache(fiber.id)
        sync.sync_root_to_scene(root=root_obj, scene=bpy.context.scene, bake=False)
        points_off = _fiber_world_vectors(fiber)
        fiber.use_segment_collisions = True
        sync.clear_solver_cache(fiber.id)
        sync.sync_root_to_scene(root=root_obj, scene=bpy.context.scene, bake=False)
        points_on = _fiber_world_vectors(fiber)
        self.assertTrue(_polyline_hits_box(points_off, Vector((1.0, 0.0, 0.0)), 0.05))
        self.assertFalse(_polyline_hits_box(points_on, Vector((1.0, 0.0, 0.0)), 0.05))

    def test_segment_collision_rollback_restores_i_plus_one_node(self):
        prev = [Vector((0.0, 0.0, 0.0)), Vector((0.7, 0.0, 0.08)), Vector((1.3, 0.0, 0.08)), Vector((2.0, 0.0, 0.0))]
        nodes = [point.copy() for point in prev]
        params = {"shorten_strength": 1.0, "bend_strength": 0.0, "margin": 0.0, "segment_collisions": True}
        FiberSolver()._solver_iteration(nodes, [point.copy() for point in prev], [True, False, False, True], {0: prev[0], 3: prev[3]}, _RollbackOracle(), (), params, 0)
        self.assertLess(nodes[1].z, prev[1].z)
        self.assertEqual(tuple(round(v, 4) for v in nodes[2]), tuple(round(v, 4) for v in prev[2]))

    def test_segment_collision_fallback_restores_last_clear_state(self):
        prev = [Vector((0.0, 0.0, 0.0)), Vector((0.7, 0.0, 0.08)), Vector((1.3, 0.0, 0.08)), Vector((2.0, 0.0, 0.0))]
        nodes = [point.copy() for point in prev]
        params = {"shorten_strength": 1.0, "bend_strength": 0.0, "margin": 0.0, "segment_collisions": True, "iterations": 1, "min_iters": 0, "eps_disp": 0.0, "eps_pen": 0.0}
        FiberSolver()._run_iterations(nodes, [point.copy() for point in prev], [True, False, False, True], {0: prev[0], 3: prev[3]}, _StickyRollbackOracle(), (), params)
        self.assertEqual([tuple(round(v, 4) for v in point) for point in nodes], [tuple(round(v, 4) for v in point) for point in prev])

    def test_recompute_fiber_preserves_mid_touch_anchor(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        blocker, blocker_obj = _cube_scp(root_obj, "TouchBlocker", (1.0, 0.0, 0.0), 0.8)
        target_local = Vector((0.0, 0.0, 0.4))
        touch = fiber.mid_touches.add()
        touch.parent_id = blocker.id
        touch.attach_param = capture_world_attachment(root_obj, blocker.id, blocker_obj.matrix_world @ target_local)
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
        self.assertTrue(hasattr(fiber, "use_segment_collisions"))
        self.assertFalse(fiber.use_segment_collisions)
        self.assertTrue(hasattr(fiber, "preview_planner_route"))
        self.assertFalse(fiber.preview_planner_route)

    def test_new_fiber_defaults_remove_legacy_solver_knobs(self):
        _root_obj, fiber, _origin, _insert = _fiber_setup()
        self.assertFalse(hasattr(fiber, "collision_margin"))
        self.assertFalse(hasattr(fiber, "damping"))
        self.assertFalse(hasattr(fiber, "guide_stiffness"))

    def test_default_touch_captures_surface_param_and_zero_offset(self):
        root_obj, fiber, origin, _insert = _fiber_setup()
        select_only(origin.geometry_object_ref)
        self.assertEqual(bpy.ops.af.add_fiber_touch_point(fiber_id=fiber.id), {"FINISHED"})
        touch = fiber.mid_touches[0]
        self.assertEqual((touch.normal_offset, parse_fiber_attach_param(touch.attach_param)[0]), (0.0, "surface_param_v2"))

    def test_vertex_touch_offset_lifts_solver_pin(self):
        root_obj, fiber, origin, _insert = _fiber_setup()
        _edit_select_vertex(origin.geometry_object_ref, 1)
        self.assertEqual(bpy.ops.af.add_fiber_touch_point(fiber_id=fiber.id), {"FINISHED"})
        touch = fiber.mid_touches[0]
        touch.normal_offset = 0.25
        target = origin.geometry_object_ref.matrix_world @ origin.geometry_object_ref.data.vertices[1].co
        lifted = touch_world(root_obj, bpy.context.scene, {}, touch)
        self.assertEqual((round(lifted.x, 4), round(lifted.y, 4), round(lifted.z, 4)), (round(target.x, 4), round(target.y, 4), round(target.z + 0.25, 4)))

    def test_vertex_touch_negative_offset_lifts_along_negative_normal(self):
        root_obj, fiber, origin, _insert = _fiber_setup()
        _edit_select_vertex(origin.geometry_object_ref, 1)
        self.assertEqual(bpy.ops.af.add_fiber_touch_point(fiber_id=fiber.id), {"FINISHED"})
        touch = fiber.mid_touches[0]
        touch.normal_offset = -0.25
        target = origin.geometry_object_ref.matrix_world @ origin.geometry_object_ref.data.vertices[1].co
        lifted = touch_world(root_obj, bpy.context.scene, {}, touch)
        self.assertEqual((round(lifted.x, 4), round(lifted.y, 4), round(lifted.z, 4)), (round(target.x, 4), round(target.y, 4), round(target.z - 0.25, 4)))

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

    def test_touch_handle_stays_on_base_surface_with_offset(self):
        root_obj, fiber, origin, _insert = _fiber_setup()
        _edit_select_vertex(origin.geometry_object_ref, 1)
        self.assertEqual(bpy.ops.af.add_fiber_touch_point(fiber_id=fiber.id), {"FINISHED"})
        fiber.mid_touches[0].normal_offset = 0.2
        handle = mark_touch_handle(empty_object("TouchBase"), root_obj, fiber.id, 0)
        base = endpoint_world(root_obj, bpy.context.scene, {}, fiber.mid_touches[0].parent_id, fiber.mid_touches[0].attach_param)
        lifted = touch_world(root_obj, bpy.context.scene, {}, fiber.mid_touches[0])
        handle.location = base
        self.assertLess((handle.location - base).length, 1.0e-6)
        self.assertGreater((handle.location - lifted).length, 1.0e-6)

    def test_touch_handle_move_recaptures_surface_mode(self):
        root_obj, fiber, origin, _insert = _fiber_setup()
        _edit_select_vertex(origin.geometry_object_ref, 1)
        self.assertEqual(bpy.ops.af.add_fiber_touch_point(fiber_id=fiber.id), {"FINISHED"})
        handle = mark_touch_handle(empty_object("TouchMove"), root_obj, fiber.id, 0)
        handle.location = origin.geometry_object_ref.matrix_world @ origin.geometry_object_ref.data.vertices[2].co
        sync = register_fiber_sync()
        with patch.object(fiber_runtime, "resolve_conflict", side_effect=lambda **kwargs: kwargs["incoming"]):
            fiber_runtime.apply_fiber_control_update(sync, root_obj, bpy.context.scene, handle, bpy.context.evaluated_depsgraph_get())
        target = origin.geometry_object_ref.matrix_world @ origin.geometry_object_ref.data.vertices[2].co
        actual = endpoint_world(root_obj, bpy.context.scene, {}, fiber.mid_touches[0].parent_id, fiber.mid_touches[0].attach_param)
        self.assertEqual(parse_fiber_attach_param(fiber.mid_touches[0].attach_param)[0], "surface_param_v2")
        self.assertLess((actual - target).length, 1.0e-6)

    def test_recompute_fiber_rejects_legacy_attach_payloads(self):
        for raw in (encode_fiber_shape_param(0.25), encode_fiber_mesh_anchor(Vector((0.0, 0.0, 0.0))), encode_fiber_vertex_index(0, "sig")):
            _root_obj, fiber, _origin, _insert = _fiber_setup()
            fiber.a_attach_param = raw
            result = recompute_fiber_action(bpy.context, fiber.id)
            self.assertFalse(result.ok)
            self.assertEqual(fiber_recompute_status(fiber), "INVALID_ATTACHMENT")
            self.assertIn("Legacy attachment", fiber_invalid_reason(fiber))

    def test_recompute_fiber_marks_missing_parent_geometry_invalid(self):
        root_obj, fiber, origin, _insert = _fiber_setup()
        missing = scp_with_object(root_obj, "NoGeo", empty_object("NoGeo"), with_geometry=False)
        fiber.a_parent_id = missing.id
        fiber.a_attach_param = capture_mesh_attachment(root_obj, origin, 0)
        result = recompute_fiber_action(bpy.context, fiber.id)
        self.assertFalse(result.ok)
        self.assertEqual((fiber_recompute_status(fiber), fiber_invalid_reason(fiber)), ("INVALID_ATTACHMENT", "Missing parent geometry."))
        self.assertEqual(_fiber_points_world(fiber), [])

    def test_delete_fiber_in_tree_removes_proxy_and_handles(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        _sync_active_fiber(root_obj, fiber)
        self.assertEqual(bpy.ops.af.delete_vcp_in_tree(node_id=fiber.id, node_type="FIBER"), {"FINISHED"})
        self.assertEqual((len(root_obj.af_vcp_system.fibers), find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")), (0, None))
        self.assertEqual((root_obj.af_vcp_system.active_vcp_type, _handle_count(fiber.id)), ("NONE", 0))

    def test_create_loop_fiber_from_selected_vertices_preserves_order_and_cyclic_curve(self):
        root_obj, fiber, loop = _loop_setup()
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        anchors = [endpoint_world(root_obj, bpy.context.scene, {}, item.parent_id, item.attach_param) for item in fiber.loop_anchors]
        expected = [loop.geometry_object_ref.matrix_world @ loop.geometry_object_ref.data.vertices[i].co for i in (0, 1, 2, 3)]
        self.assertEqual((fiber.topology_mode, len(fiber.loop_anchors)), ("LOOP", 4))
        self.assertEqual((proxy.data.splines[0].use_cyclic_u, fiber_route_mode(fiber)), (True, "DIRECT"))
        self.assertTrue(all((anchors[i] - expected[i]).length < 1.0e-6 for i in range(4)))

    def test_recompute_loop_fiber_preserves_node_count_and_hides_handles(self):
        root_obj, fiber, _loop = _loop_setup()
        fiber.node_count = 48
        bpy.ops.af.recompute_fiber(fiber_id=fiber.id)
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        self.assertEqual((len(_fiber_points_world(fiber)), proxy.data.splines[0].use_cyclic_u), (48, True))
        self.assertEqual((_handle_count(fiber.id), fiber_route_mode(fiber)), (0, "DIRECT"))
        self.assertEqual(round(fiber_planner_ms(fiber), 4), 0.0)

    def test_tree_selection_does_not_resolve_loop_again(self):
        root_obj, fiber, _loop = _loop_setup()
        other = mesh_object("Other", (5.0, 0.0, 0.0))
        before = _fiber_points_world(fiber)
        select_only(other)
        self.assertEqual(bpy.ops.af.select_vcp_in_tree(node_id=fiber.id, node_type="FIBER"), {"FINISHED"})
        self.assertEqual(before, _fiber_points_world(fiber))
