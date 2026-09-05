from pathlib import Path
import os
import sys
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

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
from anthroforge.core.attachment_codec import encode_fiber_mesh_anchor, encode_fiber_shape_param, encode_fiber_surface_param, encode_fiber_vertex_index, parse_fiber_attach_param
from anthroforge.core.deps.dirty_hints import dirty_hints_for
from anthroforge.core.deps import builtin_drivers
from anthroforge.core.scp_runtime.surface import _surface_route_graph, surface_shortest_param_path
from anthroforge.core.vcp import fiber_collision
from anthroforge.core.vcp import fiber_planner
from anthroforge.core.vcp.attachment_backend import capture_attachment_from_object_ray
from anthroforge.core.vcp.fiber_collision import CollisionOracle, _active_for_bounds, _mesh_shell_nodes
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
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.visualization import fiber_sync_runtime as fiber_runtime
from anthroforge.core.visualization import fiber_view_capture
from anthroforge.core.visualization import fiber_sync_helpers
from anthroforge.core.visualization.fiber_sync import register_fiber_sync
from anthroforge.core.visualization.fiber_sync_helpers import cached_fiber_points, endpoint_world, mark_endpoint_handle, mark_touch_handle, touch_world
from anthroforge.core.visualization import fiber_refinement
from anthroforge.core.visualization.fiber_refinement import drain_fiber_refinements, fiber_refinement_state
from anthroforge.core.visualization.sync_runner import sync_from_dirty_hints
from anthroforge.properties import vcp_properties


def _fiber_setup():
    root_obj = root()
    origin = scp_with_object(root_obj, "Origin", mesh_object("Origin"))
    insert = scp_with_object(root_obj, "Insert", mesh_object("Insert", (2.0, 0.0, 0.0)))
    bpy.context.scene.af_new_fiber_origin_obj = origin.geometry_object_ref
    bpy.context.scene.af_new_fiber_insertion_obj = insert.geometry_object_ref
    bpy.ops.af.add_fiber_vcp()
    return root_obj, root_obj.af_vcp_system.fibers[0], origin, insert


def _recompute_and_drain(fiber_id=""):
    result = bpy.ops.af.recompute_fiber(fiber_id=fiber_id)
    if result == {"FINISHED"}:
        assert drain_fiber_refinements()
    return result


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


def _append_touch(root_obj, fiber, name, location):
    scp = scp_with_object(root_obj, name, mesh_object(name, location))
    touch = fiber.mid_touches.add()
    touch.parent_id = scp.id
    touch.attach_param = capture_mesh_attachment(root_obj, scp, 0)
    return scp


def _plane_scp(root_obj, name, location=(0.0, 0.0, 0.0), size=1.0):
    half = float(size) * 0.5
    mesh = bpy.data.meshes.new(name)
    verts = [(0.0, -half, -half), (0.0, half, -half), (0.0, half, half), (0.0, -half, half)]
    mesh.from_pydata(verts, [], [(0, 1, 2, 3)])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    return scp_with_object(root_obj, name, obj), obj


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


def _remove_fiber_handles(fiber_id):
    handles = [obj for obj in bpy.context.scene.objects if obj.get("af_fiber_id") == fiber_id
               and (obj.get("af_fiber_endpoint_handle") or obj.get("af_fiber_touch_handle"))]
    for obj in handles:
        bpy.data.objects.remove(obj, do_unlink=True)


def _touch_handle(fiber_id, index=0):
    return next(obj for obj in bpy.context.scene.objects if obj.get("af_fiber_touch_handle") and obj.get("af_fiber_id") == fiber_id and int(obj.get("af_fiber_touch_index", -1)) == index)


def _loop_anchor_handle(fiber_id, index=0):
    return next(obj for obj in bpy.context.scene.objects if _is_loop_anchor_handle(obj, fiber_id, index))


def _is_loop_anchor_handle(obj, fiber_id, index):
    valid = obj.get("af_fiber_loop_anchor_handle") and obj.get("af_fiber_id") == fiber_id
    return bool(valid and int(obj.get("af_fiber_loop_anchor_index", -1)) == int(index))


def _loop_mesh_object(name, location=(0.0, 0.0, 0.0)):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    return obj


def _set_stacked_surface(obj, reverse_front=False):
    verts = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (0, 1, 1)]
    front = (3, 5, 4) if reverse_front else (3, 4, 5)
    obj.data.clear_geometry()
    obj.data.from_pydata(verts, [], [(0, 1, 2), front])
    obj.data.update()
    bpy.context.view_layer.update()


