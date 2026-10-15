from pathlib import Path
import sys
import tempfile
from unittest import mock

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy
import numpy as np

from _helpers import BlenderTestCase, mesh_object, root, scp_with_object
from adapters.draft_skin.capture import capture_skin
from adapters.draft_skin.painting import clear_map, fill_default, finish_paint, prepare_paint, set_brush_weight
from adapters.draft_skin import output as output_adapter
from adapters.draft_skin.output import replace_draft_skin
from adapters.draft_skin.vendor import ensure_worker_dependencies
from core.draft_skin.constants import PROTOCOL_VERSION, SOLVER_VERSION

ensure_worker_dependencies()

from core.draft_skin.mesh import orient_outward
from core.draft_skin.model import SkinCapture, SkinJobSpec, SkinResult, SkinSource
from core.draft_skin.protocol import capture_hash, read_job, read_result, read_status, write_job
from core.draft_skin.validation import validate_mesh
from workers import draft_skin_worker


def cube_arrays():
    vertices = np.asarray([
        (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
        (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1),
    ], dtype=np.float32)
    faces = np.asarray([
        (0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
        (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7),
    ], dtype=np.int32)
    return vertices, orient_outward(vertices, faces)


def tag(obj, root_obj, **values):
    obj["af_root_name"] = root_obj.name
    for name, value in values.items():
        obj[name] = value
    return obj


def mirror_scp(root_obj, scp, name="Ear Mirror"):
    obj = mesh_object(name)
    return tag(obj, root_obj, af_scp_geometry=True, af_scp_mirror=True, af_source_scp_id=scp.id)


def vcp_record(collection, entity_id, muscle_id=""):
    item = collection.add()
    item.id = entity_id
    if hasattr(item, "muscle_id"):
        item.muscle_id = muscle_id
    return item


def worker_spec(folder):
    root_path = Path(folder)
    value = lambda name: str(root_path / name)
    return SkinJobSpec(
        PROTOCOL_VERSION, SOLVER_VERSION, "ROOT", "", str(root_path), value("source.blend"),
        value("input.npz"), value("result.npz"), value("status.json"),
        value("job.log"), value("cancel.request"),
    )


class DraftSkinIntegrationTests(BlenderTestCase):
    def test_gap_override_survives_native_duplication(self):
        from core.scp_runtime.copy import copy_scp_subtree
        owner = root(); scp = scp_with_object(owner, "Bone", mesh_object("Bone"))
        scp.skin_gap_mode = "OVERRIDE"; scp.skin_gap_limit_percent = .25; scp.skin_gap_strength_percent = 50
        copied_id = copy_scp_subtree(owner, bpy.context.scene, scp.id)
        copied = next(item for item in owner.af_scp_system.scps if item.id == copied_id)
        self.assertEqual((copied.skin_gap_mode, copied.skin_gap_limit_percent, copied.skin_gap_strength_percent),
                         ("OVERRIDE", .25, 50))

    def test_gap_controls_undo_together_with_native_records(self):
        owner = root(); scp = scp_with_object(owner, "Bone", mesh_object("Bone")); identity = scp.id
        scp.skin_gap_mode = "OVERRIDE"; scp.skin_gap_limit_percent = .25
        owner.af_draft_skin_settings.gap_strength_percent = 25
        bpy.ops.ed.undo_push(message="Gap policy first")
        scp.skin_gap_limit_percent = 1; owner.af_draft_skin_settings.gap_strength_percent = 100
        bpy.ops.ed.undo_push(message="Gap policy second"); bpy.ops.ed.undo()
        owner = root(); restored = next(item for item in owner.af_scp_system.scps if item.id == identity)
        self.assertEqual((restored.skin_gap_limit_percent, owner.af_draft_skin_settings.gap_strength_percent), (.25, 25))

    def test_consumed_fiber_uses_final_muscle_gap_policy(self):
        owner = root(); scp_with_object(owner, "Bone", mesh_object("Bone"))
        muscle = vcp_record(owner.af_vcp_system.muscles, "M1")
        fiber = vcp_record(owner.af_vcp_system.fibers, "F1", "M1")
        muscle.skin_gap_mode = fiber.skin_gap_mode = "OVERRIDE"
        muscle.skin_gap_limit_percent = .25; fiber.skin_gap_limit_percent = 0
        tag(mesh_object("Infl"), owner, af_muscle_proxy=True, af_muscle_id="M1", af_muscle_surface="INFL")
        tag(mesh_object("Consumed"), owner, af_fiber_proxy=True, af_fiber_id="F1")
        capture = capture_skin(owner, bpy.context.scene, bpy.context.evaluated_depsgraph_get())
        self.assertFalse(any(item.entity_type == "FIBER" for item in capture.sources))
        self.assertEqual(next(item.gap_limit_ratio for item in capture.sources if item.entity_type == "MUSCLE"), .0025)

    def test_gap_overrides_and_mirrors_are_captured(self):
        root_obj = root()
        scp = scp_with_object(root_obj, "Bone", mesh_object("Bone"))
        mirror_scp(root_obj, scp)
        root_obj.af_draft_skin_settings.gap_limit_percent = 0.8
        inherited = capture_skin(root_obj, bpy.context.scene, bpy.context.evaluated_depsgraph_get())
        self.assertTrue(all(abs(source.gap_limit_ratio-0.008) < 1e-9 for source in inherited.sources))
        scp.skin_gap_mode = "OVERRIDE"
        scp.skin_gap_limit_percent = 0.2; scp.skin_gap_strength_percent = 25
        overridden = capture_skin(root_obj, bpy.context.scene, bpy.context.evaluated_depsgraph_get())
        self.assertTrue(all(abs(source.gap_limit_ratio-0.002) < 1e-9 for source in overridden.sources))
        self.assertTrue(all(source.gap_strength == 0.25 for source in overridden.sources))
        self.assertNotEqual(inherited.input_hash, overridden.input_hash)

    def test_native_records_export_gap_scalars(self):
        from anthroforge.core.importing.rna import scalar_dict, apply_scalar_dict
        root_obj = root()
        records = [root_obj.af_scp_system.scps.add()]
        records += [getattr(root_obj.af_vcp_system, name).add() for name in ("muscles", "fibers", "blobs", "soft_tissues")]
        for record in records:
            record.skin_gap_mode = "OVERRIDE"; record.skin_gap_limit_percent = 0.3
            record.skin_gap_strength_percent = 50
            payload = scalar_dict(record)
            record.skin_gap_limit_percent = 1
            apply_scalar_dict(record, payload)
            self.assertAlmostEqual(record.skin_gap_limit_percent, 0.3)
            self.assertEqual(record.skin_gap_strength_percent, 50)

    def test_gap_settings_survive_saved_file(self):
        root_obj = root(); name = root_obj.name
        scp = scp_with_object(root_obj, "Bone", mesh_object("Bone"))
        scp.skin_gap_mode = "OVERRIDE"; scp.skin_gap_limit_percent = 0.2
        root_obj.af_draft_skin_settings.gap_strength_percent = 75
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "gap_settings.blend")
            bpy.ops.wm.save_as_mainfile(filepath=path)
            bpy.ops.wm.open_mainfile(filepath=path)
            restored = bpy.data.objects[name]
            self.assertEqual(restored.af_draft_skin_settings.gap_strength_percent, 75)
            self.assertAlmostEqual(restored.af_scp_system.scps[0].skin_gap_limit_percent, 0.2)
            self.assertEqual(restored.af_scp_system.scps[0].skin_gap_mode, "OVERRIDE")

    def test_scp_collagen_properties_and_capture(self):
        root_obj = root()
        obj = mesh_object("Ear")
        scp = scp_with_object(root_obj, "Ear", obj)
        scp.skin_collagen_mode = "AUTO"
        capture = capture_skin(root_obj, bpy.context.scene, bpy.context.evaluated_depsgraph_get())
        self.assertEqual((len(capture.sources), capture.sources[0].entity_type), (1, "SCP"))
        self.assertTrue(np.allclose(capture.sources[0].collagen, 0.0))

    def test_root_settings_change_capture_contract_and_hash(self):
        root_obj = root()
        scp_with_object(root_obj, "Skull", mesh_object("Skull"))
        first = capture_skin(root_obj, bpy.context.scene, bpy.context.evaluated_depsgraph_get())
        root_obj.af_draft_skin_settings.collagen_depth_percent = 2.0
        second = capture_skin(root_obj, bpy.context.scene, bpy.context.evaluated_depsgraph_get())
        self.assertAlmostEqual(second.settings.collagen_depth_ratio, 0.02)
        self.assertNotEqual(first.input_hash, second.input_hash)

    def test_root_settings_expose_limits_and_reset_defaults(self):
        settings = root().af_draft_skin_settings
        settings.minimum_offset_percent = 1.5
        settings.collagen_falloff_percent = 8.0
        self.assertEqual(bpy.ops.af.reset_draft_skin_settings(), {"FINISHED"})
        self.assertAlmostEqual(settings.minimum_offset_percent, 0.5406473118473614)
        self.assertAlmostEqual(settings.collagen_falloff_percent, 3.964746953547317)
        rna = settings.bl_rna.properties
        self.assertEqual((rna["minimum_offset_percent"].hard_max, rna["collagen_falloff_percent"].hard_max), (2.0, 10.0))

    def test_paint_entry_initializes_only_unassigned_weights(self):
        root_obj = root()
        obj = mesh_object("Ear")
        scp = scp_with_object(root_obj, "Ear", obj)
        group = obj.vertex_groups.new(name="AF_SKIN_COLLAGEN")
        group.add([0], 0.25, "REPLACE")
        prepare_paint(bpy.context, scp)
        values = [group.weight(index) for index in range(3)]
        unified = bpy.context.scene.tool_settings.weight_paint.unified_paint_settings
        self.assertEqual((scp.skin_collagen_mode, scp.skin_collagen, obj.mode), ("PAINTED", 0.0, "WEIGHT_PAINT"))
        self.assertTrue(np.allclose(values, (0.25, 0.0, 0.0)))
        self.assertEqual((unified.use_unified_weight, unified.weight), (True, 0.0))
        finish_paint(bpy.context, scp)

    def test_fill_clear_and_brush_weight_actions(self):
        root_obj = root()
        obj = mesh_object("Skull")
        scp = scp_with_object(root_obj, "Skull", obj)
        scp.skin_collagen_mode, scp.skin_collagen = "PAINTED", 0.6
        group = fill_default(bpy.context, scp)
        set_brush_weight(bpy.context, 0.5)
        self.assertTrue(np.allclose([group.weight(index) for index in range(3)], 0.6))
        self.assertAlmostEqual(bpy.context.scene.tool_settings.weight_paint.unified_paint_settings.weight, 0.5)
        clear_map(bpy.context, scp)
        self.assertEqual(scp.skin_collagen_mode, "UNIFORM")
        self.assertIsNone(obj.vertex_groups.get("AF_SKIN_COLLAGEN"))

    def test_atomic_output_replaces_previous_and_writes_attribute(self):
        root_obj = root()
        vertices, faces = cube_arrays()
        validation = validate_mesh(vertices, faces)
        first = SkinResult(vertices, faces, np.ones(8), {"input_hash": "one"}, validation)
        second = SkinResult(vertices + 1.0, faces, np.zeros(8), {"input_hash": "two"}, validation)
        old = replace_draft_skin(bpy.context.scene, root_obj, first, [])
        old_pointer = old.as_pointer()
        old_mesh_pointer = old.data.as_pointer()
        new = replace_draft_skin(bpy.context.scene, root_obj, second, [])
        skins = [obj for obj in bpy.context.scene.objects if obj.get("af_draft_skin")]
        self.assertEqual((len(skins), new.as_pointer(), new["af_skin_input_hash"]), (1, old_pointer, "two"))
        self.assertNotEqual(new.data.as_pointer(), old_mesh_pointer)
        self.assertIsNotNone(new.data.attributes.get("af_skin_collagen"))

    def test_capture_filters_final_contributors_and_hidden_objects(self):
        root_obj = root(); scp = scp_with_object(root_obj, "Skull", mesh_object("Skull"))
        vcp_record(root_obj.af_vcp_system.muscles, "M1")
        vcp_record(root_obj.af_vcp_system.fibers, "F1", "M1")
        vcp_record(root_obj.af_vcp_system.fibers, "F2")
        tag(mesh_object("Infl"), root_obj, af_muscle_proxy=True, af_muscle_id="M1", af_muscle_surface="INFL")
        tag(mesh_object("Base"), root_obj, af_muscle_proxy=True, af_muscle_id="M1", af_muscle_surface="BASE")
        tag(mesh_object("Consumed"), root_obj, af_fiber_proxy=True, af_fiber_id="F1")
        tag(mesh_object("Standalone"), root_obj, af_fiber_proxy=True, af_fiber_id="F2")
        tag(mesh_object("Blob"), root_obj, af_blob_proxy=True, af_blob_id="B1")
        depsgraph = bpy.context.evaluated_depsgraph_get()
        mirror_scp(root_obj, scp, "Skull Mirror").hide_viewport = True
        capture = capture_skin(root_obj, bpy.context.scene, depsgraph)
        roles = [(item.entity_type, item.entity_id) for item in capture.sources]
        self.assertEqual(set(roles), {("SCP", scp.id), ("MUSCLE", "M1"), ("FIBER", "F2"), ("BLOB", "B1")})
        self.assertEqual(sum(item.entity_type == "SCP" for item in capture.sources), 2)

    def test_painted_values_transfer_to_mirror_and_mismatch_warns(self):
        root_obj = root(); source = mesh_object("Nose")
        scp = scp_with_object(root_obj, "Nose", source)
        scp.skin_collagen_mode, scp.skin_collagen = "PAINTED", 0.6
        group = source.vertex_groups.new(name="AF_SKIN_COLLAGEN")
        group.add([0], 0.2, "REPLACE")
        group.add([1], 0.8, "REPLACE")
        mirror_scp(root_obj, scp)
        mismatch = mirror_scp(root_obj, scp, "Mismatch")
        mismatch.data.clear_geometry()
        mismatch.data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)], [], [(0, 1, 2), (0, 1, 3)])
        capture = capture_skin(root_obj, bpy.context.scene, bpy.context.evaluated_depsgraph_get())
        records = {item.object_name: item for item in capture.sources}
        self.assertTrue(np.allclose(records["Ear Mirror"].collagen, (0.2, 0.8, 0.6)))
        self.assertTrue(np.allclose(records["Mismatch"].collagen, 0.6))
        self.assertTrue(any("mismatch" in warning.lower() for warning in capture.warnings))

    def test_failed_output_import_preserves_previous_skin(self):
        root_obj = root()
        vertices, faces = cube_arrays()
        result = SkinResult(vertices, faces, np.ones(8), {}, validate_mesh(vertices, faces))
        previous = replace_draft_skin(bpy.context.scene, root_obj, result, [])
        with mock.patch.object(output_adapter, "_tag_object", side_effect=RuntimeError("bad output")):
            with self.assertRaises(RuntimeError):
                replace_draft_skin(bpy.context.scene, root_obj, result, [])
        skins = [obj for obj in bpy.context.scene.objects if obj.get("af_draft_skin")]
        self.assertEqual((len(skins), skins[0].as_pointer()), (1, previous.as_pointer()))

    def test_gap_validation_failure_preserves_previous_skin(self):
        root_obj = root(); vertices, faces = cube_arrays()
        result = SkinResult(vertices, faces, np.ones(8), {}, validate_mesh(vertices, faces))
        previous = replace_draft_skin(bpy.context.scene, root_obj, result, [])
        mesh_pointer = previous.data.as_pointer()
        result.statistics['protected_gap_violations'] = 1
        with self.assertRaisesRegex(ValueError, 'protected_gap_violations'):
            replace_draft_skin(bpy.context.scene, root_obj, result, [])
        self.assertEqual(previous.data.as_pointer(), mesh_pointer)

    def test_undo_restores_previous_result(self):
        root_obj = root()
        vertices, faces = cube_arrays()
        validation = validate_mesh(vertices, faces)
        first = SkinResult(vertices, faces, np.ones(8), {"input_hash": "one"}, validation)
        second = SkinResult(vertices + 1.0, faces, np.zeros(8), {"input_hash": "two"}, validation)
        replace_draft_skin(bpy.context.scene, root_obj, first, [])
        bpy.ops.ed.undo_push(message="Draft skin first")
        replace_draft_skin(bpy.context.scene, root_obj, second, [])
        bpy.ops.ed.undo_push(message="Draft skin second")
        bpy.ops.ed.undo()
        restored = bpy.context.scene.objects.get("AF_DRAFT_SKIN")
        self.assertEqual(restored["af_skin_input_hash"], "one")

    def test_worker_rewrites_manifest_and_completes(self):
        vertices, faces = cube_arrays()
        source = SkinSource(0, "SCP", "S1", "ORIGINAL", "Cube", vertices, faces, np.ones(8))
        digest = capture_hash("ROOT", (source,))
        capture = SkinCapture("ROOT", (source,), vertices.min(0), vertices.max(0), digest, 1 / 32, 32)
        with tempfile.TemporaryDirectory(prefix="af_worker_smoke_") as folder:
            spec = worker_spec(folder)
            write_job(spec)
            with mock.patch.object(draft_skin_worker, "_bake_and_capture", return_value=capture):
                draft_skin_worker.run_job(Path(folder))
            status, result = read_status(spec.status_path), read_result(spec.result_path)
            updated = read_job(Path(folder) / "job.json")
        self.assertEqual((status.state, result.validation.valid, updated.input_hash), ("SUCCEEDED", True, digest))


if __name__ == "__main__":
    import unittest
    unittest.main()
