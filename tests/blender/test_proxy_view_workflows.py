from pathlib import Path
import json
import sys

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bmesh
import bpy
from mathutils import Vector

from _helpers import BlenderTestCase, empty_object, fiber, find_flagged, mesh_object, root, scp_with_object, select_only, temp_blend_path
from anthroforge.app.use_cases.proxy_view import switch_to_proxy_view
from anthroforge.core.attachment_codec import parse_fiber_attach_param
from anthroforge.core.scp_proxy import flush_proxy_session_runtime, run_proxy_session_guard
from anthroforge.core.scp_proxy.consts import ATTR_SLOT, ATTR_VERTEX, SIDE_MIRRORED
from anthroforge.core.scp_proxy.session import active_session
from anthroforge.core.scp_runtime.lookup import set_parent_relation
from anthroforge.core.scp_runtime.mirror_roles import apply_scp_mirror_roles
from anthroforge.core.scp_runtime import viewport_picker
from anthroforge.core.utils import get_af_root
from anthroforge.core.visualization.fiber_sync import register_fiber_sync
from anthroforge.core.visualization.fiber_sync_helpers import endpoint_world
from anthroforge.core.visualization.fiber_refinement import drain_fiber_refinements
from anthroforge.core.visualization.mirror_rules import mirror_matrix
from anthroforge.core.visualization.vcp_mirror_runtime import sync_vcp_mirrors


def _object_mode():
    bpy.ops.object.mode_set(mode="OBJECT") if bpy.context.mode != "OBJECT" else None


def _proxy_setup():
    root_obj = root()
    parent = scp_with_object(root_obj, "Parent", empty_object("Parent"), with_geometry=False)
    left = scp_with_object(root_obj, "Left", mesh_object("Left"))
    right = scp_with_object(root_obj, "Right", mesh_object("Right", (3.0, 0.0, 0.0)))
    set_parent_relation(left.transform_object_ref, left, parent.transform_object_ref)
    set_parent_relation(right.transform_object_ref, right, parent.transform_object_ref)
    return root_obj, parent, left, right


def _mirror_setup():
    root_obj = root()
    source = scp_with_object(root_obj, "Source", empty_object("Source"), with_geometry=False)
    target = scp_with_object(root_obj, "Target", mesh_object("Target", (2.0, 0.0, 0.0)))
    set_parent_relation(target.transform_object_ref, target, source.transform_object_ref)
    source.mirror_enabled = True
    return root_obj, source, target


def _empty_scp(root_obj, name):
    return scp_with_object(root_obj, name, empty_object(name), with_geometry=False)


def _subd_setup():
    root_obj = root()
    scp = scp_with_object(root_obj, "Subd", mesh_object("Subd"))
    mod = scp.geometry_object_ref.modifiers.new("Subd", "SUBSURF")
    mod.levels = 1
    return root_obj, scp, mod


def _cube_proxy_setup():
    root_obj = root()
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0.0, 0.0, 0.0))
    scp = scp_with_object(root_obj, "Cube", bpy.context.active_object)
    _switch(scp.geometry_object_ref)
    return root_obj, scp, _session_proxy(root_obj, "original")


def _switch(obj):
    select_only(obj)
    return bpy.ops.af.switch_to_proxy_view()


def _session_proxy(root_obj, key):
    return bpy.data.objects.get(active_session(root_obj).get(key, ""))


def _session_hidden(root_obj):
    for name in active_session(root_obj).get("hidden_object_names", []):
        obj = bpy.context.scene.objects.get(name)
        yield obj is not None and obj.hide_get()


def _proxy_world_verts(obj):
    return tuple(obj.matrix_world @ vert.co.copy() for vert in obj.data.vertices)


