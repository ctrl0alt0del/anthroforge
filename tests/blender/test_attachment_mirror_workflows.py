from pathlib import Path
import sys

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy
from mathutils import Vector

from _helpers import BlenderTestCase, empty_object, find_flagged, mesh_object, root, scp_with_object
from anthroforge.core.local_transform_props import create_local_transform_props
from anthroforge.core.scp_runtime.bound_objects import find_bound_entry_by_object, sync_scp_roles
from anthroforge.core.scp_runtime import sync_runtime
from anthroforge.core.scp_runtime.lookup import set_parent_relation
from anthroforge.core.scp_runtime.common import scp_prop_map
from anthroforge.core.scp_runtime.actions import execute_reparent_scp
from anthroforge.core.scp_runtime.attachment_runtime import _resolved_tangent_strategy, apply_scp_attachments, capture_attachment_from_link, capture_dirty_scp_attachments
from anthroforge.core.scp_runtime.mirror_roles import apply_scp_mirror_roles
from anthroforge.core.scp_runtime.runtime_state import attach_child_anchor_index, attach_child_origin_local
from anthroforge.core.scp_runtime.mirror_scene import sync_mirrors
from anthroforge.core.scp_runtime.object_roles import add_bound_object_to_scp
from anthroforge.core.visualization.mirror_rules import mirror_matrix
from anthroforge.core.visualization.sync import register_sync


class DummyOperator:
    def report(self, _level, _message):
        return None


def _round_xyz(obj):
    return tuple(round(value, 4) for value in obj.location)


def _apply_parent(root_obj, parent):
    bpy.context.view_layer.update()
    return apply_scp_attachments(None, root_obj, bpy.context.scene, scp_prop_map(root_obj), parent_ids={parent.id})


def _surface_setup(child_mode="FACE_CENTER", child_loc=(0.2, 0.2, 0.5)):
    root_obj = root()
    parent = scp_with_object(root_obj, "Parent", mesh_object("Parent"))
    child = scp_with_object(root_obj, "Child", mesh_object("Child", child_loc))
    child.attach_parent_anchor_mode, child.attach_child_anchor_mode = "SURFACE_NEAREST", child_mode
    set_parent_relation(child.transform_object_ref, child, parent.transform_object_ref)
    capture_attachment_from_link(child, child.transform_object_ref, child.geometry_object_ref, parent.transform_object_ref, parent.geometry_object_ref)
    return root_obj, parent, child


def _curve_object(name):
    curve = bpy.data.curves.new(name, "CURVE")
    spline = curve.splines.new("POLY")
    spline.points.add(1)
    spline.points[0].co, spline.points[1].co = (0.0, 0.0, 0.0, 1.0), (0.0, 2.0, 0.0, 1.0)
    obj = bpy.data.objects.new(name, curve)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _world_verts(obj):
    return tuple(obj.matrix_world @ vert.co.copy() for vert in obj.data.vertices)


def _max_delta(a, b):
    return max((((va - vb).length) for va, vb in zip(a, b)), default=0.0)


def _matrix_delta(a, b):
    return max((abs(a[i][j] - b[i][j]) for i in range(4) for j in range(4)), default=0.0)


def _find_mirror_bound(scp_id, bound_id):
    for obj in bpy.context.scene.objects:
        same_scp = obj.get("af_source_scp_id") == scp_id
        same_bound = obj.get("af_source_bound_id") == bound_id
        if obj.get("af_scp_mirror") and same_scp and same_bound:
            return obj
    return None


def _hooked_curve_scp(root_obj, name, parent_id, hook_obj):
    scp = scp_with_object(root_obj, name, _curve_object(name), with_geometry=False)
    scp.parent_id = parent_id
    scp.transform_object_ref.modifiers.new("Hook", "HOOK").object = hook_obj
    return scp