def _symmetric_loop_mesh_object(name):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(0, -1, 0), (-1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _loop_setup():
    root_obj = root()
    loop = scp_with_object(root_obj, "Loop", _loop_mesh_object("Loop"))
    _edit_select_vertex(loop.geometry_object_ref, 0, 1, 2, 3)
    bpy.ops.af.create_loop_fiber_from_selected_vertices()
    return root_obj, root_obj.af_vcp_system.fibers[0], loop


def _symmetric_loop_setup():
    root_obj = root()
    loop = scp_with_object(root_obj, "SymLoop", _symmetric_loop_mesh_object("SymLoop"))
    loop.mirror_enabled, loop.mirror_axis = True, "X"
    _edit_select_vertex(loop.geometry_object_ref, 0, 1, 2)
    bpy.ops.af.create_symmetric_loop_fiber_from_selected_vertices()
    return root_obj, root_obj.af_vcp_system.fibers[0], loop


def _fiber_world_vectors(fiber):
    return [Vector(value) for value in _fiber_points_world(fiber)]


def _shown_fiber_world_vectors(fiber):
    proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
    return [Vector(point.co[:3]) for point in proxy.data.splines[0].points]


def _cache_has_point(sync, fiber_id, point, eps=1.0e-6):
    return any((cached - point).length <= eps for cached in sync._solver._cache.get(fiber_id, ()))


def _point_in_box(point, center, half_extent):
    return all(abs(point[i] - center[i]) < float(half_extent) for i in range(3))


def _polyline_hits_box(points, center, half_extent, steps=6):
    for i in range(len(points) - 1):
        for step in range(steps + 2):
            point = points[i].lerp(points[i + 1], step / float(steps + 1))
            if _point_in_box(point, center, half_extent):
                return True
    return False


def _fake_collider(index):
    x = float(index * 10)
    bounds = Vector((x, -1.0, -1.0)), Vector((x + 1.0, 1.0, 1.0))
    return {"sid": f"C{index}", "stamp": (index,), "mn": bounds[0], "mx": bounds[1]}


def _fake_tiny_collider(index):
    x, eps = float(index * 10), 1.0e-6
    bounds = Vector((x, -eps, -eps)), Vector((x + eps, eps, eps))
    return {"sid": f"T{index}", "stamp": ("tiny", index), "mn": bounds[0], "mx": bounds[1]}


def _rollback_hit(point):
    return abs(point.x - 1.0) < 0.2 and abs(point.z) < 0.05


class _RollbackOracle:
    def push_out_point(self, point, colliders):
        _ = colliders
        return point.copy(), 1.0 if _rollback_hit(point) else 0.0


def _sticky_hit(point):
    return abs(point.x - 1.0) < 0.4 and abs(point.z) <= 0.079


class _StickyRollbackOracle:
    def push_out_point(self, point, colliders):
        _ = colliders
        return point.copy(), 1.0 if _sticky_hit(point) else 0.0


class _ClearOracle:
    def push_out_point(self, point, colliders):
        _ = colliders
        return point.copy(), 0.0


def _node_band_hit(point):
    return abs(point.x - 1.0) < 0.2 and point.z < 0.6


class _NodeBandOracle:
    def push_out_point(self, point, colliders):
        _ = colliders
        return point.copy(), 1.0 if _node_band_hit(point) else 0.0


def _wide_band_hit(point):
    return abs(point.x - 1.0) < 0.35 and point.z < 0.55


class _WideBandPushOracle:
    def push_out_point(self, point, colliders):
        _ = colliders
        if not _wide_band_hit(point):
            return point.copy(), 0.0
        return Vector((point.x, point.y, 0.8)), 1.0


def _owner_zone_hit(point, sid):
    if sid == "START":
        return point.x < 0.005
    if sid == "END":
        return point.x > 1.995
    return sid == "BLOCK" and abs(point.x - 1.0) < 0.2 and point.z < 0.25


class _OwnerZoneOracle:
    margin, clearance = 0.0, 0.01
    _colliders = ({"sid": "START"}, {"sid": "BLOCK"}, {"sid": "END"})

    def active_colliders_for_polyline(self, points, padding=0.0):
        _ = points, padding
        return self._colliders

    def push_out_point(self, point, colliders):
        hit = any(_owner_zone_hit(point, c["sid"]) for c in colliders)
        return point.copy(), 1.0 if hit else 0.0


class _LocalizedPinOracle:
    def push_out_point(self, point, colliders):
        index = round(float(point.x))
        hits = {"A": index <= 2 or index >= 8, "B": 4 <= index <= 6}
        hit = any(hits.get(str(c["sid"]), False) for c in colliders)
        return point.copy(), 1.0 if hit else 0.0


class _RayHitOnlyOracle:
    def segment_hit_samples(self, a, b, colliders):
        _ = a, b, colliders
        return (0.5,)

    def push_out_point(self, point, colliders):
        raise AssertionError("ray-hit clear checks should not sample penetration")


class _EmptyRealOracle:
    def active_colliders_for_polyline(self, points, padding=0.0):
        raise AssertionError("empty filtered real collider sets must not requery active colliders")

    def push_out_point(self, point, colliders):
        raise AssertionError("empty filtered real collider sets must not push out")


class _NoRayPushOracle:
    def segment_hit_samples(self, a, b, colliders):
        _ = a, b, colliders
        return ()

    def push_out_point(self, point, colliders):
        raise AssertionError("clear ray pairs should not push out")


class _RayPushOracle:
    def __init__(self):
        self.pushes = 0

    def segment_hit_samples(self, a, b, colliders):
        _ = a, b, colliders
        return (0.5,)

    def push_out_point(self, point, colliders):
        self.pushes += 1
        return point + Vector((0.0, 0.0, 0.1)), 0.1


class _ManyShellOracle:
    def shell_nodes(self, collider, dense=False):
        _ = collider, dense
        return [Vector((float(i), 0.0, 0.0)) for i in range(500)]


class _SurfaceShortcutOracle:
    margin, clearance = 0.0, 0.01

    def active_colliders_for_segment(self, a, b, owners=(), padding=0.0):
        _ = a, b, owners, padding
        return ("active",)

    def segment_visible(self, a, b, owners=(), colliders=None):
        _ = owners, colliders
        key = tuple(round(v, 4) for v in (a.x, a.y, b.x, b.y))
        return key in {(0.0, 0.0, 1.0, 1.0), (1.0, 1.0, 1.0, 0.0)}


class _SurfaceRouteOracle:
    def __init__(self, route=None):
        self.calls = 0
        self.route = route or [Vector((0.0, 0.0, 0.0)), Vector((0.5, 0.1, 0.0)), Vector((1.0, 0.0, 0.0))]

    def surface_param_path(self, owner_id, start_param, end_param):
        _ = owner_id, start_param, end_param
        self.calls += 1
        return [point.copy() for point in self.route]


class _AlwaysVisiblePlannerOracle:
    def segment_visible(self, a, b, owners=(), colliders=None):
        _ = a, b, owners, colliders
        return True


class _NeverVisiblePlannerOracle:
    def segment_visible(self, a, b, owners=(), colliders=None):
        _ = a, b, owners, colliders
        return False


class _SelfSurfacePlannerOracle:
    margin, clearance = 0.0, 0.01

    def __init__(self):
        self.shell_calls = 0
        self.owner_calls = []

    def active_colliders_for_segment(self, a, b, padding=0.0):
        _ = a, b, padding
        return ({"sid": "S"},)

    def segment_visible(self, a, b, owners=(), colliders=None):
        self.owner_calls.append(((a.x, a.y), (b.x, b.y), tuple(owners)))
        blocked = any(c.get("sid") == "S" for c in tuple(colliders or ()))
        return not blocked or abs(a.y) > 0.1 or abs(b.y) > 0.1

    def shell_nodes(self, collider, dense=False):
        _ = collider, dense
        self.shell_calls += 1
        return [Vector((0.5, 1.0, 0.0))]


class _ExternalBlockerPlannerOracle:
    margin, clearance = 0.0, 0.01

    def __init__(self):
        self.shell_calls = 0

    def active_colliders_for_segment(self, a, b, padding=0.0):
        _ = a, b, padding
        return ({"sid": "B"},)

    def segment_visible(self, a, b, owners=(), colliders=None):
        _ = owners
        return not tuple(colliders or ()) or abs(a.y) > 0.1 or abs(b.y) > 0.1

    def shell_nodes(self, collider, dense=False):
        _ = collider, dense
        self.shell_calls += 1
        return [Vector((0.5, 1.0, 0.0))]


class _DetourBlockerPlannerOracle:
    margin, clearance = 0.0, 0.01

    def active_colliders_for_segment(self, *_args, **_kwargs):
        return ({"sid": "A"},)

    def active_colliders_for_polyline(self, points, padding=0.0):
        _ = padding
        ids = ("A", "B") if max(point.y for point in points) > 0.5 else ("A",)
        return tuple({"sid": sid} for sid in ids)

    def segment_visible(self, a, b, owners=(), colliders=None):
        _ = owners
        ids = {collider["sid"] for collider in tuple(colliders or ())}
        return not (("A" in ids and max(a.y, b.y) < 0.5) or
                    ("B" in ids and max(a.y, b.y) < 1.5))

    def shell_nodes(self, collider, dense=False):
        _ = dense
        height = 1.0 if collider["sid"] == "A" else 2.0
        return [Vector((1.0, height, 0.0))]


def _path_len(points):
    return sum((points[i + 1] - points[i]).length for i in range(len(points) - 1))


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

    def test_reselecting_fiber_recreates_removed_control_handles(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        _remove_fiber_handles(fiber.id)
        root_obj.af_vcp_system.active_vcp_type, root_obj.af_vcp_system.active_vcp_id = "FIBER", fiber.id
        sync_from_dirty_hints(root_obj, bpy.context.scene, dirty_hints_for("FIBER", {fiber.id}),
                              event_type="SELECTION")
        self.assertEqual(_handle_count(fiber.id), 2)

    def test_add_fiber_operator_creates_proxy_and_endpoint_handles(self):
        root_obj, fiber, origin, insert = _fiber_setup()
        _sync_active_fiber(root_obj, fiber)
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        count = sum(bool(obj.get("af_fiber_endpoint_handle") and obj.get("af_fiber_id") == fiber.id) for obj in bpy.context.scene.objects)
        self.assertEqual((fiber.a_parent_id, fiber.b_parent_id, proxy is not None), (origin.id, insert.id, True))
        self.assertEqual((bool(fiber.a_attach_param), bool(fiber.b_attach_param), count), (True, True, 2))

    def test_add_fiber_suppresses_intermediate_prop_sync(self):
        root_obj = root()
        origin = scp_with_object(root_obj, "Origin", mesh_object("Origin"))
        insert = scp_with_object(root_obj, "Insert", mesh_object("Insert", (2.0, 0.0, 0.0)))
        bpy.context.scene.af_new_fiber_origin_obj = origin.geometry_object_ref
        bpy.context.scene.af_new_fiber_insertion_obj = insert.geometry_object_ref
        with patch.object(vcp_properties, "sync_context") as sync:
            self.assertEqual(bpy.ops.af.add_fiber_vcp(), {"FINISHED"})
        self.assertEqual(sync.call_count, 0)

    def test_fiber_display_edits_do_not_schedule_solver_runtime(self):
        _root_obj, fiber, _origin, _insert = _fiber_setup()
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        with patch.object(vcp_properties, "schedule_context") as schedule, patch.object(vcp_properties, "sync_context") as sync:
            fiber.name = "Display only"
            fiber.thickness = 0.031
        self.assertEqual((schedule.call_count, sync.call_count), (0, 0))
        self.assertAlmostEqual(proxy.data.bevel_depth, 0.031)

    def test_fiber_solver_edit_schedules_targeted_aspect(self):
        _root_obj, fiber, _origin, _insert = _fiber_setup()
        with patch.object(vcp_properties, "schedule_context") as schedule, patch.object(vcp_properties, "sync_context") as sync:
            fiber.bend_stiffness = 0.25
        kwargs = schedule.call_args.kwargs
        self.assertEqual((schedule.call_count, sync.call_count, kwargs["event_type"]), (1, 0, "FIBER_UPDATE"))
        self.assertEqual((kwargs["dirty_hints"]["FIBER"], kwargs["dirty_aspects"]), ({fiber.id}, {"FIBER": {"SOLVER"}}))

    def test_fiber_touch_add_suppresses_nested_callback_runtime(self):
        _root_obj, fiber, origin, _insert = _fiber_setup()
        select_only(origin.geometry_object_ref)
        with patch.object(vcp_properties, "schedule_context") as schedule:
            result = bpy.ops.af.add_fiber_touch_point(fiber_id=fiber.id)
        self.assertEqual((result, schedule.call_count), ({"FINISHED"}, 0))

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
        _recompute_and_drain()
        self.assertIn(fiber_recompute_status(fiber), {"CONVERGED", "NOT_CONVERGED",
                                                     "STALLED", "BUDGET_EXHAUSTED"})
        self.assertGreaterEqual(fiber_recompute_ms(fiber), 0.0)

    def test_recompute_returns_while_blocked_route_is_refining(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        _cube_scp(root_obj, "Blocker", (1.0, 0.0, 0.0), 0.8)
        self.assertEqual(bpy.ops.af.recompute_fiber(), {"FINISHED"})
        self.assertEqual((fiber_recompute_status(fiber), fiber_refinement_state(bpy.context.scene, fiber.id)),
                         ("REFINING", "REFINING"))
        self.assertTrue(drain_fiber_refinements())

    def test_refinement_completion_dispatches_one_solve_ready_event(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        _cube_scp(root_obj, "Blocker", (1.0, 0.0, 0.0), 0.8)
        callback = Mock()
        with patch.object(fiber_refinement, "_sync_scene", return_value=callback):
            bpy.ops.af.recompute_fiber()
            self.assertTrue(drain_fiber_refinements())
        self.assertEqual(callback.call_count, 1)
        self.assertEqual(callback.call_args.kwargs["payload"], {"solved_fiber_ids": [fiber.id]})

    def test_fiber_edit_cancels_stale_refinement_and_keeps_curve(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        _cube_scp(root_obj, "Blocker", (1.0, 0.0, 0.0), 0.8)
        before = _fiber_points_world(fiber)
        bpy.ops.af.recompute_fiber()
        with suppress_vcp_prop_updates():
            fiber.node_count += 8
        self.assertTrue(drain_fiber_refinements())
        self.assertEqual(fiber_recompute_status(fiber), "UNKNOWN")
        self.assertEqual(_fiber_points_world(fiber), before)

    def test_collider_geometry_update_cancels_refinement(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        _blocker, obj = _cube_scp(root_obj, "Blocker", (1.0, 0.0, 0.0), 0.8)
        bpy.ops.af.recompute_fiber()
        update = SimpleNamespace(id=obj.data, is_updated_geometry=True, is_updated_transform=False)
        fiber_refinement._on_depsgraph_update(bpy.context.scene, SimpleNamespace(updates=(update,)))
        self.assertEqual(fiber_refinement_state(bpy.context.scene, fiber.id), "UNKNOWN")

    def test_new_refinement_request_supersedes_existing_job(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        _cube_scp(root_obj, "Blocker", (1.0, 0.0, 0.0), 0.8)
        first = fiber_refinement.request_fiber_refinement(root_obj, bpy.context.scene, fiber)
        second = fiber_refinement.request_fiber_refinement(root_obj, bpy.context.scene, fiber)
        self.assertIsNot(first.job, second.job)
        self.assertEqual(fiber_refinement_state(bpy.context.scene, fiber.id), "REFINING")
        self.assertTrue(drain_fiber_refinements())

    def test_recompute_fiber_preserves_requested_node_count(self):
        _root_obj, fiber, _origin, _insert = _fiber_setup()
        fiber.node_count = 96
        _recompute_and_drain()
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        self.assertEqual(len(json.loads(proxy["af_fiber_points_world"])), 96)

    def test_curve_update_skips_unchanged_payload_and_caches_points(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        points = [Vector(value) for value in json.loads(proxy["af_fiber_points_world"])]
        with patch.object(fiber_sync_helpers, "_write_curve_payload") as writer:
            fiber_sync_helpers.update_curve_points(proxy, points, fiber.thickness)
        cached = cached_fiber_points(bpy.context.scene, root_obj.name, fiber.id)
        self.assertEqual((writer.call_count, len(cached)), (0, len(points)))

    def test_transient_curve_preview_skips_persisted_output_and_cache(self):
        _root_obj, fiber, _origin, _insert = _fiber_setup()
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        points = [Vector(value) for value in json.loads(proxy["af_fiber_points_world"])]
        middle, preview = len(points) // 2, [point.copy() for point in points]
        preview[middle].z += 0.25
        keys = ("af_fiber_points_world", "af_fiber_points_mode", "af_fiber_points_signature")
        before = tuple(proxy.get(key) for key in keys)
        with patch.object(fiber_sync_helpers, "scene_cache_set") as cache:
            fiber_sync_helpers.update_curve_points(proxy, preview, 0.027, commit=False)
        after = tuple(proxy.get(key) for key in keys)
        shown = proxy.data.splines[0].points[middle].co.z
        self.assertEqual((cache.call_count, after), (0, before))
        self.assertEqual((round(shown, 6), round(proxy.data.bevel_depth, 6)), (round(preview[middle].z, 6), 0.027))

    def test_bake_quality_is_one_shot_and_clears_legacy_preference(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        sync = register_fiber_sync()
        fiber["af_prefer_bake"] = True
        sync.sync_root_to_scene(root=root_obj, scene=bpy.context.scene, bake=True, target_fiber_ids={fiber.id})
        first = proxy.get("af_fiber_points_mode")
        sync.sync_root_to_scene(root=root_obj, scene=bpy.context.scene, bake=False, target_fiber_ids={fiber.id})
        self.assertEqual((first, proxy.get("af_fiber_points_mode"), bool(fiber.get("af_prefer_bake", False))),
                         ("BAKE", "INTERACTIVE", False))

    def test_recompute_fiber_direct_mode_records_planner_metrics(self):
        _root_obj, fiber, _origin, _insert = _fiber_setup_direct()
        _recompute_and_drain()
        self.assertEqual(fiber_route_mode(fiber), "DIRECT")
        self.assertGreaterEqual(fiber_planner_ms(fiber), 0.0)
        self.assertGreaterEqual(fiber_refine_ms(fiber), 0.0)

    def test_recompute_fiber_roadmap_mode_detours_around_blocker(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        _cube_scp(root_obj, "Blocker", (1.0, 0.0, 0.0), 0.8)
        _recompute_and_drain()
        points = _fiber_points_world(fiber)
        self.assertEqual(fiber_route_mode(fiber), "ROADMAP")
        self.assertTrue(any(abs(p[1]) > 1.0e-4 or abs(p[2]) > 1.0e-4 for p in points[1:-1]))

    def test_interactive_sync_uses_collision_safe_roadmap(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        _cube_scp(root_obj, "Blocker", (1.0, 0.0, 0.0), 0.8)
        register_fiber_sync().sync_root_to_scene(root=root_obj, scene=bpy.context.scene, bake=False)
        self.assertEqual(fiber_route_mode(fiber), "ROADMAP")
        self.assertGreaterEqual(fiber_planner_ms(fiber), 0.0)

    def test_interactive_planner_preview_renders_cleaned_planner_route(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        fiber.preview_planner_route = True
        _cube_scp(root_obj, "Blocker", (1.0, 0.0, 0.0), 0.8)
        persisted = _fiber_points_world(fiber)
        register_fiber_sync().sync_root_to_scene(root=root_obj, scene=bpy.context.scene, bake=False)
        points = _shown_fiber_world_vectors(fiber)
        a_world = endpoint_world(root_obj, bpy.context.scene, {}, fiber.a_parent_id, fiber.a_attach_param)
        b_world = endpoint_world(root_obj, bpy.context.scene, {}, fiber.b_parent_id, fiber.b_attach_param)
        self.assertEqual(fiber_route_mode(fiber), "ROADMAP")
        self.assertGreater(fiber_planner_ms(fiber), 0.0)
        self.assertLess(len(points), fiber.node_count)
        self.assertEqual(_fiber_points_world(fiber), persisted)
        self.assertLess((points[0] - a_world).length, 1.0e-6)
        self.assertLess((points[-1] - b_world).length, 1.0e-6)
        self.assertTrue(any(abs(p.y) > 1.0e-4 or abs(p.z) > 1.0e-4 for p in points[1:-1]))

    def test_progressive_planner_preview_remains_after_drain(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        _cube_scp(root_obj, "Blocker", (1.0, 0.0, 0.0), 0.8)
        persisted = _fiber_points_world(fiber)
        with suppress_vcp_prop_updates():
            fiber.preview_planner_route = True
        request = fiber_refinement.request_fiber_refinement(
            root_obj, bpy.context.scene, fiber, True, "INTERACTIVE")
        self.assertTrue(request.ok and drain_fiber_refinements())
        shown = _shown_fiber_world_vectors(fiber)
        self.assertEqual(fiber_recompute_status(fiber), "PLANNER_PREVIEW")
        self.assertLess(len(shown), fiber.node_count)
        self.assertEqual(_fiber_points_world(fiber), persisted)
        self.assertEqual(request.job.session.preview, shown)
        self.assertEqual(_shown_fiber_world_vectors(fiber), shown)

    def test_failed_planner_preview_keeps_last_curve(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        persisted = _fiber_points_world(fiber)
        with suppress_vcp_prop_updates():
            fiber.preview_planner_route = True
        request = fiber_refinement.request_fiber_refinement(
            root_obj, bpy.context.scene, fiber, False, "INTERACTIVE")
        request.job.session.preview = [Vector((0, 0, 0)), Vector((2, 0, 0))]
        request.job.session.done = True
        request.job.session.termination_reason = "NO_FEASIBLE_PATH"
        result = request.job.session.result()
        fiber_refinement._apply_progress(request.job, result)
        fiber_refinement._finish_job(request.job, result)
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        self.assertEqual((_shown_fiber_world_vectors(fiber), _fiber_points_world(fiber)),
                         (request.job.session.preview, persisted))
        self.assertEqual(proxy.get("af_fiber_display_mode"), "FAILED_PREVIEW")

    def test_sync_failed_planner_preview_keeps_last_curve(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        sync = register_fiber_sync()
        kept = [Vector((0, 0, 0)), Vector((1, 0, 0.5)), Vector((2, 0, 0))]
        sync.apply_points(root_obj, bpy.context.scene, fiber, kept, commit=True)
        persisted = _fiber_points_world(fiber)
        fiber.preview_planner_route = True
        fallback = [Vector((0, 0, 0)), Vector((2, 0, 0))]
        request = fiber_refinement.request_fiber_refinement(root_obj, bpy.context.scene, fiber, True, "INTERACTIVE")
        request.job.session.preview, request.job.session.level = fallback, None
        request.job.session.done, request.job.session.termination_reason = True, "NO_FEASIBLE_PATH"
        result = request.job.session.result(); fiber_refinement._apply_progress(request.job, result)
        fiber_refinement._finish_job(request.job, result)
        self.assertEqual((_shown_fiber_world_vectors(fiber), _fiber_points_world(fiber)), (fallback, persisted))

    def test_planner_avoids_thin_blocker_independently_of_segment_toggle(self):
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
        self.assertFalse(_polyline_hits_box(points_off, Vector((1.0, 0.0, 0.0)), 0.05))
        self.assertFalse(_polyline_hits_box(points_on, Vector((1.0, 0.0, 0.0)), 0.05))

    def test_segment_collision_oracle_samples_zero_thickness_plane_hit(self):
        root_obj = root()
        blocker, _obj = _plane_scp(root_obj, "PlaneBlocker", (1.0, 0.0, 0.0), 0.8)
        oracle = CollisionOracle(root_obj, bpy.context.scene, bpy.context.evaluated_depsgraph_get(), 0.002, 0.002)
        colliders = [c for c in oracle.colliders() if c["sid"] == blocker.id]
        samples = oracle.segment_hit_samples(Vector((0.0, 0.0, 0.0)), Vector((2.0, 0.0, 0.0)), colliders)
        pushed, pen = oracle.push_out_point(Vector((1.0, 0.0, 0.0)), colliders)
        push_delta = (pushed - Vector((1.0, 0.0, 0.0))).length
        hit_cache_size, push_cache_size = len(oracle._segment_hit_cache), len(oracle._push_cache)
        pushed.x = 99.0
        samples_again = oracle.segment_hit_samples(Vector((0.0, 0.0, 0.0)), Vector((2.0, 0.0, 0.0)), colliders)
        pushed_again, _pen_again = oracle.push_out_point(Vector((1.0, 0.0, 0.0)), colliders)
        self.assertEqual((len(oracle._segment_hit_cache), len(oracle._push_cache)), (hit_cache_size, push_cache_size))
        self.assertTrue(samples)
        self.assertEqual(samples_again, samples)
        self.assertAlmostEqual(samples[0], 0.5, places=4)
        self.assertGreater(pen, 0.0)
        self.assertLess(pushed_again.x, 10.0)
        self.assertGreater(push_delta, 0.0)

    def test_far_collider_filter_does_not_materialize_full_surface(self):
        root_obj = root()
        _cube_scp(root_obj, "FarBlocker", (100.0, 0.0, 0.0), 1.0)
        depsgraph = bpy.context.evaluated_depsgraph_get()
        oracle = CollisionOracle(root_obj, bpy.context.scene, depsgraph)
        points = (Vector((0.0, 0.0, 0.0)), Vector((1.0, 0.0, 0.0)))
        with patch.object(fiber_collision, "build_mesh_surface_data") as full_surface:
            self.assertEqual(tuple(oracle.active_colliders_for_polyline(points)), ())
        self.assertEqual(full_surface.call_count, 0)

    def test_planner_shell_nodes_follow_rotated_mesh_boundary(self):
        root_obj = root()
        blocker, obj = _plane_scp(root_obj, "RotatedPlane", (1.0, 0.0, 0.0), 2.0)
        obj.rotation_euler = (0.0, 0.65, 0.55)
        bpy.context.view_layer.update()
        oracle = CollisionOracle(root_obj, bpy.context.scene, bpy.context.evaluated_depsgraph_get(), 0.002, 0.002)
        collider = next(c for c in oracle.colliders() if c["sid"] == blocker.id)
        shell = tuple(oracle.shell_nodes(collider))
        verts = tuple(obj.matrix_world @ vert.co for vert in obj.data.vertices)
        self.assertTrue(all(min((node - vert).length for node in shell) < 0.08 for vert in verts))

    def test_segment_collision_rollback_restores_i_plus_one_node(self):
        prev = [Vector((0.0, 0.0, 0.0)), Vector((0.7, 0.0, 0.08)), Vector((1.3, 0.0, 0.08)), Vector((2.0, 0.0, 0.0))]
        nodes = [point.copy() for point in prev]
        params = {"shorten_strength": 1.0, "bend_strength": 0.0, "margin": 0.0, "segment_collisions": True}
        FiberSolver()._solver_iteration(nodes, [point.copy() for point in prev], [True, False, False, True], {0: prev[0], 3: prev[3]}, _RollbackOracle(), (), params, 0)
        self.assertLess(nodes[1].z, prev[1].z)
        self.assertEqual(tuple(round(v, 4) for v in nodes[2]), tuple(round(v, 4) for v in prev[2]))

    def test_segment_guard_node_becomes_next_iteration_phantom_pin(self):
        prev = [Vector((0.0, 0.0, 0.0)), Vector((0.7, 0.0, 0.08)), Vector((1.3, 0.0, 0.08)), Vector((2.0, 0.0, 0.0))]
        nodes, solver, guards = [point.copy() for point in prev], FiberSolver(), {}
        pins, targets = [True, False, False, True], {0: prev[0], 3: prev[3]}
        params = {"shorten_strength": 1.0, "bend_strength": 0.0, "margin": 0.0, "segment_collisions": True}
        solver._solver_iteration(nodes, [point.copy() for point in prev], pins, targets, _RollbackOracle(), (), params, 0, next_guards=guards)
        locked = guards[2].copy()
        solver._solver_iteration(nodes, [point.copy() for point in nodes], pins, targets, _ClearOracle(), (), dict(params, segment_collisions=False), 1, guards, {})
        self.assertEqual(tuple(round(v, 4) for v in nodes[2]), tuple(round(v, 4) for v in locked))

    def test_segment_collision_fallback_restores_last_clear_state(self):
        prev = [Vector((0.0, 0.0, 0.0)), Vector((0.7, 0.0, 0.08)), Vector((1.3, 0.0, 0.08)), Vector((2.0, 0.0, 0.0))]
        nodes = [point.copy() for point in prev]
        params = {"shorten_strength": 1.0, "bend_strength": 0.0, "margin": 0.0, "segment_collisions": True, "iterations": 1, "min_iters": 0, "eps_disp": 0.0, "eps_pen": 0.0}
        FiberSolver()._run_iterations(nodes, [point.copy() for point in prev], [True, False, False, True], {0: prev[0], 3: prev[3]}, _StickyRollbackOracle(), (), params)
        self.assertEqual([tuple(round(v, 4) for v in point) for point in nodes], [tuple(round(v, 4) for v in point) for point in prev])

    def test_valid_planner_seed_backtracks_unsafe_first_step(self):
        prev = [Vector((0.0, 0.0, 0.0)), Vector((1.0, 0.0, 1.0)), Vector((2.0, 0.0, 0.0))]
        nodes = [point.copy() for point in prev]
        params = {"shorten_strength": 1.0, "bend_strength": 0.0, "margin": 0.0, "segment_collisions": True, "iterations": 1, "min_iters": 0, "eps_disp": 0.0, "eps_pen": 0.0}
        FiberSolver()._run_iterations(nodes, [point.copy() for point in prev], [True, False, True], {0: prev[0], 2: prev[2]}, _NodeBandOracle(), (), params)
        self.assertGreaterEqual(nodes[1].z, 0.6)
        self.assertLess(nodes[1].z, prev[1].z)

    def test_surface_route_guides_seed_without_becoming_pins(self):
        solver = FiberSolver()
        fiber = type("Fiber", (), {"id": "F", "use_warm_start": False})()
        anchors = [fiber_planner.PlannerAnchor(Vector((0.0, 0.0, 0.0))), fiber_planner.PlannerAnchor(Vector((1.0, 0.0, 0.0))), fiber_planner.PlannerAnchor(Vector((2.0, 0.0, 0.0)))]
        guides = [Vector((0.5, 1.0, 0.0)), anchors[1].point.copy(), Vector((1.5, -1.0, 0.0))]
        nodes, pinned, targets = solver._build_level_nodes(fiber, anchors, guides, 9, None)
        pinned_indices = [i for i, value in enumerate(pinned) if value]
        self.assertEqual(pinned_indices, [0, 4, 8])
        self.assertEqual(set(targets), {0, 4, 8})
        self.assertGreater(nodes[2].y, 0.0)

    def test_mid_anchors_seed_nodes_when_surface_routing_disabled(self):
        solver = FiberSolver()
        fiber = type("Fiber", (), {"id": "F", "use_warm_start": False})()
        anchors = [fiber_planner.PlannerAnchor(Vector((0.0, 0.0, 0.0))), fiber_planner.PlannerAnchor(Vector((1.0, 1.0, 0.0))), fiber_planner.PlannerAnchor(Vector((2.0, 0.0, 0.0)))]
        nodes, pinned, targets = solver._build_level_nodes(fiber, anchors, [], 9, None)
        pinned_indices = [i for i, value in enumerate(pinned) if value]
        self.assertEqual(pinned_indices, [0, 4, 8])
        self.assertEqual(set(targets), {0, 4, 8})
        self.assertLess((nodes[4] - anchors[1].point).length, 1.0e-6)

    def test_multilevel_first_pass_fits_all_mid_anchors(self):
        solver = FiberSolver()
        anchors = [fiber_planner.PlannerAnchor(Vector((float(i), 0.0, 0.0)), str(i)) for i in range(9)]
        fiber = type("Fiber", (), {"id": "F", "use_warm_start": False})()
        params = {"node_count": 64, "iterations": 4, "margin": 0.0}
        with patch.object(solver, "_active_colliders", return_value=()), patch.object(solver, "_run_iterations", return_value=(True, 0.0, 0.0)):
            nodes, *_rest = solver._solve_multilevel(fiber, anchors, [], _ClearOracle(), params, None)
        self.assertEqual(len(nodes), 64)

    def test_surface_route_toggle_skips_guides_when_disabled(self):
        raw_a = encode_fiber_surface_param({"tri_vidx": (0, 1, 2), "tri_weights": (1.0, 0.0, 0.0)})
        raw_b = encode_fiber_surface_param({"tri_vidx": (0, 1, 2), "tri_weights": (0.0, 1.0, 0.0)})
        anchors = [fiber_planner.PlannerAnchor(Vector((0.0, 0.0, 0.0)), "S", raw_a), fiber_planner.PlannerAnchor(Vector((1.0, 0.0, 0.0)), "S", raw_b)]
        oracle = _SurfaceRouteOracle()
        fiber = type("Fiber", (), {"use_surface_routing": False})()
        self.assertEqual(FiberSolver()._planner_guides(fiber, oracle, anchors), [])
        self.assertEqual(oracle.calls, 0)
        oracle = _SurfaceRouteOracle()
        self.assertEqual(len(FiberSolver()._planner_guides(type("Fiber", (), {})(), oracle, anchors)), 1)
        self.assertEqual(oracle.calls, 1)

    def test_surface_route_rejects_large_detour(self):
        raw_a = encode_fiber_surface_param({"tri_vidx": (0, 1, 2), "tri_weights": (1.0, 0.0, 0.0)})
        raw_b = encode_fiber_surface_param({"tri_vidx": (0, 1, 2), "tri_weights": (0.0, 1.0, 0.0)})
        route = [Vector((0.0, 0.0, 0.0)), Vector((0.0, 1.0, 0.0)), Vector((1.0, 0.0, 0.0))]
        anchors = [fiber_planner.PlannerAnchor(route[0], "S", raw_a), fiber_planner.PlannerAnchor(route[-1], "S", raw_b)]
        oracle = _SurfaceRouteOracle(route)
        self.assertEqual(FiberSolver()._planner_guides(type("Fiber", (), {})(), oracle, anchors), [])
        self.assertEqual(oracle.calls, 1)

    def test_surface_route_accepts_near_direct_detour(self):
        raw_a = encode_fiber_surface_param({"tri_vidx": (0, 1, 2), "tri_weights": (1.0, 0.0, 0.0)})
        raw_b = encode_fiber_surface_param({"tri_vidx": (0, 1, 2), "tri_weights": (0.0, 1.0, 0.0)})
        route = [Vector((0.0, 0.0, 0.0)), Vector((0.5, 0.1, 0.0)), Vector((1.0, 0.0, 0.0))]
        anchors = [fiber_planner.PlannerAnchor(route[0], "S", raw_a), fiber_planner.PlannerAnchor(route[-1], "S", raw_b)]
        self.assertEqual(len(FiberSolver()._planner_guides(type("Fiber", (), {})(), _SurfaceRouteOracle(route), anchors)), 1)

    def test_surface_route_keeps_endpoint_touch_segments(self):
        raw = encode_fiber_surface_param({"tri_vidx": (0, 1, 2), "tri_weights": (1.0, 0.0, 0.0)})
        anchors = [fiber_planner.PlannerAnchor(Vector((float(i), 0.0, 0.0)), "S", raw) for i in range(3)]
        oracle = _SurfaceRouteOracle()
        self.assertEqual(len(FiberSolver()._planner_guides(type("Fiber", (), {})(), oracle, anchors)), 3)
        self.assertEqual(oracle.calls, 2)

    def test_surface_route_skips_touch_to_touch_segments(self):
        raw = encode_fiber_surface_param({"tri_vidx": (0, 1, 2), "tri_weights": (1.0, 0.0, 0.0)})
        anchors = [fiber_planner.PlannerAnchor(Vector((float(i), 0.0, 0.0)), "S", raw) for i in range(4)]
        oracle = _SurfaceRouteOracle()
        self.assertEqual(len(FiberSolver()._planner_guides(type("Fiber", (), {})(), oracle, anchors)), 4)
        self.assertEqual(oracle.calls, 2)

    def test_surface_param_path_accepts_barycentric_endpoints(self):
        verts = [Vector((0.0, 0.0, 0.0)), Vector((1.0, 0.0, 0.0)), Vector((1.0, 1.0, 0.0)), Vector((0.0, 1.0, 0.0))]
        surface = {"verts_world": verts, "route_graph": _surface_route_graph(verts, ((0, 1, 2), (0, 2, 3)))}
        start = {"tri_vidx": (0, 1, 2), "tri_weights": (0.2, 0.7, 0.1)}
        end = {"tri_vidx": (0, 2, 3), "tri_weights": (0.1, 0.2, 0.7)}
        path = surface_shortest_param_path(surface, start, end)
        expected_start = verts[0] * 0.2 + verts[1] * 0.7 + verts[2] * 0.1
        expected_end = verts[0] * 0.1 + verts[2] * 0.2 + verts[3] * 0.7
        self.assertGreater(len(path), 2)
        self.assertLess((path[0] - expected_start).length, 1.0e-6)
        self.assertLess((path[-1] - expected_end).length, 1.0e-6)

    def test_surface_route_shortcuts_visible_detour(self):
        route = [Vector((0.0, 0.0, 0.0)), Vector((0.0, 1.0, 0.0)), Vector((1.0, 1.0, 0.0)), Vector((1.0, 0.0, 0.0))]
        start = type("Anchor", (), {"point": route[0], "owner_id": "S"})()
        end = type("Anchor", (), {"point": route[-1], "owner_id": "S"})()
        short = FiberSolver()._shortcut_surface_route(_SurfaceShortcutOracle(), start, end, route)
        self.assertEqual([tuple(point) for point in short], [tuple(route[0]), tuple(route[2]), tuple(route[3])])

    def test_invalid_planner_seed_can_accept_first_clear_projection(self):
        prev = [Vector((0.0, 0.0, 0.0)), Vector((1.0, 0.0, 0.4)), Vector((2.0, 0.0, 0.0))]
        nodes = [point.copy() for point in prev]
        params = {"shorten_strength": 1.0, "bend_strength": 0.0, "margin": 0.0, "segment_collisions": True, "iterations": 1, "min_iters": 0, "eps_disp": 0.0, "eps_pen": 0.0}
        FiberSolver()._run_iterations(nodes, [point.copy() for point in prev], [True, False, True], {0: prev[0], 2: prev[2]}, _WideBandPushOracle(), (), params)
        self.assertAlmostEqual(nodes[1].z, 0.8, places=4)

    def test_backtracking_refines_to_larger_safe_alpha(self):
        start = [Vector((0.0, 0.0, 0.0)), Vector((1.0, 0.0, 1.0)), Vector((2.0, 0.0, 0.0))]
        candidate = [start[0].copy(), Vector((1.0, 0.0, 0.0)), start[2].copy()]
        nodes = [point.copy() for point in start]
        params = {"margin": 0.0, "segment_collisions": True}
        alpha, _pen = FiberSolver()._accept_candidate(nodes, start, candidate, _NodeBandOracle(), params, skip_ends=True)
        self.assertGreater(alpha, 0.25)
        self.assertGreater(nodes[1].z, 0.5)

    def test_seed_restore_ignores_only_local_endpoint_owner_zones(self):
        solver, oracle = FiberSolver(), _OwnerZoneOracle()
        params = {"margin": 0.0, "segment_collisions": True, "endpoint_owners": ("START", "END")}
        seed = [Vector((0.0, 0.0, 0.0)), Vector((0.2, 0.0, 0.0)), Vector((0.8, 0.0, 1.0)), Vector((1.2, 0.0, 1.0)), Vector((1.8, 0.0, 0.0)), Vector((2.0, 0.0, 0.0))]
        nodes = [Vector((0.0, 0.0, 0.0)), Vector((0.2, 0.0, 0.0)), Vector((0.8, 0.0, 0.0)), Vector((1.2, 0.0, 0.0)), Vector((1.8, 0.0, 0.0)), Vector((2.0, 0.0, 0.0))]
        solver._restore_seed_if_needed(nodes, seed, oracle, params)
        self.assertGreater(min(nodes[2].z, nodes[3].z), 0.5)
        self.assertTrue(solver._segments_clear(nodes, oracle, oracle._colliders, params, skip_ends=True))

    def test_owner_zones_are_bounded_to_authored_pins(self):
        solver, oracle = FiberSolver(), _LocalizedPinOracle()
        nodes = [Vector((float(index), 0.0, 0.0)) for index in range(10)]
        colliders = ({"sid": "A"}, {"sid": "B"})
        params = {"pin_owners": {0: "A", 5: "B"}}
        zones = solver._owner_zone_limits(nodes, oracle, colliders, params)
        self.assertEqual(zones, {"A": ((0, 0),), "B": ((5, 5),)})
        self.assertTrue(solver._node_collider_allowed(colliders[0], 8, zones))

    def test_accepted_state_keeps_authored_owner_zones_stable(self):
        solver, oracle = FiberSolver(), _LocalizedPinOracle()
        nodes = [Vector((float(index), 0.0, 0.0)) for index in range(10)]
        colliders, params = ({"sid": "A"}, {"sid": "B"}), {"margin": 0.0, "pin_owners": {0: "A", 5: "B"}}
        self.assertEqual(solver._owner_zone_limits(nodes, oracle, colliders, params)["A"], ((0, 0),))
        nodes[2].x = 4.0
        with patch.object(solver, "_active_colliders", return_value=colliders), patch.object(solver, "_refresh_safe_snapshot", return_value=None):
            solver._post_iteration_state(nodes, oracle, params, None)
        self.assertEqual(solver._owner_zone_limits(nodes, oracle, colliders, params)["A"], ((0, 0),))

    def test_segment_blocked_early_out_uses_ray_hit_without_pushout(self):
        blocked = FiberSolver()._segment_blocked(Vector((0.0, 0.0, 0.0)), Vector((1.0, 0.0, 0.0)), _RayHitOnlyOracle(), ({"sid": "A"},))
        self.assertTrue(blocked)

    def test_empty_real_collider_filter_short_circuits_penetration(self):
        pen = FiberSolver()._sample_penetration(Vector((0.0, 0.0, 0.0)), _EmptyRealOracle(), ())
        self.assertEqual(pen, 0.0)

    def test_active_collider_spatial_index_filters_many_aabbs(self):
        colliders = tuple(_fake_collider(i) for i in range(40))
        bounds = Vector((100.2, -0.2, -0.2)), Vector((100.8, 0.2, 0.2))
        active = _active_for_bounds(bpy.context.scene, colliders, bounds)
        self.assertEqual([c["sid"] for c in active], ["C10"])

    def test_active_collider_spatial_index_caps_huge_query_cells(self):
        colliders = tuple(_fake_tiny_collider(i) for i in range(40))
        bounds = Vector((-1.0, -0.1, -0.1)), Vector((400.0, 0.1, 0.1))
        active = _active_for_bounds(bpy.context.scene, colliders, bounds)
        self.assertEqual(len(active), 40)

    def test_shell_nodes_sample_large_mesh_vertices(self):
        verts = [Vector((float(i), 0.0, 0.0)) for i in range(300)]
        nodes = _mesh_shell_nodes({"surface": {"verts_world": verts, "triangles": ()}}, 0.0, False)
        self.assertEqual(len(nodes), 32)

    def test_roadmap_nodes_cap_many_shell_points(self):
        start = fiber_planner.PlannerAnchor(Vector((0.0, 0.0, 0.0)))
        end = fiber_planner.PlannerAnchor(Vector((1.0, 0.0, 0.0)))
        segment = fiber_planner.PlannerSegment(start, end)
        nodes = fiber_planner._roadmap_nodes(_ManyShellOracle(), segment, ({"sid": "A"},), False)
        self.assertEqual(len(nodes), 96)

    def test_planner_routes_around_same_owner_chord(self):
        oracle = _SelfSurfacePlannerOracle()
        start = fiber_planner.PlannerAnchor(Vector((0.0, 0.0, 0.0)), "S")
        end = fiber_planner.PlannerAnchor(Vector((1.0, 0.0, 0.0)), "S")
        result = fiber_planner._plan_segment(oracle, fiber_planner.PlannerSegment(start, end), False)
        self.assertEqual((result.mode, len(result.points), result.active_ids), (fiber_planner.ROADMAP, 3, ("S",)))
        self.assertGreater(oracle.shell_calls, 0)
        detour_owners = [owners for a, b, owners in oracle.owner_calls if abs(a[1]) > 0.1 or abs(b[1]) > 0.1]
        self.assertIn(("S", ""), detour_owners)
        self.assertIn(("", "S"), detour_owners)

    def test_planner_keeps_external_blocker_as_roadmap_collider(self):
        oracle = _ExternalBlockerPlannerOracle()
        start = fiber_planner.PlannerAnchor(Vector((0.0, 0.0, 0.0)), "S")
        end = fiber_planner.PlannerAnchor(Vector((1.0, 0.0, 0.0)), "S")
        result = fiber_planner._plan_segment(oracle, fiber_planner.PlannerSegment(start, end), False)
        self.assertEqual((result.mode, len(result.points), result.active_ids), (fiber_planner.ROADMAP, 3, ("B",)))
        self.assertGreater(oracle.shell_calls, 0)

    def test_planner_replans_for_blocker_discovered_on_detour(self):
        oracle = _DetourBlockerPlannerOracle()
        anchors = (fiber_planner.PlannerAnchor(Vector((0.0, 0.0, 0.0))),
                   fiber_planner.PlannerAnchor(Vector((2.0, 0.0, 0.0))))
        result = fiber_planner.plan_route(oracle, anchors, allow_dense=False)
        self.assertEqual((result.mode, result.active_ids),
                         (fiber_planner.ROADMAP, ("A", "B")))
        self.assertGreater(max(point.y for point in result.points), 1.5)

    def test_planner_relax_shortens_visible_zigzag_seed(self):
        route = [Vector((0.0, 0.0, 0.0)), Vector((0.5, 1.0, 0.0)), Vector((1.0, 0.0, 0.0))]
        relaxed = fiber_planner._relax_path(_AlwaysVisiblePlannerOracle(), route, ())
        self.assertLess(_path_len(relaxed), _path_len(route))
        self.assertAlmostEqual(relaxed[1].y, 0.0, places=4)

    def test_planner_relax_preserves_blocked_zigzag_seed(self):
        route = [Vector((0.0, 0.0, 0.0)), Vector((0.5, 1.0, 0.0)), Vector((1.0, 0.0, 0.0))]
        relaxed = fiber_planner._relax_path(_NeverVisiblePlannerOracle(), route, ())
        self.assertEqual([tuple(point) for point in relaxed], [tuple(point) for point in route])

    def test_segment_penalty_skips_pushout_without_ray_hit(self):
        nodes = [Vector((0.1, 0.0, 0.0)), Vector((0.9, 0.0, 0.0))]
        params = {"margin": 0.0, "segment_collisions": True}
        pen = FiberSolver()._apply_segment_collision_constraints(nodes, [False, False], _NoRayPushOracle(), (_fake_collider(0),), params)
        self.assertEqual(pen, 0.0)

    def test_segment_penalty_samples_pushout_after_ray_hit(self):
        nodes, oracle = [Vector((0.1, 0.0, 0.0)), Vector((0.9, 0.0, 0.0))], _RayPushOracle()
        params = {"margin": 0.0, "segment_collisions": True}
        pen = FiberSolver()._apply_segment_collision_constraints(nodes, [False, False], oracle, (_fake_collider(0),), params)
        self.assertGreater(pen, 0.0)
        self.assertGreater(oracle.pushes, 0)

    def test_recompute_fiber_rejects_unsafe_mid_touch_result(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        blocker, blocker_obj = _cube_scp(root_obj, "TouchBlocker", (1.0, 0.0, 0.0), 0.8)
        target_local = Vector((0.0, 0.0, 0.4))
        before = _fiber_points_world(fiber)
        touch = fiber.mid_touches.add()
        touch.parent_id = blocker.id
        touch.attach_param = capture_world_attachment(root_obj, blocker.id, blocker_obj.matrix_world @ target_local)
        _recompute_and_drain()
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        self.assertEqual(_fiber_points_world(fiber), before)
        self.assertEqual(proxy.get("af_fiber_output_state"), "STALE")

    def test_move_fiber_touch_point_reorders_handles_in_viewport(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        first = _append_touch(root_obj, fiber, "FirstMid", (0.75, 1.0, 0.0))
        second = _append_touch(root_obj, fiber, "SecondMid", (1.25, -1.0, 0.0))
        _sync_active_fiber(root_obj, fiber)
        select_only(find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id"))
        before = [_touch_handle(fiber.id, i).location.copy() for i in range(2)]
        self.assertEqual(bpy.ops.af.move_fiber_touch_point(fiber_id=fiber.id, touch_index=1, direction=-1), {"FINISHED"})
        after = [_touch_handle(fiber.id, i).location.copy() for i in range(2)]
        self.assertEqual([tp.parent_id for tp in fiber.mid_touches], [second.id, first.id])
        self.assertLess((after[0] - before[1]).length, 1.0e-6)
        self.assertLess((after[1] - before[0]).length, 1.0e-6)

    def test_recompute_fiber_active_collider_metric_filters_far_blockers(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        for i in range(8):
            _cube_scp(root_obj, f"Far{i}", (20.0, float(i) * 2.0, 0.0), 0.8)
        _recompute_and_drain()
        self.assertLess(fiber_active_colliders(fiber), 5)

    def test_new_fiber_defaults_surface_routing_off(self):
        _root_obj, fiber, _origin, _insert = _fiber_setup()
        self.assertTrue(hasattr(fiber, "use_warm_start"))
        self.assertTrue(fiber.use_warm_start)
        self.assertTrue(hasattr(fiber, "use_surface_routing"))
        self.assertFalse(fiber.use_surface_routing)
        self.assertTrue(hasattr(fiber, "use_segment_collisions"))
        self.assertFalse(fiber.use_segment_collisions)
        self.assertTrue(hasattr(fiber, "preview_planner_route"))
        self.assertFalse(fiber.preview_planner_route)

    def test_new_fiber_defaults_include_solver_version_and_rollback_state(self):
        _root_obj, fiber, _origin, _insert = _fiber_setup()
        self.assertEqual(fiber.solver_version, 1)
        self.assertAlmostEqual(fiber.collision_radius, 0.002)
        self.assertEqual((fiber.legacy_points_json, fiber.legacy_status), ("", ""))
        self.assertEqual((fiber.legacy_eps_disp, fiber.legacy_eps_pen), (0.0, 0.0))

    def test_new_fiber_v2_commit_updates_provenance_atomically(self):
        with patch.dict("os.environ", {"AF_FIBER_ENGINE": "V2"}):
            _root_obj, fiber, _origin, _insert = _fiber_setup()
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        self.assertEqual((fiber.solver_version, proxy.get("af_fiber_output_engine")), (2, "V2"))
        self.assertEqual(proxy.get("af_fiber_output_engine_version"), "fiber-v2-production-3")

    def test_bake_iteration_policy_edit_does_not_trigger_runtime(self):
        _root_obj, fiber, _origin, _insert = _fiber_setup()
        with patch.object(vcp_properties, "schedule_context") as schedule, patch.object(vcp_properties, "sync_context") as sync:
            fiber.iterations_bake += 1
        self.assertEqual((schedule.call_count, sync.call_count), (0, 0))

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
        with patch.object(fiber_view_capture, "view_ray_for_world_point", return_value=fiber_view_capture.NO_VIEW_RAY), patch.object(fiber_runtime, "resolve_conflict", return_value="ENDPOINT_RAW"):
            fiber_runtime.apply_fiber_control_update(sync, root_obj, bpy.context.scene, handle, bpy.context.evaluated_depsgraph_get())
        self.assertEqual(fiber.a_attach_param, "ENDPOINT_RAW")

    def test_touch_handle_update_uses_conflict_resolution(self):
        root_obj, fiber, origin, _insert = _fiber_setup()
        select_only(origin.geometry_object_ref)
        bpy.ops.af.add_fiber_touch_point()
        _sync_active_fiber(root_obj, fiber)
        sync = register_fiber_sync()
        handle = mark_touch_handle(empty_object("Touch"), root_obj, fiber.id, 0)
        with patch.object(fiber_view_capture, "view_ray_for_world_point", return_value=fiber_view_capture.NO_VIEW_RAY), patch.object(fiber_runtime, "resolve_conflict", return_value="TOUCH_RAW"):
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
        with patch.object(fiber_view_capture, "view_ray_for_world_point", return_value=fiber_view_capture.NO_VIEW_RAY), patch.object(fiber_runtime, "resolve_conflict", side_effect=lambda **kwargs: kwargs["incoming"]):
            fiber_runtime.apply_fiber_control_update(sync, root_obj, bpy.context.scene, handle, bpy.context.evaluated_depsgraph_get())
        target = origin.geometry_object_ref.matrix_world @ origin.geometry_object_ref.data.vertices[2].co
        actual = endpoint_world(root_obj, bpy.context.scene, {}, fiber.mid_touches[0].parent_id, fiber.mid_touches[0].attach_param)
        self.assertEqual(parse_fiber_attach_param(fiber.mid_touches[0].attach_param)[0], "surface_param_v2")
        self.assertLess((actual - target).length, 1.0e-6)

    def test_endpoint_handle_transfers_to_another_scp_surface(self):
        root_obj, fiber, _origin, insert = _fiber_setup()
        _sync_active_fiber(root_obj, fiber)
        handle = next(obj for obj in bpy.context.scene.objects if obj.get("af_fiber_endpoint") == "A")
        target = insert.geometry_object_ref.matrix_world @ insert.geometry_object_ref.data.vertices[1].co
        handle.location = target
        with patch.object(fiber_view_capture, "view_ray_for_world_point", return_value=fiber_view_capture.NO_VIEW_RAY):
            changed = fiber_runtime.apply_fiber_control_update(register_fiber_sync(), root_obj, bpy.context.scene, handle, bpy.context.evaluated_depsgraph_get())
        actual = endpoint_world(root_obj, bpy.context.scene, {}, fiber.a_parent_id, fiber.a_attach_param)
        self.assertEqual((changed, fiber.a_parent_id), (fiber.id, insert.id))
        self.assertLess((actual - target).length, 1.0e-6)

    def test_endpoint_transfer_uses_frontmost_visible_scp(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        front = scp_with_object(root_obj, "Front", mesh_object("Front", (0.0, 0.0, 1.0)))
        _sync_active_fiber(root_obj, fiber)
        handle = next(obj for obj in bpy.context.scene.objects if obj.get("af_fiber_endpoint") == "A")
        handle.location = Vector((0.2, 0.2, 1.0)); ray = (Vector((0.2, 0.2, 3.0)), Vector((0, 0, -1)))
        with patch.object(fiber_view_capture, "view_ray_for_world_point", return_value=ray):
            fiber_runtime.apply_fiber_control_update(register_fiber_sync(), root_obj, bpy.context.scene, handle, bpy.context.evaluated_depsgraph_get())
        actual = endpoint_world(root_obj, bpy.context.scene, {}, fiber.a_parent_id, fiber.a_attach_param)
        self.assertEqual(fiber.a_parent_id, front.id)
        self.assertAlmostEqual(actual.z, 1.0)

    def test_touch_handle_transfers_owner_and_preserves_offset(self):
        root_obj, fiber, origin, insert = _fiber_setup()
        _edit_select_vertex(origin.geometry_object_ref, 1); bpy.ops.af.add_fiber_touch_point(fiber_id=fiber.id)
        touch = fiber.mid_touches[0]; touch.normal_offset = 0.2; _sync_active_fiber(root_obj, fiber)
        handle = _touch_handle(fiber.id)
        target = insert.geometry_object_ref.matrix_world @ insert.geometry_object_ref.data.vertices[2].co
        handle.location = target
        with patch.object(fiber_view_capture, "view_ray_for_world_point", return_value=fiber_view_capture.NO_VIEW_RAY):
            fiber_runtime.apply_fiber_control_update(register_fiber_sync(), root_obj, bpy.context.scene, handle, bpy.context.evaluated_depsgraph_get())
        actual = endpoint_world(root_obj, bpy.context.scene, {}, touch.parent_id, touch.attach_param)
        self.assertEqual(touch.parent_id, insert.id)
        self.assertAlmostEqual(touch.normal_offset, 0.2)
        self.assertLess((actual - target).length, 1.0e-6)

    def test_ambiguous_equal_surface_keeps_current_owner(self):
        root_obj, fiber, origin, _insert = _fiber_setup()
        duplicate = scp_with_object(root_obj, "Duplicate", mesh_object("Duplicate"))
        _sync_active_fiber(root_obj, fiber)
        handle = next(obj for obj in bpy.context.scene.objects if obj.get("af_fiber_endpoint") == "A")
        handle.location = origin.geometry_object_ref.matrix_world @ origin.geometry_object_ref.data.vertices[1].co
        with patch.object(fiber_view_capture, "view_ray_for_world_point", return_value=fiber_view_capture.NO_VIEW_RAY):
            fiber_runtime.apply_fiber_control_update(register_fiber_sync(), root_obj, bpy.context.scene, handle, bpy.context.evaluated_depsgraph_get())
        self.assertNotEqual(origin.id, duplicate.id)
        self.assertEqual(fiber.a_parent_id, origin.id)

    def test_rejected_owner_transfer_keeps_attachment_atomic(self):
        root_obj, fiber, origin, insert = _fiber_setup(); before = fiber.a_attach_param
        _sync_active_fiber(root_obj, fiber)
        handle = next(obj for obj in bpy.context.scene.objects if obj.get("af_fiber_endpoint") == "A")
        handle.location = insert.geometry_object_ref.matrix_world @ insert.geometry_object_ref.data.vertices[1].co
        policy = lambda **row: row["current"] if row["aspect"].endswith(".owner") else row["incoming"]
        with patch.object(fiber_view_capture, "view_ray_for_world_point", return_value=fiber_view_capture.NO_VIEW_RAY), patch.object(fiber_runtime, "resolve_conflict", side_effect=policy):
            changed = fiber_runtime.apply_fiber_control_update(register_fiber_sync(), root_obj, bpy.context.scene, handle, bpy.context.evaluated_depsgraph_get())
        self.assertIsNone(changed)
        self.assertEqual((fiber.a_parent_id, fiber.a_attach_param), (origin.id, before))

    def test_fiber_update_projects_endpoint_handle_to_surface(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        handle = next(obj for obj in bpy.context.scene.objects if obj.get("af_fiber_endpoint_handle") and obj.get("af_fiber_endpoint") == "A")
        select_only(handle)
        handle.location += Vector((0.2, 0.2, 0.75))
        sync = register_fiber_sync()
        fiber_runtime.apply_fiber_control_update(sync, root_obj, bpy.context.scene, handle, bpy.context.evaluated_depsgraph_get())
        with patch.object(builtin_drivers, "_request_fiber_refinements"):
            builtin_drivers.FiberSyncDriver().sync(root_obj, bpy.context.scene, False, {"FIBER": {fiber.id}}, False, {"event_type": "FIBER_UPDATE"})
        target = endpoint_world(root_obj, bpy.context.scene, {}, fiber.a_parent_id, fiber.a_attach_param)
        self.assertLess((handle.location - target).length, 1.0e-6)

    def test_fiber_update_projects_touch_handle_to_surface(self):
        root_obj, fiber, _origin, _insert = _fiber_setup()
        _append_touch(root_obj, fiber, "Touch", (1.0, 1.0, 0.0))
        _sync_active_fiber(root_obj, fiber)
        handle = _touch_handle(fiber.id)
        select_only(handle)
        handle.location += Vector((0.2, 0.2, 0.75))
        fiber_runtime.apply_fiber_control_update(register_fiber_sync(), root_obj, bpy.context.scene, handle, bpy.context.evaluated_depsgraph_get())
        with patch.object(builtin_drivers, "_request_fiber_refinements"):
            builtin_drivers.FiberSyncDriver().sync(root_obj, bpy.context.scene, False, {"FIBER": {fiber.id}}, False, {"event_type": "FIBER_UPDATE"})
        touch = fiber.mid_touches[0]
        target = endpoint_world(root_obj, bpy.context.scene, {}, touch.parent_id, touch.attach_param)
        self.assertAlmostEqual(target.z, 0.0, places=6)
        self.assertLess((handle.location - target).length, 1.0e-6)

    def test_endpoint_capture_uses_first_camera_facing_surface(self):
        root_obj, fiber, origin, _insert = _fiber_setup()
        _set_stacked_surface(origin.geometry_object_ref)
        fiber.a_attach_param = capture_mesh_attachment(root_obj, origin, 0)
        _sync_active_fiber(root_obj, fiber)
        handle = next(obj for obj in bpy.context.scene.objects if obj.get("af_fiber_endpoint_handle") and obj.get("af_fiber_endpoint") == "A")
        handle.location = Vector((0.2, 0.2, 0.1))
        ray = (Vector((0.2, 0.2, 2.0)), Vector((0.0, 0.0, -1.0)))
        with patch.object(fiber_view_capture, "view_ray_for_world_point", return_value=ray):
            fiber_runtime.apply_fiber_control_update(register_fiber_sync(), root_obj, bpy.context.scene, handle, bpy.context.evaluated_depsgraph_get())
        actual = endpoint_world(root_obj, bpy.context.scene, {}, fiber.a_parent_id, fiber.a_attach_param)
        self.assertAlmostEqual(actual.z, 1.0, places=6)

    def test_camera_capture_rejects_a_back_facing_first_hit(self):
        _root_obj, _fiber, origin, _insert = _fiber_setup()
        _set_stacked_surface(origin.geometry_object_ref, reverse_front=True)
        ray = (Vector((0.2, 0.2, 2.0)), Vector((0.0, 0.0, -1.0)))
        raw = capture_attachment_from_object_ray(origin.geometry_object_ref, *ray)
        self.assertIsNone(raw)

    def test_view_ray_uses_active_viewport_through_control(self):
        region, rv3d = SimpleNamespace(type="WINDOW"), SimpleNamespace(view_location=Vector())
        context = SimpleNamespace(area=SimpleNamespace(type="VIEW_3D"), region=region,
                                  space_data=SimpleNamespace(region_3d=rv3d))
        with patch.object(fiber_view_capture.view3d_utils, "location_3d_to_region_2d", return_value=Vector((4, 5))), patch.object(
                fiber_view_capture.view3d_utils, "region_2d_to_origin_3d", return_value=Vector((0, 0, 3))), patch.object(
                fiber_view_capture.view3d_utils, "region_2d_to_vector_3d", return_value=Vector((0, 0, -2))):
            ray = fiber_view_capture.view_ray_for_world_point(Vector((0, 0, 1)), context)
        self.assertEqual((tuple(ray[0]), tuple(ray[1])), ((0.0, 0.0, 3.0), (0.0, 0.0, -1.0)))

    def test_view_capture_does_not_nearest_fallback_behind_camera(self):
        region, rv3d = SimpleNamespace(type="WINDOW"), SimpleNamespace(view_location=Vector())
        context = SimpleNamespace(area=SimpleNamespace(type="VIEW_3D"), region=region,
                                  space_data=SimpleNamespace(region_3d=rv3d))
        with patch.object(fiber_view_capture.view3d_utils, "location_3d_to_region_2d", return_value=None):
            ray = fiber_view_capture.view_ray_for_world_point(Vector((0, 0, 1)), context)
        self.assertIsNone(ray)

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
        before = _fiber_points_world(fiber)
        missing = scp_with_object(root_obj, "NoGeo", empty_object("NoGeo"), with_geometry=False)
        fiber.a_parent_id = missing.id
        fiber.a_attach_param = capture_mesh_attachment(root_obj, origin, 0)
        result = recompute_fiber_action(bpy.context, fiber.id)
        self.assertFalse(result.ok)
        self.assertEqual((fiber_recompute_status(fiber), fiber_invalid_reason(fiber)), ("INVALID_ATTACHMENT", "Missing parent geometry."))
        self.assertEqual(_fiber_points_world(fiber), before)
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        self.assertEqual(proxy.get("af_fiber_output_state"), "STALE")
        self.assertIsNone(cached_fiber_points(bpy.context.scene, root_obj.name, fiber.id))

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

    def test_v2_request_records_loop_compatibility_provenance(self):
        with patch.dict(os.environ, {"AF_FIBER_ENGINE": "V2"}):
            _root_obj, fiber, _loop = _loop_setup()
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        self.assertEqual((fiber.solver_version, proxy.get("af_fiber_output_engine")), (1, "V1"))
        self.assertEqual(proxy.get("af_fiber_requested_engine"), "V2")
        self.assertEqual(proxy.get("af_fiber_engine_fallback_reason"),
                         "V2_TOPOLOGY_COMPATIBILITY")

    def test_create_loop_fiber_suppresses_intermediate_prop_sync(self):
        root_obj = root()
        loop = scp_with_object(root_obj, "Loop", _loop_mesh_object("Loop"))
        _edit_select_vertex(loop.geometry_object_ref, 0, 1, 2, 3)
        with patch.object(vcp_properties, "sync_context") as sync:
            self.assertEqual(bpy.ops.af.create_loop_fiber_from_selected_vertices(), {"FINISHED"})
        self.assertEqual(sync.call_count, 0)

    def test_loop_fiber_follows_parent_scp_transform_change(self):
        root_obj, fiber, loop = _loop_setup()
        before = [point.copy() for point in _fiber_world_vectors(fiber)]
        loop.geometry_object_ref.location.x += 3.0
        bpy.context.view_layer.update()
        sync_from_dirty_hints(root=root_obj, scene=bpy.context.scene, dirty_hints=dirty_hints_for("SCP", {loop.id}))
        after = _fiber_world_vectors(fiber)
        self.assertLess((after[0] - before[0] - Vector((3.0, 0.0, 0.0))).length, 1.0e-6)

    def test_create_symmetric_loop_fiber_expands_selected_half(self):
        _root_obj, fiber, _loop = _symmetric_loop_setup()
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        points = _fiber_world_vectors(fiber)
        self.assertEqual((fiber.topology_mode, fiber.symmetry_mode, len(fiber.loop_anchors)), ("LOOP", "MIRROR_SEAM_LOOP", 3))
        self.assertEqual((fiber.symmetry_axis, tuple(round(v, 4) for v in fiber.symmetry_origin)), ("X", (0.0, 0.0, 0.0)))
        self.assertEqual(proxy.data.splines[0].use_cyclic_u, True)
        self.assertTrue(any(point.x < -0.25 for point in points))
        self.assertTrue(any(point.x > 0.25 for point in points))

    def test_v2_request_records_symmetric_loop_compatibility(self):
        with patch.dict(os.environ, {"AF_FIBER_ENGINE": "V2"}):
            _root_obj, fiber, _loop = _symmetric_loop_setup()
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        self.assertEqual((fiber.solver_version, proxy.get("af_fiber_output_engine")), (1, "V1"))
        self.assertEqual(proxy.get("af_fiber_engine_fallback_reason"),
                         "V2_TOPOLOGY_COMPATIBILITY")

    def test_v3_loop_commits_native_cyclic_output(self):
        with patch.dict(os.environ, {"AF_FIBER_ENGINE": "V3"}):
            _root_obj, fiber, _loop = _loop_setup(); fiber.node_count = 48
            _recompute_and_drain(fiber.id)
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        self.assertEqual((fiber.solver_version, proxy.get("af_fiber_output_engine")), (3, "V3"))
        self.assertEqual((len(_fiber_points_world(fiber)), proxy.data.splines[0].use_cyclic_u),
                         (48, True))
        self.assertFalse(proxy.get("af_fiber_engine_fallback_reason"))

    def test_v3_symmetric_loop_uses_global_cyclic_solver(self):
        with patch.dict(os.environ, {"AF_FIBER_ENGINE": "V3"}):
            root_obj, fiber, _loop = _symmetric_loop_setup(); _recompute_and_drain(fiber.id)
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        self.assertEqual((fiber.solver_version, proxy.get("af_fiber_output_engine")), (3, "V3"))
        self.assertTrue(proxy.data.splines[0].use_cyclic_u)
        self.assertFalse(proxy.get("af_fiber_engine_fallback_reason"))
        solver = register_fiber_sync()._solver
        _runtime, anchors, issue = solver._loop_anchors(
            root_obj, bpy.context.scene, bpy.context.evaluated_depsgraph_get(), fiber)
        self.assertFalse(issue); self.assertTrue(all(anchor.owner_id for anchor in anchors))

    def test_selected_loop_fiber_shows_anchor_handles(self):
        root_obj, fiber, _loop = _loop_setup()
        _sync_active_fiber(root_obj, fiber)
        count = sum(bool(obj.get("af_fiber_loop_anchor_handle") and obj.get("af_fiber_id") == fiber.id) for obj in bpy.context.scene.objects)
        self.assertEqual(count, len(fiber.loop_anchors))
        self.assertLess((_loop_anchor_handle(fiber.id, 0).location - Vector((0.0, 0.0, 0.0))).length, 1.0e-6)

    def test_loop_anchor_handle_move_recaptures_surface_mode(self):
        root_obj, fiber, loop = _loop_setup()
        _sync_active_fiber(root_obj, fiber)
        handle = _loop_anchor_handle(fiber.id, 0)
        select_only(handle)
        handle.location = loop.geometry_object_ref.matrix_world @ loop.geometry_object_ref.data.vertices[2].co
        sync = register_fiber_sync()
        sync._solver._cache[fiber.id] = [Vector((9.0, 9.0, 9.0))]
        with patch.object(fiber_view_capture, "view_ray_for_world_point", return_value=fiber_view_capture.NO_VIEW_RAY), patch.object(fiber_runtime, "resolve_conflict", side_effect=lambda **kwargs: kwargs["incoming"]):
            fiber_runtime.apply_fiber_control_update(sync, root_obj, bpy.context.scene, handle, bpy.context.evaluated_depsgraph_get())
        target = loop.geometry_object_ref.matrix_world @ loop.geometry_object_ref.data.vertices[2].co
        anchor = fiber.loop_anchors[0]
        actual = endpoint_world(root_obj, bpy.context.scene, {}, anchor.parent_id, anchor.attach_param)
        self.assertEqual(parse_fiber_attach_param(anchor.attach_param)[0], "surface_param_v2")
        self.assertFalse(_cache_has_point(sync, fiber.id, Vector((9.0, 9.0, 9.0))))
        self.assertLess(min((point - target).length for point in _fiber_world_vectors(fiber)), 1.0e-6)
        self.assertLess((actual - target).length, 1.0e-6)

    def test_loop_anchor_handle_transfers_to_another_scp(self):
        root_obj, fiber, _loop = _loop_setup()
        target_scp = scp_with_object(root_obj, "LoopTarget", mesh_object("LoopTarget", (3.0, 0.0, 0.0)))
        _sync_active_fiber(root_obj, fiber); handle = _loop_anchor_handle(fiber.id, 0)
        target = target_scp.geometry_object_ref.matrix_world @ target_scp.geometry_object_ref.data.vertices[1].co
        handle.location = target
        with patch.object(fiber_view_capture, "view_ray_for_world_point", return_value=fiber_view_capture.NO_VIEW_RAY):
            fiber_runtime.apply_fiber_control_update(register_fiber_sync(), root_obj, bpy.context.scene, handle, bpy.context.evaluated_depsgraph_get())
        anchor = fiber.loop_anchors[0]
        actual = endpoint_world(root_obj, bpy.context.scene, {}, anchor.parent_id, anchor.attach_param)
        self.assertEqual(anchor.parent_id, target_scp.id)
        self.assertLess((actual - target).length, 1.0e-6)

    def test_recompute_loop_fiber_preserves_node_count_and_hides_handles(self):
        root_obj, fiber, _loop = _loop_setup()
        fiber.node_count = 48
        _recompute_and_drain(fiber.id)
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