def _evaluated_world_verts(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    obj_eval = obj.evaluated_get(depsgraph)
    mesh = obj_eval.to_mesh()
    try:
        return tuple(obj.matrix_world @ vert.co.copy() for vert in mesh.vertices)
    finally:
        obj_eval.to_mesh_clear()


def _proxy_vertex_index(obj, scp_id, source_vertex):
    slot = _slot_for_scp(obj, scp_id)
    return next(i for i in range(len(obj.data.vertices)) if _attr(obj, ATTR_SLOT, i) == slot and _attr(obj, ATTR_VERTEX, i) == source_vertex)


def _slot_for_scp(obj, scp_id):
    data = json.loads(str(obj.get("af_scp_proxy_sources_json", "[]") or "[]"))
    return next(int(row["slot"]) for row in data if str(row.get("scp_id", "")) == str(scp_id))


def _scp_named(root_obj, name):
    return next(item for item in root_obj.af_scp_system.scps if str(item.name or "") == str(name))


def _attr(obj, name, index):
    return int(obj.data.attributes[name].data[index].value)


def _poly_center_world(obj, face_index=0):
    poly = obj.data.polygons[int(face_index)]
    verts = [obj.matrix_world @ obj.data.vertices[int(i)].co.copy() for i in poly.vertices]
    return sum(verts, Vector()) / float(len(verts))


def _modal_proxy_hit(root_obj, obj, face_index=0):
    center = _poly_center_world(obj, face_index)
    row = viewport_picker.candidate_for_object(root_obj, obj)
    hit = viewport_picker.raycast_world(center + Vector((0.0, 0.0, 2.0)), Vector((0.0, 0.0, -1.0)), (row,))
    return None if hit is None else hit[:2]


def _fiber_points_world(fiber_id):
    obj = find_flagged("af_fiber_proxy", fiber_id, "af_fiber_id")
    return [] if obj is None else [Vector(point) for point in json.loads(obj["af_fiber_points_world"])]


def _fiber_curve_points_world(fiber_id):
    obj = find_flagged("af_fiber_proxy", fiber_id, "af_fiber_id")
    splines = () if obj is None else tuple(obj.data.splines)
    if not splines:
        return []
    return [obj.matrix_world @ point.co.xyz for point in splines[0].points]


def _vcp_collection():
    collection = bpy.context.scene.collection.children.get("AF_VCP_VIS")
    if collection is None:
        collection = bpy.data.collections.new("AF_VCP_VIS")
        bpy.context.scene.collection.children.link(collection)
    return collection


def _source_fiber_proxy(root_obj, item):
    curve = bpy.data.curves.new("FiberSource", "CURVE")
    curve.dimensions = "3D"
    spline = curve.splines.new("POLY")
    spline.points.add(1)
    spline.points[0].co, spline.points[1].co = (0, 0, 0, 1), (1, 1, 0, 1)
    obj = bpy.data.objects.new("FiberSource", curve)
    _vcp_collection().objects.link(obj)
    obj["af_fiber_proxy"], obj["af_root_name"] = True, root_obj.name
    obj["af_fiber_id"], obj["af_fiber_output_state"] = item.id, "CURRENT"
    return obj


def _curve_coords(obj):
    return tuple(tuple(float(value) for value in point.co) for spline in obj.data.splines for point in spline.points)


def _polyline_has_interior_samples(points, limit=1.0, steps=4):
    for i in range(len(points) - 1):
        for step in range(1, steps + 1):
            point = points[i].lerp(points[i + 1], step / float(steps + 1))
            if all(-limit < value < limit for value in (point.x, point.y, point.z)):
                return True
    return False


def _edit_select(obj, *indices):
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


def _assert_attach_moves(root_obj, fiber, scp, index):
    start = endpoint_world(root_obj, bpy.context.scene, {}, fiber.a_parent_id, fiber.a_attach_param)
    scp.geometry_object_ref.data.vertices[int(index)].co.z = 1.25
    scp.geometry_object_ref.data.update()
    moved = endpoint_world(root_obj, bpy.context.scene, {}, fiber.a_parent_id, fiber.a_attach_param)
    return round(start.z, 4), round(moved.z, 4)


class ProxyViewWorkflowTests(BlenderTestCase):
    def tearDown(self):
        _object_mode()
        super().tearDown()

    def test_switch_to_proxy_view_builds_and_restores_hidden_scope(self):
        root_obj, source, target = _mirror_setup()
        target.geometry_object_ref.hide_set(True)
        self.assertEqual(_switch(source.transform_object_ref), {"FINISHED"})
        original = _session_proxy(root_obj, "original")
        mirrored = _session_proxy(root_obj, "mirrored")
        original_name = original.name
        self.assertEqual((original is not None, mirrored is not None), (True, True))
        self.assertTrue(source.transform_object_ref.hide_get())
        self.assertEqual(bpy.ops.af.exit_proxy_view(), {"FINISHED"})
        self.assertTrue(target.geometry_object_ref.hide_get())
        self.assertFalse(source.transform_object_ref.hide_get())
        self.assertIsNone(bpy.data.objects.get(original_name))

    def test_proxy_view_rehides_scope_after_reload(self):
        path = temp_blend_path()
        self.addCleanup(lambda: Path(path).unlink(missing_ok=True))
        root_obj, parent, left, _right = _proxy_setup()
        self.assertEqual(_switch(parent.transform_object_ref), {"FINISHED"})
        bpy.ops.wm.save_as_mainfile(filepath=path)
        bpy.ops.wm.open_mainfile(filepath=path, load_ui=False)
        root_obj = get_af_root(bpy.context.scene)
        parent = _scp_named(root_obj, "Parent")
        left = _scp_named(root_obj, "Left")
        self.assertTrue(bool(active_session(root_obj)))
        self.assertTrue(parent.transform_object_ref.hide_get())
        self.assertTrue(left.geometry_object_ref.hide_get())

    def test_mirrored_proxy_matches_target_mirror_rule(self):
        root_obj, source, target = _mirror_setup()
        self.assertEqual(_switch(source.transform_object_ref), {"FINISHED"})
        mirrored = _session_proxy(root_obj, "mirrored")
        expected = tuple(mirror_matrix("X") @ vert for vert in _evaluated_world_verts(target.geometry_object_ref))
        verts = tuple((round(v.x, 4), round(v.y, 4), round(v.z, 4)) for v in _proxy_world_verts(mirrored))
        want = tuple((round(v.x, 4), round(v.y, 4), round(v.z, 4)) for v in expected)
        self.assertEqual(verts, want)

    def test_create_loop_from_proxy_rehides_mirror_scope(self):
        root_obj, source, _target = _mirror_setup()
        self.assertEqual(_switch(source.transform_object_ref), {"FINISHED"})
        proxy = _session_proxy(root_obj, "original")
        _edit_select(proxy, 0, 1, 2)
        self.assertEqual(bpy.ops.af.create_loop_fiber_from_selected_vertices(), {"FINISHED"})
        self.assertTrue(all(_session_hidden(root_obj)))

    def test_failed_proxy_build_keeps_existing_session(self):
        root_obj, parent, _left, _right = _proxy_setup()
        self.assertEqual(_switch(parent.transform_object_ref), {"FINISHED"})
        original_name = active_session(root_obj).get("original", "")
        empty = _empty_scp(root_obj, "Empty")
        select_only(empty.transform_object_ref)
        self.assertFalse(switch_to_proxy_view(bpy.context).ok)
        self.assertEqual(active_session(root_obj).get("original", ""), original_name)
        self.assertIsNotNone(bpy.data.objects.get(original_name))

    def test_subdivision_modifier_builds_proxy_from_evaluated_mesh(self):
        root_obj, scp, _mod = _subd_setup()
        self.assertEqual(_switch(scp.geometry_object_ref), {"FINISHED"})
        proxy = _session_proxy(root_obj, "original")
        self.assertGreater(len(proxy.data.vertices), len(scp.geometry_object_ref.data.vertices))

    def test_proxy_session_exits_when_topology_changes(self):
        root_obj, scp, mod = _subd_setup()
        self.assertEqual(_switch(scp.geometry_object_ref), {"FINISHED"})
        proxy_name = _session_proxy(root_obj, "original").name
        mod.levels = 2
        run_proxy_session_guard(bpy.context.scene, force=True)
        flush_proxy_session_runtime()
        self.assertEqual(active_session(root_obj), {})
        self.assertFalse(scp.geometry_object_ref.hide_get())
        self.assertIsNone(bpy.data.objects.get(proxy_name))

    def test_surface_attach_survives_proxy_topology_change(self):
        root_obj, scp, mod = _subd_setup()
        self.assertEqual(_switch(scp.geometry_object_ref), {"FINISHED"})
        proxy = _session_proxy(root_obj, "original")
        _edit_select(proxy, 0, 1)
        self.assertEqual(bpy.ops.af.connect_proxy_vertices_with_fiber(), {"FINISHED"})
        fiber = root_obj.af_vcp_system.fibers[0]
        self.assertEqual(parse_fiber_attach_param(fiber.a_attach_param)[0], "surface_param_v2")
        mod.levels = 2
        self.assertIsNotNone(endpoint_world(root_obj, bpy.context.scene, {}, fiber.a_parent_id, fiber.a_attach_param))

    def test_connect_proxy_vertices_with_fiber_writes_surface_mode(self):
        root_obj, parent, left, right = _proxy_setup()
        self.assertEqual(_switch(parent.transform_object_ref), {"FINISHED"})
        proxy = _session_proxy(root_obj, "original")
        _edit_select(proxy, _proxy_vertex_index(proxy, left.id, 1), _proxy_vertex_index(proxy, right.id, 2))
        self.assertEqual(bpy.ops.af.connect_proxy_vertices_with_fiber(), {"FINISHED"})
        fiber = root_obj.af_vcp_system.fibers[0]; fiber_proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        self.assertEqual((bpy.context.mode, bpy.context.active_object), ("EDIT_MESH", proxy))
        self.assertEqual((fiber.a_parent_id, fiber.b_parent_id), (left.id, right.id))
        self.assertEqual((fiber_proxy is not None, len(fiber_proxy.data.splines) if fiber_proxy else 0), (True, 1))
        self.assertEqual((parse_fiber_attach_param(fiber.a_attach_param)[0], parse_fiber_attach_param(fiber.b_attach_param)[0]), ("surface_param_v2", "surface_param_v2"))
        self.assertNotEqual(*_assert_attach_moves(root_obj, fiber, left, 1))

    def test_connect_proxy_vertices_with_fiber_uses_middle_vertices_as_touch_points(self):
        root_obj, parent, left, right = _proxy_setup()
        middle = scp_with_object(root_obj, "Middle", mesh_object("Middle", (1.5, 0.0, 0.0)))
        set_parent_relation(middle.transform_object_ref, middle, parent.transform_object_ref)
        self.assertEqual(_switch(parent.transform_object_ref), {"FINISHED"})
        proxy = _session_proxy(root_obj, "original")
        _edit_select(proxy, _proxy_vertex_index(proxy, left.id, 1), _proxy_vertex_index(proxy, middle.id, 0), _proxy_vertex_index(proxy, right.id, 2))
        self.assertEqual(bpy.ops.af.connect_proxy_vertices_with_fiber(), {"FINISHED"})
        fiber = root_obj.af_vcp_system.fibers[0]
        self.assertEqual((fiber.a_parent_id, fiber.b_parent_id, len(fiber.mid_touches)), (left.id, right.id, 1))
        self.assertEqual((fiber.mid_touches[0].parent_id, parse_fiber_attach_param(fiber.mid_touches[0].attach_param)[0]), (middle.id, "surface_param_v2"))

    def test_add_fiber_touch_point_uses_selected_proxy_vertex(self):
        root_obj, parent, left, right = _proxy_setup()
        bpy.context.scene.af_new_fiber_origin_obj = left.geometry_object_ref
        bpy.context.scene.af_new_fiber_insertion_obj = right.geometry_object_ref
        bpy.ops.af.add_fiber_vcp()
        fiber = root_obj.af_vcp_system.fibers[0]
        self.assertEqual(_switch(parent.transform_object_ref), {"FINISHED"})
        proxy = _session_proxy(root_obj, "original")
        _edit_select(proxy, _proxy_vertex_index(proxy, left.id, 0))
        self.assertEqual(bpy.ops.af.add_fiber_touch_point(fiber_id=fiber.id), {"FINISHED"})
        self.assertEqual((len(fiber.mid_touches), fiber.mid_touches[0].parent_id), (1, left.id))
        self.assertEqual(parse_fiber_attach_param(fiber.mid_touches[0].attach_param)[0], "surface_param_v2")

    def test_modal_touch_picker_accepts_original_proxy_surface(self):
        root_obj, parent, left, _right = _proxy_setup()
        self.assertEqual(_switch(parent.transform_object_ref), {"FINISHED"})
        proxy = _session_proxy(root_obj, "original")
        self.assertTrue(any(row[1] == proxy for row in viewport_picker.pick_candidates(bpy.context, root_obj)))
        hit = _modal_proxy_hit(root_obj, proxy)
        self.assertEqual(hit[0], left.id)
        self.assertLess((hit[1] - _poly_center_world(left.geometry_object_ref)).length, 1.0e-6)

    def test_modal_touch_picker_unmirrors_mirrored_proxy_surface(self):
        root_obj, source, target = _mirror_setup()
        self.assertEqual(_switch(source.transform_object_ref), {"FINISHED"})
        hit = _modal_proxy_hit(root_obj, _session_proxy(root_obj, "mirrored"))
        self.assertEqual(hit[0], target.id)
        self.assertLess((hit[1] - _poly_center_world(target.geometry_object_ref)).length, 1.0e-6)

    def test_connect_proxy_vertices_with_fiber_keeps_cube_body_diagonal_on_surface(self):
        root_obj, cube, proxy = _cube_proxy_setup()
        _edit_select(proxy, _proxy_vertex_index(proxy, cube.id, 0), _proxy_vertex_index(proxy, cube.id, 7))
        self.assertEqual(bpy.ops.af.connect_proxy_vertices_with_fiber(), {"FINISHED"})
        fiber = root_obj.af_vcp_system.fibers[0]
        proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
        preview = _fiber_curve_points_world(fiber.id)
        self.assertEqual(proxy.get("af_fiber_output_state"), "STALE")
        self.assertFalse(proxy.get("af_fiber_points_world"))
        self.assertFalse(_polyline_has_interior_samples(preview, limit=0.99))
        _object_mode()
        self.assertEqual(bpy.ops.af.recompute_fiber(fiber_id=fiber.id), {"FINISHED"})
        self.assertTrue(drain_fiber_refinements())
        retained = _fiber_curve_points_world(fiber.id)
        self.assertEqual(len(retained), len(preview))
        self.assertEqual(proxy.get("af_fiber_display_mode"), "FAILED_PREVIEW")
        self.assertFalse(_polyline_has_interior_samples(retained, limit=0.99))

    def test_mirrored_proxy_selection_maps_back_to_target_scp(self):
        root_obj, source, target = _mirror_setup()
        self.assertEqual(_switch(source.transform_object_ref), {"FINISHED"})
        mirrored = _session_proxy(root_obj, "mirrored")
        a = _proxy_vertex_index(mirrored, target.id, 0)
        b = _proxy_vertex_index(mirrored, target.id, 2)
        _edit_select(mirrored, a, b)
        self.assertEqual(bpy.ops.af.connect_proxy_vertices_with_fiber(), {"FINISHED"})
        fiber = root_obj.af_vcp_system.fibers[0]
        _object_mode()
        register_fiber_sync().sync_root_to_scene(root=root_obj, scene=bpy.context.scene)
        sync_vcp_mirrors(root=root_obj, scene=bpy.context.scene, target_fiber_ids={fiber.id})
        mirror = next(obj for obj in bpy.context.scene.objects if obj.get("af_fiber_mirror_proxy") and obj.get("af_source_fiber_id") == fiber.id)
        self.assertEqual((fiber.a_parent_id, fiber.b_parent_id, parse_fiber_attach_param(fiber.a_attach_param)[0], mirror is not None), (target.id, target.id, "surface_param_v2", True))

    def test_stale_fiber_preserves_last_good_mirror(self):
        root_obj, _source, target = _mirror_setup()
        apply_scp_mirror_roles(root_obj)
        item = fiber(root_obj, target.id, target.id)
        proxy = _source_fiber_proxy(root_obj, item)
        sync_vcp_mirrors(root_obj, bpy.context.scene, target_fiber_ids={item.id})
        mirror = next(obj for obj in bpy.context.scene.objects if obj.get("af_fiber_mirror_proxy"))
        before = _curve_coords(mirror)
        proxy.data.splines[0].points[0].co.x += 5.0
        proxy["af_fiber_output_state"] = "STALE"
        sync_vcp_mirrors(root_obj, bpy.context.scene, target_fiber_ids={item.id})
        retained = next(obj for obj in bpy.context.scene.objects if obj.get("af_fiber_mirror_proxy"))
        self.assertEqual((retained is mirror, _curve_coords(retained)), (True, before))
