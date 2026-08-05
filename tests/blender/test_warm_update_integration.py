from unittest import mock

import bpy
import numpy as np

from _helpers import BlenderTestCase, root
from adapters.draft_skin.vendor import ensure_worker_dependencies
ensure_worker_dependencies()
from adapters.warm_update import output as warm_output
from adapters.warm_update import migration
from core.draft_skin.model import SkinCapture, SkinResult, SkinSolverSettings, SkinSource
from core.draft_skin.validation import validate_mesh
from core.topology.model import TopologyCapture, TopologyResult
from core.topology.validation import validate_topology


class WarmUpdateIntegrationTests(BlenderTestCase):
    def test_prepare_legacy_outputs_preserves_meshes_and_adds_bindings(self):
        root_obj = root(); skin, topology = warm_output.replace_outputs(
            bpy.context.scene, root_obj, _skin_result(0.0), _topology_result(0.0))
        topology.data.attributes.remove(topology.data.attributes["af_topology_bind_schema"])
        skin_before, topology_before = _points(skin), _points(topology)
        skin_result = migration.prepare_skin(root_obj, bpy.context.scene, _skin_capture())
        topology_result = migration.prepare_topology(root_obj, bpy.context.scene, _topology_capture())
        warm_output.replace_outputs(bpy.context.scene, root_obj, skin_result, topology_result)
        np.testing.assert_array_equal(_points(skin), skin_before)
        np.testing.assert_array_equal(_points(topology), topology_before)
        self.assertIsNotNone(skin.data.attributes.get("af_skin_bind_schema"))
        self.assertIsNotNone(topology.data.attributes.get("af_topology_bind_schema"))

    def test_legacy_outputs_remain_usable_without_migration(self):
        root_obj = root(); skin, topology = warm_output.replace_outputs(
            bpy.context.scene, root_obj, _skin_result(0.0), _topology_result(0.0))
        topology.data.attributes.remove(topology.data.attributes["af_topology_bind_schema"])
        state = migration.migration_state(root_obj, bpy.context.scene)
        self.assertEqual(state, {"skin": True, "topology": True})
        self.assertEqual((len(skin.data.vertices), len(topology.data.polygons)), (8, 6))

    def test_coordinated_output_replaces_both_meshes(self):
        root_obj = root()
        first = warm_output.replace_outputs(bpy.context.scene, root_obj,
                                            _skin_result(0.0), _topology_result(0.0))
        second = warm_output.replace_outputs(bpy.context.scene, root_obj,
                                             _skin_result(1.0), _topology_result(1.0))
        self.assertEqual([item.name for item in second], ["AF_DRAFT_SKIN", "AF_TOPOLOGY"])
        self.assertEqual(second[0]["af_skin_input_hash"], "1.0")
        self.assertEqual(second[1]["af_topology_input_hash"], "1.0")
        self.assertEqual([item.as_pointer() for item in first], [item.as_pointer() for item in second])

    def test_failed_coordinated_import_restores_both_outputs(self):
        root_obj = root()
        skin, topology = warm_output.replace_outputs(bpy.context.scene, root_obj,
                                                     _skin_result(0.0), _topology_result(0.0))
        old_skin = np.asarray([vertex.co[:] for vertex in skin.data.vertices])
        with mock.patch.object(warm_output.topology_output, "_tag", side_effect=RuntimeError("bad topology")):
            with self.assertRaises(RuntimeError):
                warm_output.replace_outputs(bpy.context.scene, root_obj,
                                            _skin_result(2.0), _topology_result(2.0))
        np.testing.assert_allclose([vertex.co[:] for vertex in skin.data.vertices], old_skin)
        self.assertEqual(skin["af_skin_input_hash"], "0.0")
        self.assertEqual(topology["af_topology_input_hash"], "0.0")

    def test_operator_groups_replacement_in_one_undo_step(self):
        from anthroforge.operators.warm_update import AF_OT_UpdateSkinTopology
        self.assertIn("UNDO", AF_OT_UpdateSkinTopology.bl_options)


def _cube(offset):
    vertices = np.asarray(((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                           (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)), float) + offset
    triangles = np.asarray(((0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
                            (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
                            (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)), np.int32)
    return vertices, triangles


def _skin_result(offset):
    vertices, triangles = _cube(offset)
    return SkinResult(vertices, triangles, np.ones(8), {"input_hash": str(offset)},
                      validate_mesh(vertices, triangles))


def _topology_result(offset):
    vertices, _triangles = _cube(offset)
    quads = np.asarray(((0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1),
                        (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)), np.int32)
    regions, guides = np.zeros(6, np.int32), np.full(6, -1, np.int32)
    return TopologyResult(vertices, quads, regions, guides, {"input_hash": str(offset)},
                          validate_topology(vertices, quads))


def _skin_capture():
    vertices, triangles = _cube(0.0)
    source = SkinSource(0, "SCP", "cube", "ORIGINAL", "Cube", vertices, triangles)
    return SkinCapture("AF_ROOT", (source,), vertices.min(0), vertices.max(0), "hash",
                       0.01, settings=SkinSolverSettings())


def _topology_capture():
    vertices, triangles = _cube(0.0)
    return TopologyCapture("AF_ROOT", vertices, triangles, (), vertices.min(0),
                           vertices.max(0), "hash")


def _points(obj):
    return np.asarray([vertex.co[:] for vertex in obj.data.vertices])
