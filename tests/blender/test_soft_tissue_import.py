from pathlib import Path
import os
import sys

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy

from _helpers import BlenderTestCase, mesh_object, reset_scene, root, scp_with_object, temp_blend_path
from anthroforge.core.importing.service import import_package_from_blend, import_vcp_from_blend
from anthroforge.core.vcp.runtime_state import soft_tissue_status
from anthroforge.core.visualization.soft_tissue_sync import register_soft_tissue_sync


def _quad(name):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(((-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)), (), ((0, 1, 2, 3),))
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _source_file():
    host = _quad("SourceHost")
    scp = scp_with_object(root(), "Source Host", host)
    base = _quad("SourceBase")
    scene = bpy.context.scene
    scene.af_new_soft_tissue_preset = "LAYER"
    scene.af_new_soft_tissue_base_obj, scene.af_new_soft_tissue_host_obj = base, host
    if bpy.ops.af.add_soft_tissue_vcp() != {"FINISHED"}:
        raise AssertionError("Could not create source tissue")
    path = temp_blend_path()
    bpy.ops.wm.save_as_mainfile(filepath=path)
    return path, scp.id


def _proxy(tissue_id):
    return next((obj for obj in bpy.context.scene.objects if obj.get("af_soft_tissue_proxy")
                 and obj.get("af_soft_tissue_id") == tissue_id), None)


class SoftTissueImportTests(BlenderTestCase):
    def test_vcp_import_skips_incompatible_soft_tissue_host(self):
        path, host_id = _source_file()
        self.addCleanup(lambda: os.remove(path) if os.path.exists(path) else None)
        reset_scene()
        root_obj = root()
        target = scp_with_object(root_obj, "Target Host", mesh_object("TriangleHost"))
        self.assertEqual(target.id, host_id)
        result = import_vcp_from_blend(path, bpy.context)
        self.assertEqual((result.soft_tissue_count, len(root_obj.af_vcp_system.soft_tissues)), (0, 0))
        self.assertTrue(any("incompatible" in warning for warning in result.warnings))

    def test_full_package_remaps_host_and_retains_base(self):
        path, _host_id = _source_file()
        self.addCleanup(lambda: os.remove(path) if os.path.exists(path) else None)
        reset_scene()
        root_obj = root()
        scp_with_object(root_obj, "Existing", _quad("ExistingHost"))
        result = import_package_from_blend(path, bpy.context)
        tissue = root_obj.af_vcp_system.soft_tissues[-1]
        host = next(item for item in root_obj.af_scp_system.scps if item.name == "SourceHost")
        register_soft_tissue_sync().sync_root_to_scene(root_obj, bpy.context.scene, {tissue.id}, force=True)
        self.assertEqual((result.scp_count, result.soft_tissue_count, tissue.host_scp_id), (1, 1, host.id))
        self.assertEqual((tissue.base_object_ref.get("af_soft_tissue_id"), soft_tissue_status(tissue)), (tissue.id, "CLEAN"))

    def test_vcp_import_retains_referenced_base_and_rebuilds(self):
        path, host_id = _source_file()
        self.addCleanup(lambda: os.remove(path) if os.path.exists(path) else None)
        reset_scene()
        root_obj = root()
        target = scp_with_object(root_obj, "Target Host", _quad("TargetHost"))
        self.assertEqual(target.id, host_id)
        result = import_vcp_from_blend(path, bpy.context)
        tissue = root_obj.af_vcp_system.soft_tissues[-1]
        register_soft_tissue_sync().sync_root_to_scene(root_obj, bpy.context.scene, {tissue.id}, force=True)
        self.assertEqual((result.soft_tissue_count, tissue.host_scp_id), (1, target.id))
        self.assertEqual(tissue.base_object_ref.get("af_soft_tissue_id"), tissue.id)
        self.assertIn(tissue.base_object_ref, tuple(bpy.context.scene.objects))
        self.assertEqual((soft_tissue_status(tissue), _proxy(tissue.id) is not None), ("CLEAN", True))


if __name__ == "__main__":
    import unittest
    unittest.main()
