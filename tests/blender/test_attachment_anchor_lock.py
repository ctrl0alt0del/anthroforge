from pathlib import Path
import sys

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bmesh
import bpy

from _helpers import BlenderTestCase, empty_object, root, scp_with_object, select_only
from app.queries.attachment_anchor_lock import child_anchor_lock_panel_state
from core.scp_runtime.attachment_runtime import capture_attachment_from_link, recapture_attachment_for_scp
from core.scp_runtime.child_anchor_lock import set_locked_child_anchor_index
from core.scp_runtime.lookup import set_parent_relation
from core.scp_runtime.runtime_state import attach_child_anchor_index


def _anchor_mesh(name):
    mesh = bpy.data.meshes.new(name)
    verts = [(-2, 0, 0), (-1, 0, 0), (-2, 1, 0), (-1, 1, 0), (1, 0, 0), (2, 0, 0), (1, 1, 0), (2, 1, 0)]
    mesh.from_pydata(verts, [], [(0, 1, 3, 2), (4, 5, 7, 6)])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _lock_fixture(mode):
    root_obj = root()
    parent = scp_with_object(root_obj, "Parent", empty_object("Parent", (-1.9, 0.0, 0.0)), with_geometry=False)
    child = scp_with_object(root_obj, "Child", _anchor_mesh("Child"))
    child.attach_parent_anchor_mode, child.attach_child_anchor_mode = "OBJECT_ORIGIN", mode
    set_parent_relation(child.transform_object_ref, child, parent.transform_object_ref)
    capture_attachment_from_link(child, child.transform_object_ref, child.geometry_object_ref, parent.transform_object_ref, None)
    return root_obj, parent, child


def _edit_mesh(obj):
    select_only(obj)
    bpy.ops.object.mode_set(mode="EDIT")


def _select_vertex(obj, index):
    _edit_mesh(obj)
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    for face in bm.faces:
        face.select = False
    for vert in bm.verts:
        vert.select = False
    bm.verts[index].select = True
    bmesh.update_edit_mesh(obj.data)


def _select_face(obj, index):
    _edit_mesh(obj)
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    for vert in bm.verts:
        vert.select = False
    for face in bm.faces:
        face.select = False
    bm.faces[index].select = True
    bmesh.update_edit_mesh(obj.data)


def _object_mode():
    bpy.ops.object.mode_set(mode="OBJECT") if bpy.context.mode != "OBJECT" else None


class AttachmentAnchorLockTests(BlenderTestCase):
    def tearDown(self):
        _object_mode()
        super().tearDown()

    def test_vertex_lock_operator_keeps_locked_anchor_until_cleared(self):
        root_obj, parent, child = _lock_fixture("VERTEX_NEAREST")
        _select_vertex(child.geometry_object_ref, 0)
        state = child_anchor_lock_panel_state(bpy.context, child)
        self.assertEqual((state.can_set, state.selected_index), (True, 0))
        self.assertEqual(bpy.ops.af.set_scp_child_anchor_lock(), {"FINISHED"})
        self.assertEqual((bpy.context.mode, child.attach_child_vertex_lock_index), ("EDIT_MESH", 0))
        _object_mode()
        parent.transform_object_ref.location = (2.0, 0.0, 0.0)
        self.assertTrue(recapture_attachment_for_scp(root_obj, bpy.context.scene, child.id))
        self.assertEqual(attach_child_anchor_index(child), 0)
        self.assertEqual(bpy.ops.af.clear_scp_child_anchor_lock(), {"FINISHED"})
        self.assertEqual(child.attach_child_vertex_lock_index, -1)
        bpy.context.view_layer.update()
        self.assertEqual(attach_child_anchor_index(child), 5)

    def test_face_lock_operator_keeps_locked_anchor_until_cleared(self):
        root_obj, parent, child = _lock_fixture("FACE_CENTER")
        parent.transform_object_ref.location = (-1.5, 0.5, 0.0)
        self.assertTrue(recapture_attachment_for_scp(root_obj, bpy.context.scene, child.id))
        _select_face(child.geometry_object_ref, 0)
        state = child_anchor_lock_panel_state(bpy.context, child)
        self.assertEqual((state.can_set, state.selected_index), (True, 0))
        self.assertEqual(bpy.ops.af.set_scp_child_anchor_lock(), {"FINISHED"})
        _object_mode()
        parent.transform_object_ref.location = (1.5, 0.5, 0.0)
        self.assertTrue(recapture_attachment_for_scp(root_obj, bpy.context.scene, child.id))
        self.assertEqual(attach_child_anchor_index(child), 0)
        self.assertEqual(bpy.ops.af.clear_scp_child_anchor_lock(), {"FINISHED"})
        bpy.context.view_layer.update()
        self.assertEqual(attach_child_anchor_index(child), 1)

    def test_invalid_lock_state_is_reported_and_can_be_replaced(self):
        _root_obj, _parent, child = _lock_fixture("VERTEX_NEAREST")
        set_locked_child_anchor_index(child, "VERTEX_NEAREST", 99)
        _select_vertex(child.geometry_object_ref, 1)
        state = child_anchor_lock_panel_state(bpy.context, child)
        self.assertEqual((state.invalid_lock, state.can_set, state.has_lock), (True, True, True))
        self.assertEqual(bpy.ops.af.set_scp_child_anchor_lock(), {"FINISHED"})
        self.assertEqual(child.attach_child_vertex_lock_index, 1)
