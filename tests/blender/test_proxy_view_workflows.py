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

from _helpers import BlenderTestCase, empty_object, mesh_object, root, scp_with_object, select_only
from anthroforge.app.use_cases.proxy_view import switch_to_proxy_view
from anthroforge.core.attachment_codec import parse_fiber_attach_param
from anthroforge.core.scp_proxy import flush_proxy_session_runtime, run_proxy_session_guard
from anthroforge.core.scp_proxy.consts import ATTR_SLOT, ATTR_VERTEX, SIDE_MIRRORED
from anthroforge.core.scp_proxy.session import active_session
from anthroforge.core.scp_runtime.lookup import set_parent_relation
from anthroforge.core.visualization.fiber_sync import register_fiber_sync
from anthroforge.core.visualization.fiber_sync_helpers import endpoint_world
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


def _switch(obj):
    select_only(obj)
    return bpy.ops.af.switch_to_proxy_view()


def _session_proxy(root_obj, key):
    return bpy.data.objects.get(active_session(root_obj).get(key, ""))


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


def _attr(obj, name, index):
    return int(obj.data.attributes[name].data[index].value)


def _edit_select(obj, *indices):
    select_only(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    for vert in bm.verts:
        vert.select = False
    for index in indices:
        bm.verts[int(index)].select = True
    bmesh.update_edit_mesh(obj.data)


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

    def test_mirrored_proxy_matches_target_mirror_rule(self):
        root_obj, source, target = _mirror_setup()
        self.assertEqual(_switch(source.transform_object_ref), {"FINISHED"})
        mirrored = _session_proxy(root_obj, "mirrored")
        expected = tuple(mirror_matrix("X") @ vert for vert in _evaluated_world_verts(target.geometry_object_ref))
        verts = tuple((round(v.x, 4), round(v.y, 4), round(v.z, 4)) for v in _proxy_world_verts(mirrored))
        want = tuple((round(v.x, 4), round(v.y, 4), round(v.z, 4)) for v in expected)
        self.assertEqual(verts, want)

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

    def test_mesh_vertex_attach_returns_none_after_topology_change(self):
        root_obj, scp, mod = _subd_setup()
        self.assertEqual(_switch(scp.geometry_object_ref), {"FINISHED"})
        proxy = _session_proxy(root_obj, "original")
        _edit_select(proxy, 0, 1)
        self.assertEqual(bpy.ops.af.connect_proxy_vertices_with_fiber(), {"FINISHED"})
        fiber = root_obj.af_vcp_system.fibers[0]
        self.assertIsNotNone(endpoint_world(root_obj, bpy.context.scene, {}, fiber.a_parent_id, fiber.a_attach_param))
        mod.levels = 2
        self.assertIsNone(endpoint_world(root_obj, bpy.context.scene, {}, fiber.a_parent_id, fiber.a_attach_param))

    def test_connect_proxy_vertices_with_fiber_uses_mesh_vertex_mode(self):
        root_obj, parent, left, right = _proxy_setup()
        self.assertEqual(_switch(parent.transform_object_ref), {"FINISHED"})
        proxy = _session_proxy(root_obj, "original")
        _edit_select(proxy, _proxy_vertex_index(proxy, left.id, 1), _proxy_vertex_index(proxy, right.id, 2))
        self.assertEqual(bpy.ops.af.connect_proxy_vertices_with_fiber(), {"FINISHED"})
        fiber = root_obj.af_vcp_system.fibers[0]
        self.assertEqual((bpy.context.mode, bpy.context.active_object), ("EDIT_MESH", proxy))
        self.assertEqual((fiber.a_parent_id, fiber.b_parent_id), (left.id, right.id))
        self.assertEqual((parse_fiber_attach_param(fiber.a_attach_param), parse_fiber_attach_param(fiber.b_attach_param)), (("mesh_vertex_v1", 1), ("mesh_vertex_v1", 2)))
        start = endpoint_world(root_obj, bpy.context.scene, {}, fiber.a_parent_id, fiber.a_attach_param)
        left.geometry_object_ref.data.vertices[1].co.z = 1.25
        left.geometry_object_ref.data.update()
        moved = endpoint_world(root_obj, bpy.context.scene, {}, fiber.a_parent_id, fiber.a_attach_param)
        self.assertNotEqual(round(start.z, 4), round(moved.z, 4))

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
        self.assertEqual((fiber.a_parent_id, fiber.b_parent_id, parse_fiber_attach_param(fiber.a_attach_param)[0], mirror is not None), (target.id, target.id, "mesh_vertex_v1", True))
