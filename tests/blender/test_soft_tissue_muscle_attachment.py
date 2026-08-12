from pathlib import Path
import sys

import bpy
from mathutils import Vector

TEST_DIR = Path(__file__).resolve().parent
if str(TEST_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_DIR))

from _helpers import BlenderTestCase, find_flagged, reset_scene, root, select_only, temp_blend_path
from test_fiber_surface_workflows import _matching_four_scps
from test_muscle_vcp_workflows import _mirrored_side_muscle_setup, _muscle_setup, _surface_obj
from test_soft_tissue_workflows import _grid
from app.runtime_api import sync_scene
from app.use_cases.vcp_delete import delete_vcp_in_tree
from app.use_cases.soft_tissue_target import _change_target
from core.deps.dirty_hints import dirty_hints_for
from core.vcp.runtime_state import soft_tissue_status
from core.vcp.surface_target import target_ref
from core.visualization.muscle_sync import register_muscle_sync
from core.visualization.fiber_surface_sync import find_fiber_surface_proxy
from core.visualization.soft_tissue_sync import register_soft_tissue_sync
from core.visualization import sync_runner
from core.deps.mirror_roles import apply_scp_mirror_roles
from core.visualization.vcp_mirror_runtime import sync_vcp_mirrors


class SoftTissueMuscleAttachmentTests(BlenderTestCase):
    def test_infl_target_follows_muscle_without_recapture(self):
        root_obj, muscle, tissue, _base, _target = _muscle_tissue("INFL")
        proxy = _tissue_proxy(tissue.id)
        before = _world_points(proxy)
        payloads = _binding_payloads(tissue)
        muscle.inflation_mode, muscle.inflation_max_value = "DISTRIBUTED", 0.35
        sync_scene(root_obj, bpy.context.scene, dirty_hints_for("MUSCLE", {muscle.id}))
        after = _world_points(proxy)
        self.assertGreater(_maximum_delta(before, after), 1.0e-3)
        self.assertEqual((_binding_payloads(tissue), soft_tissue_status(tissue)), (payloads, "CLEAN"))

    def test_base_and_infl_roles_are_explicit(self):
        root_obj, muscle, first, _base, _target = _muscle_tissue("BASE")
        second = _add_tissue(root_obj, muscle, "INFL", "Infl Tissue")
        self.assertEqual(first.attachment_target_surface, "MUSCLE_BASE")
        self.assertEqual(second.attachment_target_surface, "MUSCLE_INFL")
        self.assertNotEqual(first.base_bindings_json, second.base_bindings_json)

    def test_topology_change_retains_output_and_requires_rebind(self):
        root_obj, muscle, tissue, _base, _target = _muscle_tissue("INFL")
        proxy, before = _tissue_proxy(tissue.id), _world_points(_tissue_proxy(tissue.id))
        for fiber in root_obj.af_vcp_system.fibers:
            fiber.node_count += 1
        sync_scene(root_obj, bpy.context.scene, dirty_hints_for("FIBER", {f.id for f in root_obj.af_vcp_system.fibers}))
        self.assertEqual((soft_tissue_status(tissue), _world_points(proxy)), ("ERROR", before))
        root_obj.af_vcp_system.active_vcp_type, root_obj.af_vcp_system.active_vcp_id = "SOFT_TISSUE", tissue.id
        self.assertEqual(bpy.ops.af.rebind_soft_tissue(), {"FINISHED"})
        self.assertEqual(soft_tissue_status(tissue), "CLEAN")

    def test_referenced_muscle_deletion_is_blocked(self):
        root_obj, muscle, tissue, _base, _target = _muscle_tissue("INFL")
        result = delete_vcp_in_tree(bpy.context, "MUSCLE", muscle.id)
        self.assertFalse(result.ok)
        self.assertIn(tissue.id, result.message)
        self.assertEqual(len(root_obj.af_vcp_system.muscles), 1)

    def test_deleted_muscle_proxy_is_recreated_without_deleting_entities(self):
        root_obj, muscle, tissue, _base, target = _muscle_tissue("INFL")
        bpy.data.objects.remove(target, do_unlink=True)
        register_muscle_sync().sync_root_to_scene(root_obj, bpy.context.scene, {muscle.id})
        sync_scene(root_obj, bpy.context.scene, dirty_hints_for("MUSCLE", {muscle.id}))
        recreated = _surface_obj(root_obj, muscle, "INFL")
        self.assertIsNotNone(recreated)
        self.assertEqual((len(root_obj.af_vcp_system.muscles), soft_tissue_status(tissue)), (1, "CLEAN"))

    def test_clear_target_preserves_rows_and_removes_bindings(self):
        root_obj, _muscle, tissue, _base, _target = _muscle_tissue("INFL")
        count = len(tissue.attachments)
        root_obj.af_vcp_system.active_vcp_type, root_obj.af_vcp_system.active_vcp_id = "SOFT_TISSUE", tissue.id
        self.assertEqual(bpy.ops.af.clear_soft_tissue_target(tissue_id=tissue.id), {"FINISHED"})
        self.assertEqual((tissue.attachment_target_type, len(tissue.attachments)), ("NONE", count))
        self.assertTrue(all(row.bindings_json == "[]" for row in tissue.attachments))
        self.assertEqual(soft_tissue_status(tissue), "CLEAN")

    def test_assign_and_select_target_operators_use_explicit_surface_role(self):
        root_obj, muscle, tissue, _base, target = _muscle_tissue("BASE")
        root_obj.af_vcp_system.active_vcp_type, root_obj.af_vcp_system.active_vcp_id = "SOFT_TISSUE", tissue.id
        self.assertEqual(bpy.ops.af.clear_soft_tissue_target(tissue_id=tissue.id), {"FINISHED"})
        bpy.context.scene.af_new_soft_tissue_target_obj = target
        self.assertEqual(bpy.ops.af.assign_soft_tissue_target(tissue_id=tissue.id), {"FINISHED"})
        self.assertEqual((tissue.attachment_target_id, tissue.attachment_target_surface),
                         (muscle.id, "MUSCLE_BASE"))
        self.assertEqual(bpy.ops.af.select_soft_tissue_target(tissue_id=tissue.id), {"FINISHED"})
        self.assertEqual(bpy.context.active_object, target)

    def test_target_assignment_is_immediate_in_manual_mode(self):
        root_obj, muscle, tissue, _base, target = _muscle_tissue("INFL")
        root_obj.af_vcp_system.active_vcp_type, root_obj.af_vcp_system.active_vcp_id = "SOFT_TISSUE", tissue.id
        tissue.auto_recompute = False
        self.assertEqual(bpy.ops.af.clear_soft_tissue_target(tissue_id=tissue.id), {"FINISHED"})
        bpy.context.scene.af_new_soft_tissue_target_obj = target
        self.assertEqual(bpy.ops.af.assign_soft_tissue_target(tissue_id=tissue.id), {"FINISHED"})
        self.assertEqual((soft_tissue_status(tissue), tissue.attachment_target_id), ("CLEAN", muscle.id))
        before = _world_points(_tissue_proxy(tissue.id))
        muscle.inflation_mode, muscle.inflation_max_value = "DISTRIBUTED", 0.5
        sync_scene(root_obj, bpy.context.scene, dirty_hints_for("MUSCLE", {muscle.id}))
        self.assertEqual((soft_tissue_status(tissue), _world_points(_tissue_proxy(tissue.id))), ("DIRTY", before))

    def test_live_constraint_controls_do_not_recapture(self):
        _root_obj, _muscle, tissue, _base, _target = _muscle_tissue("INFL")
        row, before = tissue.attachments[0], _binding_payloads(tissue)
        row.mode, row.strength, row.normal_offset = "SOFT", 0.23, 0.04
        register_soft_tissue_sync().sync_root_to_scene(root(), bpy.context.scene, {tissue.id}, force=True)
        sync_runner.clear_pending_runtime()
        self.assertEqual(_binding_payloads(tissue), before)
        self.assertEqual(soft_tissue_status(tissue), "CLEAN")

    def test_feather_recaptures_regions_only(self):
        _root_obj, _muscle, tissue, _base, _target = _muscle_tissue("INFL")
        controls, base, regions = _binding_payloads(tissue)
        row = next(item for item in tissue.attachments if item.mask_attribute == "BOUNDARY")
        row.feather = 0.45
        scopes = {str(tissue.id): "REGIONS"}
        register_soft_tissue_sync().sync_root_to_scene(root(), bpy.context.scene, {tissue.id}, scopes, True)
        sync_runner.clear_pending_runtime()
        updated = _binding_payloads(tissue)
        self.assertEqual(updated[:2], (controls, base))
        self.assertNotEqual(updated[2], regions)

    def test_failed_assignment_rolls_back_identity_bindings_and_geometry(self):
        root_obj, _muscle, tissue, _base, _target = _muscle_tissue("INFL")
        identity = (tissue.attachment_target_type, tissue.attachment_target_id, tissue.attachment_target_surface)
        payloads, points = _binding_payloads(tissue), _world_points(_tissue_proxy(tissue.id))
        missing = target_ref("MUSCLE", "MISSING", "MUSCLE_INFL")
        result = _change_target(bpy.context, root_obj, tissue, missing, "unused")
        current = (tissue.attachment_target_type, tissue.attachment_target_id, tissue.attachment_target_surface)
        self.assertFalse(result.ok)
        self.assertEqual((current, _binding_payloads(tissue), _world_points(_tissue_proxy(tissue.id))),
                         (identity, payloads, points))

    def test_full_package_round_trip_remaps_muscle_target(self):
        _root_obj, _muscle, _tissue, _base, _target = _muscle_tissue("INFL")
        path = temp_blend_path()
        self.addCleanup(lambda: _remove_file(path))
        bpy.ops.wm.save_as_mainfile(filepath=path)
        reset_scene()
        result = _import_package()(path, bpy.context)
        vcp = root().af_vcp_system
        self.assertEqual((result.muscle_count, result.soft_tissue_count), (1, 1))
        self.assertEqual(vcp.soft_tissues[0].attachment_target_id, vcp.muscles[0].id)

    def test_vcp_round_trip_remaps_muscle_target(self):
        _root_obj, _muscle, _tissue, _base, _target = _muscle_tissue("BASE")
        path = temp_blend_path()
        self.addCleanup(lambda: _remove_file(path))
        bpy.ops.wm.save_as_mainfile(filepath=path)
        reset_scene()
        _matching_four_scps()
        result = _import_vcp()(path, bpy.context)
        vcp = root().af_vcp_system
        self.assertEqual((result.muscle_count, result.soft_tissue_count), (1, 1))
        self.assertEqual(vcp.soft_tissues[0].attachment_target_id, vcp.muscles[0].id)

    def test_fiber_surface_source_is_never_rewritten_by_muscle_target(self):
        root_obj, muscle, _first, _base, target = _muscle_tissue("INFL")
        surface = root_obj.af_vcp_system.fiber_surfaces[0]
        source = find_fiber_surface_proxy(bpy.context.scene, root_obj.name, surface.id)
        before = _world_points(source)
        select_only(source)
        bpy.context.scene.af_new_soft_tissue_preset = "CUSTOM"
        bpy.context.scene.af_new_soft_tissue_target_obj = target
        self.assertEqual(bpy.ops.af.add_soft_tissue_vcp(), {"FINISHED"})
        muscle.inflation_mode, muscle.inflation_max_value = "DISTRIBUTED", 0.4
        sync_scene(root_obj, bpy.context.scene, dirty_hints_for("MUSCLE", {muscle.id}))
        self.assertEqual(_world_points(source), before)

    def test_tissue_mirror_uses_muscle_target_rule(self):
        root_obj, first, second = _mirrored_side_muscle_setup()
        apply_scp_mirror_roles(root_obj)
        select_only(first)
        second.select_set(True)
        self.assertEqual(bpy.ops.af.add_muscle_vcp(), {"FINISHED"})
        muscle = root_obj.af_vcp_system.muscles[-1]
        register_muscle_sync().sync_root_to_scene(root_obj, bpy.context.scene)
        tissue = _add_tissue(root_obj, muscle, "INFL", "Mirror Tissue")
        sync_vcp_mirrors(root_obj, bpy.context.scene, target_soft_tissue_ids={tissue.id})
        mirrors = [obj for obj in bpy.context.scene.objects if obj.get("af_soft_tissue_mirror_proxy")]
        capture = _capture_skin()(root_obj, bpy.context.scene, bpy.context.evaluated_depsgraph_get())
        sources = [item for item in capture.sources if item.entity_type == "SOFT_TISSUE"]
        self.assertEqual((len(mirrors), len(sources)), (1, 2))

    def test_muscle_spanning_mirrored_rows_creates_no_second_tissue(self):
        root_obj, first, _second = _mirrored_side_muscle_setup()
        apply_scp_mirror_roles(root_obj)
        select_only(first)
        self.assertEqual(bpy.ops.af.add_muscle_vcp(), {"FINISHED"})
        muscle = root_obj.af_vcp_system.muscles[-1]
        register_muscle_sync().sync_root_to_scene(root_obj, bpy.context.scene)
        tissue = _add_tissue(root_obj, muscle, "INFL", "Spanning Tissue")
        sync_vcp_mirrors(root_obj, bpy.context.scene, target_soft_tissue_ids={tissue.id})
        mirrors = [obj for obj in bpy.context.scene.objects if obj.get("af_soft_tissue_mirror_proxy")]
        self.assertEqual((root_obj.af_vcp_system.fiber_surfaces[0].use_mirrored_rows, len(mirrors)), (True, 0))


