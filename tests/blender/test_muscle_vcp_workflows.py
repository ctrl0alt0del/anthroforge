from pathlib import Path
import sys

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy

from _helpers import BlenderTestCase, empty_object, find_flagged, mesh_object, root, scp_with_object, select_only
from core.vcp.runtime_state import muscle_inflation_ctrl_world
from core.visualization.muscle_sync import apply_muscle_control_update, register_muscle_sync
from core.visualization.muscle_sync_helpers import mark_inflation_ctrl


def _add_fiber(origin, insert):
    bpy.context.scene.af_new_fiber_origin_obj = origin.geometry_object_ref
    bpy.context.scene.af_new_fiber_insertion_obj = insert.geometry_object_ref
    bpy.ops.af.add_fiber_vcp()


def _muscle_setup():
    root_obj = root()
    o1 = scp_with_object(root_obj, "O1", mesh_object("O1"))
    i1 = scp_with_object(root_obj, "I1", mesh_object("I1", (2.0, 0.0, 0.0)))
    o2 = scp_with_object(root_obj, "O2", mesh_object("O2", (0.0, 1.0, 0.0)))
    i2 = scp_with_object(root_obj, "I2", mesh_object("I2", (2.0, 1.0, 0.0)))
    _add_fiber(o1, i1), _add_fiber(o2, i2)
    return root_obj, find_flagged("af_fiber_proxy", root_obj.af_vcp_system.fibers[0].id, "af_fiber_id"), find_flagged("af_fiber_proxy", root_obj.af_vcp_system.fibers[1].id, "af_fiber_id")


def _clear_selection():
    for obj in tuple(bpy.context.selected_objects):
        obj.select_set(False)
    bpy.context.view_layer.objects.active = None


