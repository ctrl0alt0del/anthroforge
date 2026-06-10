from pathlib import Path
import sys
from unittest.mock import patch

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy

from _helpers import BlenderTestCase, find_flagged, mesh_object, root, scp_with_object, select_only
from anthroforge.core.visualization.blob_sync_helpers import target_object_for_blob
from anthroforge.core.visualization.blob_sync import register_blob_sync
from anthroforge.core.visualization.blob_sync_runtime import apply_blob_control_update


def _add_fiber(origin, insert):
    bpy.context.scene.af_new_fiber_origin_obj = origin.geometry_object_ref
    bpy.context.scene.af_new_fiber_insertion_obj = insert.geometry_object_ref
    bpy.ops.af.add_fiber_vcp()


def _muscle_proxy(root_obj):
    o1 = scp_with_object(root_obj, "O1", mesh_object("O1"))
    i1 = scp_with_object(root_obj, "I1", mesh_object("I1", (2.0, 0.0, 0.0)))
    o2 = scp_with_object(root_obj, "O2", mesh_object("O2", (0.0, 1.0, 0.0)))
    i2 = scp_with_object(root_obj, "I2", mesh_object("I2", (2.0, 1.0, 0.0)))
    _add_fiber(o1, i1), _add_fiber(o2, i2)
    select_only(find_flagged("af_fiber_proxy", root_obj.af_vcp_system.fibers[0].id, "af_fiber_id"))
    find_flagged("af_fiber_proxy", root_obj.af_vcp_system.fibers[1].id, "af_fiber_id").select_set(True)
    bpy.ops.af.add_muscle_vcp()
    return find_flagged("af_muscle_proxy", root_obj.af_vcp_system.muscles[0].id, "af_muscle_id")


def _add_blob(target):
    bpy.context.scene.af_new_blob_target_obj = target
    bpy.ops.af.add_blob_vcp()


def _clear_selection():
    for obj in tuple(bpy.context.selected_objects):
        obj.select_set(False)
    bpy.context.view_layer.objects.active = None


class BlobVcpWorkflowTests(BlenderTestCase):
    def test_proxy_selection_keeps_blob_control_visible(self):
        root_obj = root()
        scp = scp_with_object(root_obj, "Bone", mesh_object("Bone"))
        _add_blob(scp.geometry_object_ref)
        blob = root_obj.af_vcp_system.blobs[0]
        proxy = find_flagged("af_blob_proxy", blob.id, "af_blob_id")
        root_obj.af_vcp_system.active_vcp_type, root_obj.af_vcp_system.active_vcp_id = "NONE", ""
        _clear_selection()
        select_only(proxy)
        register_blob_sync().sync_root_to_scene(root=root_obj, scene=bpy.context.scene)
        self.assertIsNotNone(find_flagged("af_blob_control_gizmo", blob.id, "af_blob_id"))

    def test_blob_target_inference_handles_muscle_scp_and_object_targets(self):
        root_obj = root()
        scp = scp_with_object(root_obj, "Bone", mesh_object("Bone"))
        loose = mesh_object("Loose", (4.0, 0.0, 0.0))
        muscle_proxy = _muscle_proxy(root_obj)
        for target in (muscle_proxy, scp.geometry_object_ref, loose):
            _add_blob(target)
        items = [(b.attach_target_type, b.attach_target_id, b.attach_target_object_name) for b in root_obj.af_vcp_system.blobs]
        self.assertEqual(items[0][0], "MUSCLE")
        self.assertEqual(items[1][:2], ("SCP", scp.id))
        self.assertEqual(items[2], ("OBJECT", "", loose.name))

    def test_blob_target_resolution_falls_back_from_infl_to_base(self):
        root_obj = root()
        muscle_proxy = _muscle_proxy(root_obj)
        _add_blob(muscle_proxy)
        blob = root_obj.af_vcp_system.blobs[0]
        infl = next(obj for obj in bpy.context.scene.objects if obj.get("af_muscle_proxy") and obj.get("af_muscle_id") == blob.attach_target_id and obj.get("af_muscle_surface") == "INFL")
        base = next(obj for obj in bpy.context.scene.objects if obj.get("af_muscle_proxy") and obj.get("af_muscle_id") == blob.attach_target_id and obj.get("af_muscle_surface") == "BASE")
        self.assertIs(target_object_for_blob(bpy.context.scene, root_obj, blob), infl)
        bpy.data.objects.remove(infl, do_unlink=True)
        self.assertIs(target_object_for_blob(bpy.context.scene, root_obj, blob), base)

    def test_blob_control_update_and_cleanup_remove_stale_objects(self):
        root_obj = root()
        scp = scp_with_object(root_obj, "Bone", mesh_object("Bone"))
        _add_blob(scp.geometry_object_ref)
        blob = root_obj.af_vcp_system.blobs[0]
        _clear_selection()
        sync = register_blob_sync()
        sync.sync_root_to_scene(root=root_obj, scene=bpy.context.scene)
        proxy = find_flagged("af_blob_proxy", blob.id, "af_blob_id")
        ctrl = find_flagged("af_blob_control_gizmo", blob.id, "af_blob_id")
        ctrl = ctrl or sync._create_blob_control(sync._get_vis_collection(bpy.context.scene), root_obj, blob.id)
        proxy_name, ctrl_name = proxy.name, ctrl.name
        ctrl.location.x = 3.0
        self.assertEqual(apply_blob_control_update(sync, root_obj, bpy.context.scene, ctrl), blob.id)
        self.assertEqual(round(root_obj.af_vcp_system.blobs[0].control_point_world[0], 4), 3.0)
        root_obj.af_vcp_system.blobs.remove(0)
        sync.sync_root_to_scene(root=root_obj, scene=bpy.context.scene)
        self.assertEqual((bpy.data.objects.get(proxy_name), bpy.data.objects.get(ctrl_name)), (None, None))

    def test_blob_control_update_respects_conflict_resolution(self):
        root_obj = root()
        scp = scp_with_object(root_obj, "Bone", mesh_object("Bone"))
        _add_blob(scp.geometry_object_ref)
        blob = root_obj.af_vcp_system.blobs[0]
        sync = register_blob_sync()
        sync.sync_root_to_scene(root=root_obj, scene=bpy.context.scene)
        ctrl = find_flagged("af_blob_control_gizmo", blob.id, "af_blob_id")
        ctrl = ctrl or sync._create_blob_control(sync._get_vis_collection(bpy.context.scene), root_obj, blob.id)
        with patch("anthroforge.core.visualization.blob_sync_runtime.resolve_conflict", return_value=(4.0, 5.0, 6.0)):
            self.assertEqual(apply_blob_control_update(sync, root_obj, bpy.context.scene, ctrl), blob.id)
        self.assertEqual(tuple(round(v, 4) for v in root_obj.af_vcp_system.blobs[0].control_point_world), (4.0, 5.0, 6.0))

    def test_blob_object_target_invalidation_returns_none(self):
        root_obj = root()
        loose = mesh_object("Loose", (4.0, 0.0, 0.0))
        _add_blob(loose)
        blob = root_obj.af_vcp_system.blobs[0]
        sync = register_blob_sync()
        sync.sync_root_to_scene(root=root_obj, scene=bpy.context.scene)
        proxy_name = find_flagged("af_blob_proxy", blob.id, "af_blob_id").name
        bpy.data.objects.remove(loose, do_unlink=True)
        self.assertIsNone(target_object_for_blob(bpy.context.scene, root_obj, blob))
        sync.sync_root_to_scene(root=root_obj, scene=bpy.context.scene)
        self.assertIsNotNone(bpy.data.objects.get(proxy_name))