class AttachmentMirrorWorkflowTests(BlenderTestCase):
    def test_surface_attachment_capture_tracks_parent_mesh_motion(self):
        root_obj, parent, child = _surface_setup()
        parent.transform_object_ref.location.z = 2.0
        _apply_parent(root_obj, parent)
        self.assertGreater(round(child.transform_object_ref.location.z, 4), 2.0)

    def test_follow_rotation_on_rotates_child_with_parent(self):
        root_obj = root()
        parent = scp_with_object(root_obj, "Parent", empty_object("Parent"), with_geometry=False)
        child_obj = empty_object("Child", (1.0, 0.0, 0.0))
        child = scp_with_object(root_obj, "Child", child_obj, with_geometry=False)
        child.attach_child_anchor_mode, child.attach_parent_anchor_mode = "OBJECT_ORIGIN", "OBJECT_ORIGIN"
        set_parent_relation(child_obj, child, parent.transform_object_ref)
        capture_attachment_from_link(child, child_obj, None, parent.transform_object_ref, None)
        parent.transform_object_ref.rotation_euler.z = 1.5708
        _apply_parent(root_obj, parent)
        axis = child_obj.matrix_world.to_quaternion() @ Vector((1.0, 0.0, 0.0))
        self.assertEqual(_round_xyz(child_obj), (0.0, 1.0, 0.0))
        self.assertGreater(round(axis.y, 4), 0.99)

    def test_follow_rotation_off_preserves_child_rotation(self):
        root_obj = root()
        parent = scp_with_object(root_obj, "Parent", empty_object("Parent"), with_geometry=False)
        child_obj = empty_object("Child", (2.0, 0.0, 0.0))
        child = scp_with_object(root_obj, "Child", child_obj, with_geometry=False)
        child.attach_child_anchor_mode, child.attach_parent_anchor_mode = "OBJECT_ORIGIN", "OBJECT_ORIGIN"
        child.attach_follow_rotation = False
        child_obj.rotation_euler.z = 0.4
        set_parent_relation(child_obj, child, parent.transform_object_ref)
        capture_attachment_from_link(child, child_obj, None, parent.transform_object_ref, None)
        parent.transform_object_ref.rotation_euler.z = 1.2
        _apply_parent(root_obj, parent)
        self.assertEqual((round(child_obj.rotation_euler.z, 4), _round_xyz(child_obj)[0]), (0.4, 0.7247))

    def test_surface_attachment_tracks_parent_scale(self):
        root_obj, parent, child = _surface_setup(child_mode="VERTEX_NEAREST")
        start = round(child.transform_object_ref.location.x, 4)
        parent.transform_object_ref.scale.x = 2.0
        _apply_parent(root_obj, parent)
        self.assertGreater(round(child.transform_object_ref.location.x, 4), start)

    def test_surface_attachment_tracks_parent_vertex_reposition(self):
        root_obj, parent, child = _surface_setup()
        start = _round_xyz(child.transform_object_ref)
        parent.geometry_object_ref.data.vertices[0].co.z = 1.5
        parent.geometry_object_ref.data.update()
        _apply_parent(root_obj, parent)
        self.assertNotEqual(_round_xyz(child.transform_object_ref), start)

    def test_tangent_strategy_resolution_covers_auto_stable_and_flow(self):
        _root_obj, parent, child = _surface_setup()
        guide = _curve_object("Guide")
        mod = parent.geometry_object_ref.modifiers.new("Curve", "CURVE")
        mod.object, mod.deform_axis = guide, "POS_Y"
        self.assertEqual(_resolved_tangent_strategy(child, parent.geometry_object_ref), "DEFORMATION_FLOW")
        child.attach_tangent_strategy = "STABLE_SURFACE"
        self.assertEqual(_resolved_tangent_strategy(child, parent.geometry_object_ref), "STABLE_SURFACE")
        child.attach_tangent_strategy = "DEFORMATION_FLOW"
        self.assertEqual(_resolved_tangent_strategy(child, parent.geometry_object_ref), "DEFORMATION_FLOW")

    def test_multi_level_attachment_refreshes_child_chain(self):
        root_obj = root()
        parent = scp_with_object(root_obj, "Parent", empty_object("Parent"), with_geometry=False)
        mid = scp_with_object(root_obj, "Mid", empty_object("Mid", (1.0, 0.0, 0.0)), with_geometry=False)
        child = scp_with_object(root_obj, "Child", empty_object("Child", (2.0, 0.0, 0.0)), with_geometry=False)
        for item, parent_obj in ((mid, parent.transform_object_ref), (child, mid.transform_object_ref)):
            item.attach_child_anchor_mode, item.attach_parent_anchor_mode = "OBJECT_ORIGIN", "OBJECT_ORIGIN"
            set_parent_relation(item.transform_object_ref, item, parent_obj)
            capture_attachment_from_link(item, item.transform_object_ref, None, parent_obj, None)
        parent.transform_object_ref.location.x = 3.0
        _apply_parent(root_obj, parent)
        self.assertEqual((_round_xyz(mid.transform_object_ref), _round_xyz(child.transform_object_ref)), ((4.0, 0.0, 0.0), (5.0, 0.0, 0.0)))

    def test_failed_capture_rolls_back_parent_link(self):
        root_obj = root()
        parent = scp_with_object(root_obj, "Parent", empty_object("Parent"), with_geometry=False)
        child = scp_with_object(root_obj, "Child", empty_object("Child"), with_geometry=False)
        child.attach_parent_anchor_mode = "SURFACE_NEAREST"
        result = execute_reparent_scp(DummyOperator(), bpy.context, child.id, parent.id)
        self.assertEqual((result, child.parent_id), ({"CANCELLED"}, ""))

    def test_blocked_recapture_skips_parent_apply_set(self):
        root_obj = root()
        parent = scp_with_object(root_obj, "Parent", empty_object("Parent"), with_geometry=False)
        child = scp_with_object(root_obj, "Child", empty_object("Child"), with_geometry=False)
        child.attach_child_anchor_mode, child.attach_parent_anchor_mode = "OBJECT_ORIGIN", "OBJECT_ORIGIN"
        set_parent_relation(child.transform_object_ref, child, parent.transform_object_ref)
        changed = capture_dirty_scp_attachments(root_obj, bpy.context.scene, {child.id}, source="depsgraph", recapture_ids={child.id}, apply_parent_ids={parent.id})
        self.assertEqual(changed, set())

    def test_attachment_property_update_recaptures_child_anchor(self):
        _root_obj, parent, child = _surface_setup()
        self.assertGreaterEqual(attach_child_anchor_index(child), 0)
        child.parent_id = parent.id
        child.attach_child_anchor_mode = "OBJECT_ORIGIN"
        self.assertEqual(attach_child_anchor_index(child), -1)
        self.assertEqual(tuple(round(v, 4) for v in attach_child_origin_local(child)), (0.0, 0.0, 0.0))

    def test_sync_runtime_payload_marks_recapture_and_apply_ids(self):
        payload = sync_runtime._payload({"S1"}, {"S1", "S2"})
        self.assertEqual((payload["scp_recapture_ids"], payload["scp_apply_target_ids"], payload["scp_apply_parent_ids"]), (["S1"], ["S1", "S2"], ["S1", "S2"]))

    def test_mirror_sync_creates_and_cleans_target_clone(self):
        root_obj = root()
        source = scp_with_object(root_obj, "Source", mesh_object("Source"))
        target = scp_with_object(root_obj, "Target", mesh_object("Target", (2.0, 0.0, 0.0)))
        target.parent_id, source.mirror_enabled, source.mirror_axis = source.id, True, "X"
        apply_scp_mirror_roles(root_obj)
        sync_mirrors(register_sync(), root_obj, bpy.context.scene, scp_prop_map(root_obj), {target.id})
        clone = find_flagged("af_scp_mirror", target.id, "af_source_scp_id")
        clone_name = clone.name
        self.assertEqual((clone is not None, round(clone.location.x, 4)), (True, -2.0))
        source.mirror_enabled = False
        apply_scp_mirror_roles(root_obj)
        sync_mirrors(register_sync(), root_obj, bpy.context.scene, scp_prop_map(root_obj), {target.id})
        self.assertIsNone(bpy.data.objects.get(clone_name))

    def test_mirror_sync_respects_axis_and_origin(self):
        root_obj = root()
        source = scp_with_object(root_obj, "Source", mesh_object("Source"))
        target = scp_with_object(root_obj, "Target", mesh_object("Target", (2.0, 2.0, 0.0)))
        target.parent_id, source.mirror_enabled = source.id, True
        source.mirror_axis, source.mirror_origin = "Y", (0.0, 1.0, 0.0)
        apply_scp_mirror_roles(root_obj)
        sync_mirrors(register_sync(), root_obj, bpy.context.scene, scp_prop_map(root_obj), {target.id})
        clone = find_flagged("af_scp_mirror", target.id, "af_source_scp_id")
        self.assertEqual(_round_xyz(clone), (2.0, 0.0, 0.0))

    def test_mirror_sync_scope_keeps_unrelated_clusters(self):
        root_obj = root()
        source_a = scp_with_object(root_obj, "SourceA", mesh_object("SourceA"))
        target_a = scp_with_object(root_obj, "TargetA", mesh_object("TargetA", (2.0, 0.0, 0.0)))
        source_b = scp_with_object(root_obj, "SourceB", mesh_object("SourceB"))
        target_b = scp_with_object(root_obj, "TargetB", mesh_object("TargetB", (0.0, 2.0, 0.0)))
        target_a.parent_id, source_a.mirror_enabled = source_a.id, True
        target_b.parent_id, source_b.mirror_enabled = source_b.id, True
        apply_scp_mirror_roles(root_obj)
        sync = register_sync()
        sync_mirrors(sync, root_obj, bpy.context.scene, scp_prop_map(root_obj))
        clone_a = find_flagged("af_scp_mirror", target_a.id, "af_source_scp_id")
        clone_b = find_flagged("af_scp_mirror", target_b.id, "af_source_scp_id")
        clone_a_name, clone_b_name = clone_a.name, clone_b.name
        source_a.mirror_enabled = False
        apply_scp_mirror_roles(root_obj)
        sync_mirrors(sync, root_obj, bpy.context.scene, scp_prop_map(root_obj), {target_a.id})
        self.assertIsNone(bpy.data.objects.get(clone_a_name))
        self.assertIsNotNone(bpy.data.objects.get(clone_b_name))

    def test_mirror_sync_detaches_sheared_child_helper(self):
        root_obj = root()
        source = scp_with_object(root_obj, "Source", empty_object("Source"), with_geometry=False)
        target = scp_with_object(root_obj, "Target", empty_object("Target"), with_geometry=False)
        upstream = empty_object("Upstream")
        helper = empty_object("Helper")
        target.parent_id, source.mirror_enabled, source.mirror_axis = source.id, True, "Y"
        self.assertTrue(add_bound_object_to_scp(root_obj, target, helper))
        sync_scp_roles(root_obj, target)
        upstream.rotation_euler = (-0.3, 0.2, -1.1)
        upstream.scale = (0.7, 1.3, 4.2)
        target.transform_object_ref.parent = upstream
        target.transform_object_ref.matrix_parent_inverse = upstream.matrix_world.inverted()
        target.transform_object_ref.rotation_euler = (-0.1654, -0.0014, -1.4889)
        target.transform_object_ref.scale = (0.4352, 0.4352, 4.1735)
        helper.location = (1.0339, -0.1605, -0.9385)
        bpy.context.view_layer.update()
        apply_scp_mirror_roles(root_obj)
        sync_mirrors(register_sync(), root_obj, bpy.context.scene, scp_prop_map(root_obj), {target.id})
        bound_id = find_bound_entry_by_object(target, helper).id
        clone = _find_mirror_bound(target.id, bound_id)
        self.assertIsNone(clone.parent)
        self.assertLess(_matrix_delta(mirror_matrix("Y") @ helper.matrix_world, clone.matrix_world), 1e-4)

    def test_mirror_sync_keeps_reflected_shape_for_rotated_scaled_root(self):
        root_obj = root()
        source = scp_with_object(root_obj, "Source", mesh_object("Source"))
        target = scp_with_object(root_obj, "Target", mesh_object("Target", (2.0, 0.0, 0.0)))
        obj = source.transform_object_ref
        obj.location, obj.rotation_euler = (1.7, 0.3, -0.4), (1.24, 0.7052, -2.1069)
        obj.scale, target.parent_id, source.mirror_enabled = (2.3918, 0.1016, 0.1504), source.id, True
        source.mirror_axis = "Y"
        apply_scp_mirror_roles(root_obj)
        sync_mirrors(register_sync(), root_obj, bpy.context.scene, scp_prop_map(root_obj), {target.id})
        clone = find_flagged("af_scp_mirror", target.id, "af_source_scp_id")
        expected = tuple(mirror_matrix("Y") @ vert for vert in _world_verts(obj))
        self.assertLess(_max_delta(expected, _world_verts(clone)), 1e-4)

    def test_mirror_sync_clears_local_transform_drivers_on_hidden_clone(self):
        root_obj = root()
        source = scp_with_object(root_obj, "Source", empty_object("Source"), with_geometry=False)
        target = scp_with_object(root_obj, "Target", empty_object("Target"), with_geometry=False)
        helper = empty_object("Helper")
        target.parent_id, source.mirror_enabled, source.mirror_axis = source.id, True, "Y"
        self.assertTrue(add_bound_object_to_scp(root_obj, target, helper))
        sync_scp_roles(root_obj, target)
        target.transform_object_ref.location, target.transform_object_ref.rotation_euler, target.transform_object_ref.scale = (-1.288933, -2.127279, -7.179165), (0.0, 0.0, -1.625514), (0.553584, 0.735199, 0.553584)
        helper.location, helper.rotation_euler = (1.180263, 0.015051, 0.911106), (0.0, 0.827395, 0.0)
        self.assertTrue(create_local_transform_props(helper)[0])
        apply_scp_mirror_roles(root_obj); sync_mirrors(register_sync(), root_obj, bpy.context.scene, scp_prop_map(root_obj), {target.id})
        bound_id = find_bound_entry_by_object(target, helper).id; clone = _find_mirror_bound(target.id, bound_id)
        self.assertEqual(len(tuple(getattr(getattr(clone, "animation_data", None), "drivers", ()) or ())), 0)
        self.assertLess(_matrix_delta(mirror_matrix("Y") @ helper.matrix_world, clone.matrix_world), 1e-4)

    def test_mirror_sync_remaps_shared_external_hook_targets(self):
        root_obj = root()
        sternum = scp_with_object(root_obj, "Sternum", empty_object("Sternum"), with_geometry=False)
        sternum.mirror_enabled = True
        hook = scp_with_object(root_obj, "Hook", empty_object("Hook"), with_geometry=False)
        hook.parent_id = sternum.id
        clavicle_a = _hooked_curve_scp(root_obj, "ClavicleA", sternum.id, hook.transform_object_ref)
        clavicle_b = _hooked_curve_scp(root_obj, "ClavicleB", sternum.id, hook.transform_object_ref)
        apply_scp_mirror_roles(root_obj)
        sync_mirrors(register_sync(), root_obj, bpy.context.scene, scp_prop_map(root_obj))
        hook_clone = find_flagged("af_scp_mirror", hook.id, "af_source_scp_id")
        clone_a = find_flagged("af_scp_mirror", clavicle_a.id, "af_source_scp_id")
        clone_b = find_flagged("af_scp_mirror", clavicle_b.id, "af_source_scp_id")
        refs = tuple(obj.modifiers["Hook"].object for obj in (clone_a, clone_b))
        self.assertEqual((hook_clone is not None, refs), (True, (hook_clone, hook_clone)))
