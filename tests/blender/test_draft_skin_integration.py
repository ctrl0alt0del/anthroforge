from pathlib import Path
import sys
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
from adapters.draft_skin import output as output_adapter
from adapters.draft_skin.output import replace_draft_skin
from adapters.draft_skin.vendor import ensure_worker_dependencies

ensure_worker_dependencies()

from core.draft_skin.mesh import orient_outward
from core.draft_skin.model import SkinResult
from core.draft_skin.validation import validate_mesh


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


class DraftSkinIntegrationTests(BlenderTestCase):
    def test_scp_collagen_properties_and_capture(self):
        root_obj = root()
        obj = mesh_object("Ear")
        scp = scp_with_object(root_obj, "Ear", obj)
        scp.skin_collagen_mode = "AUTO"
        capture = capture_skin(root_obj, bpy.context.scene, bpy.context.evaluated_depsgraph_get())
        self.assertEqual((len(capture.sources), capture.sources[0].entity_type), (1, "SCP"))
        self.assertTrue(np.allclose(capture.sources[0].collagen, 0.0))

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
        root_obj = root()
        scp = scp_with_object(root_obj, "Skull", mesh_object("Skull"))
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
        root_obj = root()
        source = mesh_object("Nose")
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


if __name__ == "__main__":
    import unittest
    unittest.main()