class MuscleVcpWorkflowTests(BlenderTestCase):
    def test_add_muscle_operator_selects_inflation_control(self):
        root_obj, first, second = _muscle_setup()
        select_only(first)
        second.select_set(True)
        self.assertEqual(bpy.ops.af.add_muscle_vcp(), {"FINISHED"})
        muscle = root_obj.af_vcp_system.muscles[0]
        ctrl = find_flagged("af_muscle_inflation_ctrl", muscle.id, "af_muscle_id")
        self.assertEqual((ctrl is not None, bpy.context.active_object), (True, ctrl))

    def test_add_muscle_from_selected_fibers_creates_surfaces_and_control(self):
        root_obj, first, second = _muscle_setup()
        select_only(first)
        second.select_set(True)
        self.assertEqual(bpy.ops.af.add_muscle_vcp(), {"FINISHED"})
        _clear_selection()
        register_muscle_sync().sync_root_to_scene(root=root_obj, scene=bpy.context.scene)
        muscle = root_obj.af_vcp_system.muscles[0]
        base = find_flagged("af_muscle_proxy", muscle.id, "af_muscle_id")
        self.assertEqual((len(muscle.fiber_refs), base is not None), (2, True))

    def test_incompatible_fibers_are_rejected(self):
        root_obj, first, second = _muscle_setup()
        root_obj.af_vcp_system.fibers[1].node_count += 1
        select_only(first)
        second.select_set(True)
        with self.assertRaises(RuntimeError):
            bpy.ops.af.add_muscle_vcp()
        self.assertEqual(len(root_obj.af_vcp_system.muscles), 0)

    def test_flip_normals_and_inflation_control_selection_keep_muscle_active(self):
        root_obj, first, second = _muscle_setup()
        select_only(first)
        second.select_set(True)
        bpy.ops.af.add_muscle_vcp()
        _clear_selection()
        sync = register_muscle_sync()
        sync.sync_root_to_scene(root=root_obj, scene=bpy.context.scene)
        muscle = root_obj.af_vcp_system.muscles[0]
        bpy.ops.af.flip_muscle_normals()
        ctrl = find_flagged("af_muscle_inflation_ctrl", muscle.id, "af_muscle_id")
        ctrl = ctrl or sync._create_inflation_ctrl(sync._get_vis_collection(bpy.context.scene), root_obj, muscle.id)
        select_only(ctrl)
        self.assertTrue(muscle.flip_normals)
        self.assertEqual(bpy.context.active_object.get("af_muscle_id"), muscle.id)

    def test_reassigning_fiber_detaches_it_from_older_muscle(self):
        root_obj = root()
        for name, loc in (("O1", (0.0, 0.0, 0.0)), ("I1", (2.0, 0.0, 0.0)), ("O2", (0.0, 1.0, 0.0)), ("I2", (2.0, 1.0, 0.0)), ("O3", (0.0, 2.0, 0.0)), ("I3", (2.0, 2.0, 0.0))):
            scp_with_object(root_obj, name, mesh_object(name, loc))
        scps = root_obj.af_scp_system.scps
        _add_fiber(scps[0], scps[1]), _add_fiber(scps[2], scps[3]), _add_fiber(scps[4], scps[5])
        proxies = [find_flagged("af_fiber_proxy", item.id, "af_fiber_id") for item in root_obj.af_vcp_system.fibers]
        select_only(proxies[0])
        proxies[1].select_set(True)
        bpy.ops.af.add_muscle_vcp()
        first_muscle = root_obj.af_vcp_system.muscles[0]
        select_only(proxies[1])
        proxies[2].select_set(True)
        bpy.ops.af.add_muscle_vcp()
        second_muscle = root_obj.af_vcp_system.muscles[1]
        self.assertEqual([ref.fiber_id for ref in first_muscle.fiber_refs], [root_obj.af_vcp_system.fibers[0].id])
        self.assertEqual({ref.fiber_id for ref in second_muscle.fiber_refs}, {root_obj.af_vcp_system.fibers[1].id, root_obj.af_vcp_system.fibers[2].id})

    def test_missing_fiber_points_clear_muscle_surface(self):
        root_obj, first, second = _muscle_setup()
        select_only(first)
        second.select_set(True)
        bpy.ops.af.add_muscle_vcp()
        root_obj.af_vcp_system.muscles[0].fiber_refs[0].fiber_id = "MISSING"
        sync = register_muscle_sync()
        sync.sync_root_to_scene(root=root_obj, scene=bpy.context.scene)
        base = find_flagged("af_muscle_proxy", root_obj.af_vcp_system.muscles[0].id, "af_muscle_id")
        self.assertEqual(len(base.data.vertices), 0)

    def test_apply_muscle_control_update_snaps_ctrl_to_surface(self):
        root_obj, first, second = _muscle_setup()
        select_only(first)
        second.select_set(True)
        bpy.ops.af.add_muscle_vcp()
        sync = register_muscle_sync()
        sync.sync_root_to_scene(root=root_obj, scene=bpy.context.scene)
        muscle = root_obj.af_vcp_system.muscles[0]
        ctrl = mark_inflation_ctrl(empty_object("InflationCtrl"), root_obj, muscle.id)
        ctrl.location.z += 5.0
        self.assertEqual(apply_muscle_control_update(sync, root_obj, bpy.context.scene, ctrl), muscle.id)
        self.assertEqual(tuple(round(v, 4) for v in muscle_inflation_ctrl_world(muscle)), tuple(round(v, 4) for v in ctrl.location))

    def test_removed_inflation_control_is_ignored(self):
        root_obj, first, second = _muscle_setup()
        select_only(first)
        second.select_set(True)
        bpy.ops.af.add_muscle_vcp()
        sync = register_muscle_sync()
        sync.sync_root_to_scene(root=root_obj, scene=bpy.context.scene)
        muscle = root_obj.af_vcp_system.muscles[0]
        ctrl = find_flagged("af_muscle_inflation_ctrl", muscle.id, "af_muscle_id")
        ctrl = ctrl or sync._create_inflation_ctrl(sync._get_vis_collection(bpy.context.scene), root_obj, muscle.id)
        bpy.data.objects.remove(ctrl, do_unlink=True)
        self.assertIsNone(apply_muscle_control_update(sync, root_obj, bpy.context.scene, ctrl))

    def test_select_max_inflation_point_recreates_missing_control(self):
        root_obj, first, second = _muscle_setup()
        select_only(first)
        second.select_set(True)
        bpy.ops.af.add_muscle_vcp()
        muscle = root_obj.af_vcp_system.muscles[0]
        ctrl = find_flagged("af_muscle_inflation_ctrl", muscle.id, "af_muscle_id")
        if ctrl is not None:
            bpy.data.objects.remove(ctrl, do_unlink=True)
        _clear_selection()
        self.assertEqual(bpy.ops.af.select_muscle_inflation_ctrl(), {"FINISHED"})
        ctrl = find_flagged("af_muscle_inflation_ctrl", muscle.id, "af_muscle_id")
        self.assertEqual((ctrl is not None, bpy.context.active_object), (True, ctrl))
