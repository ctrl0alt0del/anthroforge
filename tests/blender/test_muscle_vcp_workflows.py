from pathlib import Path
import sys
from unittest.mock import patch

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy
from mathutils import Vector

from _helpers import BlenderTestCase, capture_mesh_attachment, empty_object, find_flagged, mesh_object, root, scp_with_object, select_only
from core.id_utils import next_prefixed_id
from core.scp_runtime.lookup import set_parent_relation
from core.vcp.muscle_surface import prepare_surface_rows
from core.vcp.runtime_state import muscle_inflation_ctrl_world
from core.visualization.muscle_sync import apply_muscle_control_update, register_muscle_sync
from core.visualization import fiber_sync_helpers, muscle_sync_helpers, muscle_sync_runtime
from core.visualization.muscle_sync_helpers import find_muscle_proxy, mark_inflation_ctrl
from core.visualization.vcp_mirror_runtime import sync_vcp_mirrors


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


def _new_muscle(root_obj, fiber_ids, mode="CTRL_POINT"):
    muscle = root_obj.af_vcp_system.muscles.add()
    muscle.id = next_prefixed_id(root_obj.af_vcp_system.muscles, "MUSCLE")
    muscle.name = muscle.id
    muscle.inflation_mode = mode
    for fiber_id in fiber_ids:
        muscle.fiber_refs.add().fiber_id = fiber_id
        _fiber_by_id(root_obj, fiber_id).muscle_id = muscle.id
    root_obj.af_vcp_system.active_vcp_type, root_obj.af_vcp_system.active_vcp_id = "MUSCLE", muscle.id
    return muscle


def _fiber_by_id(root_obj, fiber_id):
    return next(item for item in root_obj.af_vcp_system.fibers if item.id == fiber_id)


def _surface_obj(root_obj, muscle, surface_type):
    vis = register_muscle_sync()._get_vis_collection(bpy.context.scene)
    return find_muscle_proxy(vis, root_obj.name, muscle.id, surface_type)


def _vertex_delta(base_obj, infl_obj, index):
    return (infl_obj.data.vertices[index].co - base_obj.data.vertices[index].co).length