def _muscle_tissue(role):
    root_obj, first, second = _muscle_setup()
    select_only(first)
    second.select_set(True)
    if bpy.ops.af.add_muscle_vcp() != {"FINISHED"}:
        raise AssertionError("Muscle creation failed")
    muscle = root_obj.af_vcp_system.muscles[-1]
    register_muscle_sync().sync_root_to_scene(root_obj, bpy.context.scene)
    tissue = _add_tissue(root_obj, muscle, role, f"{role} Tissue")
    target = _surface_obj(root_obj, muscle, role)
    return root_obj, muscle, tissue, tissue.base_object_ref, target


def _add_tissue(root_obj, muscle, role, name):
    target = _surface_obj(root_obj, muscle, role)
    base = _grid(name, 5)
    scene = bpy.context.scene
    scene.af_new_soft_tissue_preset = "LAYER"
    scene.af_new_soft_tissue_base_obj = base
    scene.af_new_soft_tissue_target_obj = target
    scene.af_new_soft_tissue_host_obj = None
    if bpy.ops.af.add_soft_tissue_vcp() != {"FINISHED"}:
        raise AssertionError("Soft Tissue creation failed")
    return root_obj.af_vcp_system.soft_tissues[-1]


def _tissue_proxy(tissue_id):
    return find_flagged("af_soft_tissue_proxy", tissue_id, "af_soft_tissue_id")


def _world_points(obj):
    return tuple(tuple(obj.matrix_world @ vertex.co) for vertex in obj.data.vertices)


def _maximum_delta(first, second):
    return max((Vector(a) - Vector(b)).length for a, b in zip(first, second))


def _binding_payloads(tissue):
    return tissue.control_bindings_json, tissue.base_bindings_json, tuple(row.bindings_json for row in tissue.attachments)


def _remove_file(path):
    import os
    if os.path.exists(path):
        os.remove(path)


def _import_package():
    from anthroforge.core.importing.service import import_package_from_blend
    return import_package_from_blend


def _import_vcp():
    from anthroforge.core.importing.service import import_vcp_from_blend
    return import_vcp_from_blend


def _capture_skin():
    from adapters.draft_skin.capture import capture_skin
    return capture_skin