def _center_delta(root_obj, muscle, amount):
    muscle.inflation_max_value = amount
    register_muscle_sync().sync_root_to_scene(root=root_obj, scene=bpy.context.scene)
    base = _surface_obj(root_obj, muscle, "BASE")
    infl = _surface_obj(root_obj, muscle, "INFL")
    n = int(root_obj.af_vcp_system.fibers[0].node_count)
    rows = len(base.data.vertices) // n
    return _vertex_delta(base, infl, (rows // 2) * n + (n // 2))


def _distributed_deltas(root_obj, muscle):
    base = _surface_obj(root_obj, muscle, "BASE")
    infl = _surface_obj(root_obj, muscle, "INFL")
    n = int(root_obj.af_vcp_system.fibers[0].node_count)
    rows = len(base.data.vertices) // n
    mid_row, mid_col = rows // 2, n // 2
    return (
        _vertex_delta(base, infl, mid_row * n + mid_col),
        _vertex_delta(base, infl, mid_row * n),
        _vertex_delta(base, infl, mid_row * n + (n - 1)),
        _vertex_delta(base, infl, mid_col),
    )


def _near_end_delta(root_obj, muscle, taper_band):
    muscle.inflation_length_taper_band = taper_band
    register_muscle_sync().sync_root_to_scene(root=root_obj, scene=bpy.context.scene)
    base = _surface_obj(root_obj, muscle, "BASE")
    infl = _surface_obj(root_obj, muscle, "INFL")
    n = int(root_obj.af_vcp_system.fibers[0].node_count)
    rows = len(base.data.vertices) // n
    return _vertex_delta(base, infl, (rows // 2) * n + 1)


def _three_fiber_setup():
    root_obj = root()
    for name, loc in (("O1", (0.0, 0.0, 0.0)), ("I1", (2.0, 0.0, 0.0)), ("O2", (0.0, 1.0, 0.0)), ("I2", (2.0, 1.0, 0.0)), ("O3", (0.0, 2.0, 0.0)), ("I3", (2.0, 2.0, 0.0))):
        scp_with_object(root_obj, name, mesh_object(name, loc))
    scps = root_obj.af_scp_system.scps
    _add_fiber(scps[0], scps[1]), _add_fiber(scps[2], scps[3]), _add_fiber(scps[4], scps[5])
    return root_obj, [find_flagged("af_fiber_proxy", item.id, "af_fiber_id") for item in root_obj.af_vcp_system.fibers]


def _mirrored_side_muscle_setup():
    root_obj = root()
    source = scp_with_object(root_obj, "MirrorSrc", empty_object("MirrorSrc"), with_geometry=False)
    source.mirror_enabled = True
    o1 = scp_with_object(root_obj, "O1", mesh_object("O1", (1.0, 0.0, 0.0)))
    i1 = scp_with_object(root_obj, "I1", mesh_object("I1", (3.0, 0.0, 0.0)))
    o2 = scp_with_object(root_obj, "O2", mesh_object("O2", (1.0, 1.0, 0.0)))
    i2 = scp_with_object(root_obj, "I2", mesh_object("I2", (3.0, 1.0, 0.0)))
    for scp in (o1, i1, o2, i2):
        set_parent_relation(scp.transform_object_ref, scp, source.transform_object_ref)
    _add_fiber(o1, i1), _add_fiber(o2, i2)
    return root_obj, find_flagged("af_fiber_proxy", root_obj.af_vcp_system.fibers[0].id, "af_fiber_id"), find_flagged("af_fiber_proxy", root_obj.af_vcp_system.fibers[1].id, "af_fiber_id")


def _restored_ctrl_state(root_obj, muscle):
    sync = register_muscle_sync()
    original = tuple(round(v, 4) for v in muscle_inflation_ctrl_world(muscle))
    muscle.inflation_mode = "DISTRIBUTED"
    sync.sync_root_to_scene(root=root_obj, scene=bpy.context.scene)
    root_obj.af_vcp_system.active_vcp_type, root_obj.af_vcp_system.active_vcp_id = "MUSCLE", muscle.id
    muscle.inflation_mode = "CTRL_POINT"
    sync.sync_root_to_scene(root=root_obj, scene=bpy.context.scene)
    ctrl = find_flagged("af_muscle_inflation_ctrl", muscle.id, "af_muscle_id")
    return ctrl, tuple(round(v, 4) for v in muscle_inflation_ctrl_world(muscle)), original


def _loop_mesh_object(name, location=(0.0, 0.0, 0.0)):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    return obj


def _circle_points(count, radius=1.0, z=0.0):
    import math

    return [Vector((radius * math.cos(i * 6.28318530718 / count), radius * math.sin(i * 6.28318530718 / count), z)) for i in range(count)]


def _avg_row_distance(a, b):
    return sum((a[i] - b[i]).length for i in range(min(len(a), len(b)))) / float(min(len(a), len(b)))


def _edit_select(obj, *indices):
    import bmesh

    select_only(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    for vert in bm.verts:
        vert.select_set(False)
    bm.select_history.clear()
    for index in indices:
        vert = bm.verts[int(index)]
        vert.select_set(True)
        bm.select_history.add(vert)
    bmesh.update_edit_mesh(obj.data)


def _two_loop_setup():
    root_obj = root()
    for name, loc in (("LoopA", (0.0, 0.0, 0.0)), ("LoopB", (0.0, 0.0, 0.8))):
        loop = scp_with_object(root_obj, name, _loop_mesh_object(name, loc))
        _edit_select(loop.geometry_object_ref, 0, 1, 2, 3)
        bpy.ops.af.create_loop_fiber_from_selected_vertices()
    return root_obj, root_obj.af_vcp_system.fibers[0], root_obj.af_vcp_system.fibers[1]


class MuscleVcpWorkflowTests(BlenderTestCase):
    def test_muscle_proxy_object_color_matches_material(self):
        root_obj, first, second = _muscle_setup()
        select_only(first)
        second.select_set(True)
        bpy.ops.af.add_muscle_vcp()
        register_muscle_sync().sync_root_to_scene(root=root_obj, scene=bpy.context.scene)
        muscle = root_obj.af_vcp_system.muscles[0]
        base = _surface_obj(root_obj, muscle, "BASE")
        want = tuple(round(float(v), 4) for v in base.data.materials[0].diffuse_color)
        self.assertEqual(tuple(round(float(v), 4) for v in base.color), want)

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

    def test_muscle_rows_use_cached_fiber_points(self):
        root_obj, first, second = _muscle_setup()
        fibers = tuple(root_obj.af_vcp_system.fibers)
        for fiber, proxy in zip(fibers, (first, second)):
            rows = muscle_sync_runtime.json.loads(proxy["af_fiber_points_world"])
            fiber_sync_helpers.update_curve_points(proxy, [Vector(row) for row in rows], fiber.thickness)
        with patch.object(muscle_sync_runtime.json, "loads") as loads:
            rows = muscle_sync_runtime.collect_fiber_points(root_obj, bpy.context.scene, fibers)
        self.assertEqual((loads.call_count, len(rows)), (0, 2))

    def test_update_mesh_skips_rebuild_for_same_topology(self):
        obj = mesh_object("PerfMesh")
        verts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        faces = [(0, 1, 2)]
        muscle_sync_helpers.update_mesh(obj, verts, faces)
        changed = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        with patch.object(muscle_sync_helpers, "_rebuild_mesh") as rebuild:
            muscle_sync_helpers.update_mesh(obj, changed, faces)
        self.assertEqual((rebuild.call_count, round(obj.data.vertices[1].co.x, 4)), (0, 2.0))

    def test_closed_loop_rows_are_rephased_before_muscle_surface(self):
        outer = _circle_points(32, 1.0, 0.0)
        inner = list(reversed(_circle_points(32, 0.8, 0.1)[9:] + _circle_points(32, 0.8, 0.1)[:9]))
        rows = prepare_surface_rows([outer, inner], target_n=32, densify_v=False, closed_u=True)
        self.assertGreater(_avg_row_distance(outer, inner), 1.0)
        self.assertLess(_avg_row_distance(rows[0], rows[1]), 0.25)

    def test_closed_loop_muscle_gets_minimum_inner_rows(self):
        outer = _circle_points(32, 1.0, 0.0)
        inner = _circle_points(32, 0.95, 0.03)
        rows = prepare_surface_rows([outer, inner], target_n=32, densify_v=True, closed_u=True)
        self.assertGreaterEqual(len(rows), 5)

    def test_add_muscle_from_single_mirrored_fiber_expands_across_plane(self):
        root_obj, first, _second = _mirrored_side_muscle_setup()
        select_only(first)
        self.assertEqual(bpy.ops.af.add_muscle_vcp(), {"FINISHED"})
        muscle = root_obj.af_vcp_system.muscles[0]
        register_muscle_sync().sync_root_to_scene(root=root_obj, scene=bpy.context.scene)
        base = _surface_obj(root_obj, muscle, "BASE")
        xs = [(base.matrix_world @ vert.co).x for vert in base.data.vertices]
        sync_vcp_mirrors(root=root_obj, scene=bpy.context.scene, target_muscle_ids={muscle.id})
        mirror = next((obj for obj in bpy.context.scene.objects if obj.get("af_muscle_mirror_proxy") and obj.get("af_source_muscle_id") == muscle.id), None)
        self.assertEqual([ref.fiber_id for ref in muscle.fiber_refs], [root_obj.af_vcp_system.fibers[0].id])
        self.assertTrue(muscle.use_mirrored_rows)
        self.assertGreater(len(base.data.vertices), 0)
        self.assertLess(min(xs), -1.0e-6)
        self.assertGreater(max(xs), 1.0e-6)
        self.assertIsNone(mirror)

    def test_incompatible_fibers_are_rejected(self):
        root_obj, first, second = _muscle_setup()
        root_obj.af_vcp_system.fibers[1].node_count += 1
        select_only(first)
        second.select_set(True)
        with self.assertRaises(RuntimeError):
            bpy.ops.af.add_muscle_vcp()
        self.assertEqual(len(root_obj.af_vcp_system.muscles), 0)

    def test_fibers_with_different_mid_touch_counts_still_build_muscle(self):
        root_obj, first, second = _muscle_setup()
        touch = root_obj.af_vcp_system.fibers[1].mid_touches.add()
        touch.parent_id = root_obj.af_scp_system.scps[2].id
        touch.attach_param = capture_mesh_attachment(root_obj, root_obj.af_scp_system.scps[2], 0)
        select_only(first); second.select_set(True); bpy.ops.af.add_muscle_vcp()
        register_muscle_sync().sync_root_to_scene(root=root_obj, scene=bpy.context.scene)
        muscle = root_obj.af_vcp_system.muscles[0]
        base = find_flagged("af_muscle_proxy", muscle.id, "af_muscle_id")
        self.assertGreater(len(base.data.vertices), 0)

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
        root_obj, proxies = _three_fiber_setup()
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

    def test_add_muscle_uses_tracked_selection_order(self):
        root_obj, proxies = _three_fiber_setup()
        bpy.context.scene.af_selection_order_json = f'["{proxies[0].name}","{proxies[1].name}","{proxies[2].name}"]'
        select_only(proxies[2])
        proxies[0].select_set(True)
        proxies[1].select_set(True)
        bpy.ops.af.add_muscle_vcp()
        refs = [ref.fiber_id for ref in root_obj.af_vcp_system.muscles[0].fiber_refs]
        want = [fiber.id for fiber in root_obj.af_vcp_system.fibers[:3]]
        self.assertEqual(refs, want)

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

    def test_muscle_can_expand_rows_across_mirror_plane(self):
        root_obj, first, second = _mirrored_side_muscle_setup()
        select_only(first); second.select_set(True); bpy.ops.af.add_muscle_vcp()
        muscle = root_obj.af_vcp_system.muscles[0]
        sync = register_muscle_sync()
        sync.sync_root_to_scene(root=root_obj, scene=bpy.context.scene)
        before = len(_surface_obj(root_obj, muscle, "BASE").data.vertices)
        muscle.use_mirrored_rows = True
        sync.sync_root_to_scene(root=root_obj, scene=bpy.context.scene)
        base = _surface_obj(root_obj, muscle, "BASE")
        xs = [(base.matrix_world @ vert.co).x for vert in base.data.vertices]
        sync_vcp_mirrors(root=root_obj, scene=bpy.context.scene, target_muscle_ids={muscle.id})
        mirror = next((obj for obj in bpy.context.scene.objects if obj.get("af_muscle_mirror_proxy") and obj.get("af_source_muscle_id") == muscle.id), None)
        self.assertGreater(len(base.data.vertices), before)
        self.assertLess(min(xs), -1.0e-6)
        self.assertGreater(max(xs), 1.0e-6)
        self.assertIsNone(mirror)

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

    def test_distributed_mode_builds_surfaces_without_control(self):
        root_obj, _first, _second = _muscle_setup()
        fibers = [item.id for item in root_obj.af_vcp_system.fibers[:2]]
        muscle = _new_muscle(root_obj, fibers, mode="DISTRIBUTED")
        register_muscle_sync().sync_root_to_scene(root=root_obj, scene=bpy.context.scene)
        base = _surface_obj(root_obj, muscle, "BASE")
        infl = _surface_obj(root_obj, muscle, "INFL")
        ctrl = find_flagged("af_muscle_inflation_ctrl", muscle.id, "af_muscle_id")
        self.assertEqual((base is not None, infl is not None, ctrl), (True, True, None))

    def test_switching_modes_removes_and_restores_inflation_control(self):
        root_obj, first, second = _muscle_setup()
        select_only(first)
        second.select_set(True)
        bpy.ops.af.add_muscle_vcp()
        sync = register_muscle_sync()
        sync.sync_root_to_scene(root=root_obj, scene=bpy.context.scene)
        muscle = root_obj.af_vcp_system.muscles[0]
        ctrl, current, original = _restored_ctrl_state(root_obj, muscle)
        self.assertEqual((ctrl is not None, current), (True, original))
        self.assertEqual(tuple(round(v, 4) for v in ctrl.location), original)

    def test_distributed_mode_tapers_longitudinally_and_respects_side_boundaries(self):
        root_obj, _first, _second = _muscle_setup()
        fibers = [item.id for item in root_obj.af_vcp_system.fibers[:2]]
        muscle = _new_muscle(root_obj, fibers, mode="DISTRIBUTED")
        register_muscle_sync().sync_root_to_scene(root=root_obj, scene=bpy.context.scene)
        center, start, end, side = _distributed_deltas(root_obj, muscle)
        self.assertGreater(center, 1e-4)
        self.assertLess(start, 1e-6)
        self.assertLess(end, 1e-6)
        self.assertLess(side, 1e-6)

    def test_distributed_mode_inflation_amount_scales_beyond_small_values(self):
        root_obj, _first, _second = _muscle_setup()
        fibers = [item.id for item in root_obj.af_vcp_system.fibers[:2]]
        muscle = _new_muscle(root_obj, fibers, mode="DISTRIBUTED")
        low = _center_delta(root_obj, muscle, 0.01)
        high = _center_delta(root_obj, muscle, 0.08)
        self.assertGreater(high, low * 2.0)

    def test_distributed_mode_smaller_taper_band_flattens_later(self):
        root_obj, _first, _second = _muscle_setup()
        fibers = [item.id for item in root_obj.af_vcp_system.fibers[:2]]
        muscle = _new_muscle(root_obj, fibers, mode="DISTRIBUTED")
        early = _near_end_delta(root_obj, muscle, 0.35)
        late = _near_end_delta(root_obj, muscle, 0.08)
        self.assertGreater(late, early * 1.5)

    def test_delete_muscle_in_tree_removes_surfaces_and_control(self):
        root_obj, first, second = _muscle_setup()
        select_only(first); second.select_set(True); bpy.ops.af.add_muscle_vcp()
        register_muscle_sync().sync_root_to_scene(root=root_obj, scene=bpy.context.scene)
        muscle = root_obj.af_vcp_system.muscles[0]
        self.assertEqual(bpy.ops.af.delete_vcp_in_tree(node_id=muscle.id, node_type="MUSCLE"), {"FINISHED"})
        self.assertEqual((len(root_obj.af_vcp_system.muscles), root_obj.af_vcp_system.active_vcp_type), (0, "NONE"))
        self.assertEqual((_surface_obj(root_obj, muscle, "BASE"), _surface_obj(root_obj, muscle, "INFL")), (None, None))
        self.assertEqual((find_flagged("af_muscle_inflation_ctrl", muscle.id, "af_muscle_id"), [f.muscle_id for f in root_obj.af_vcp_system.fibers]), (None, ["", ""]))

    def test_loop_muscle_rejects_mixed_open_and_loop_fibers(self):
        root_obj, first, _second = _muscle_setup()
        loop = scp_with_object(root_obj, "Loop", _loop_mesh_object("Loop", (4.0, 0.0, 0.0)))
        _edit_select(loop.geometry_object_ref, 0, 1, 2, 3)
        bpy.ops.af.create_loop_fiber_from_selected_vertices()
        loop_proxy = find_flagged("af_fiber_proxy", root_obj.af_vcp_system.fibers[-1].id, "af_fiber_id")
        select_only(first)
        loop_proxy.select_set(True)
        with self.assertRaises(RuntimeError):
            bpy.ops.af.add_muscle_vcp()

    def test_two_solved_loops_create_valid_surface(self):
        root_obj, first, second = _two_loop_setup()
        select_only(find_flagged("af_fiber_proxy", first.id, "af_fiber_id"))
        find_flagged("af_fiber_proxy", second.id, "af_fiber_id").select_set(True)
        bpy.ops.af.add_muscle_vcp()
        register_muscle_sync().sync_root_to_scene(root=root_obj, scene=bpy.context.scene)
        muscle = root_obj.af_vcp_system.muscles[0]
        base = _surface_obj(root_obj, muscle, "BASE")
        self.assertGreater(len(base.data.vertices), 0)
        self.assertGreater(len(base.data.polygons), 0)
