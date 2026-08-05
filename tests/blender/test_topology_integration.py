from pathlib import Path
import sys

import numpy as np
import bpy

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(Path(__file__).parent), str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

from _helpers import BlenderTestCase, mesh_object, root, scp_with_object
from adapters.topology.capture import capture_topology
from adapters.topology.engine import annuli, instant
from adapters.topology.output import replace_topology
from core.topology.model import TopologyResult
from core.topology.validation import validate_topology


def cube_arrays():
    vertices = np.asarray([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                           (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)], dtype=float)
    quads = np.asarray([(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                        (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)], dtype=np.int32)
    return vertices, quads


def draft_skin(root_obj):
    vertices, quads = cube_arrays()
    mesh = bpy.data.meshes.new("Draft")
    mesh.from_pydata(vertices.tolist(), [], quads.tolist())
    obj = bpy.data.objects.new("AF_DRAFT_SKIN", mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj["af_draft_skin"], obj["af_root_name"] = True, root_obj.name
    return obj


def loop_proxy(root_obj, fiber_id, name, mirror=False):
    curve = bpy.data.curves.new(name, "CURVE")
    spline = curve.splines.new("POLY"); spline.points.add(3)
    spline.points.foreach_set("co", (0, 0, 0, 1, 1, 0, 0, 1, 1, 1, 0, 1, 0, 1, 0, 1))
    spline.use_cyclic_u = True
    obj = bpy.data.objects.new(name, curve); bpy.context.scene.collection.objects.link(obj)
    obj["af_fiber_proxy"], obj["af_fiber_id"] = True, fiber_id
    obj["af_root_name"], obj["af_fiber_mirror_proxy"] = root_obj.name, mirror
    return obj


def topology_result(offset=0.0):
    vertices, quads = cube_arrays(); vertices += offset
    regions = np.zeros(len(quads), dtype=np.int32)
    guides = np.full(len(quads), -1, dtype=np.int32)
    stats = {"input_hash": str(offset), "guide_map": []}
    owners = np.zeros(len(vertices), dtype=np.int32)
    lengths = np.full(len(vertices), 0.25, dtype=np.float32)
    return TopologyResult(vertices, quads, regions, guides, stats,
                          validate_topology(vertices, quads), owners, lengths)


def closure_fixture(connected=True):
    from adapters.draft_skin.vendor import ensure_worker_dependencies
    ensure_worker_dependencies()
    from scipy.sparse import coo_matrix
    from scipy.spatial import cKDTree
    vertices = np.column_stack((np.arange(4.0), np.zeros((4, 2))))
    edges = ((0, 1), (1, 0), (1, 2), (2, 1), (2, 3), (3, 2)) if connected else ((0, 1), (1, 0))
    graph = coo_matrix((np.ones(len(edges)), tuple(zip(*edges))), shape=(4, 4)).tocsr()
    points = np.asarray(((3, 0, 0), (2.9, .01, 0), (2.8, 0, 0), (0, 0, 0)))
    return points, graph, cKDTree(vertices), vertices


class TopologyIntegrationTests(BlenderTestCase):
    def test_guide_cut_stops_at_authored_outer_ring(self):
        ring = np.asarray(((-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)), dtype=float)
        vertices = np.asarray(((0.8, -.1, 0), (.9, .1, 0), (1, 0, 0),
                               (1.05, -.1, 0), (1.15, .1, 0), (1.1, 0, 0)))
        faces = np.asarray(((0, 1, 2), (3, 4, 5)), dtype=np.int32)
        np.testing.assert_array_equal(instant.guide_face_mask(vertices, faces, ring), (True, False))

    def test_plane_coordinates_support_arbitrary_symmetry(self):
        normal = np.asarray((1.0, 1.0, 0.0)); normal /= np.linalg.norm(normal)
        plane = instant.SymmetryPlane(np.asarray((1.0, 2.0, 3.0)), normal)
        points = np.asarray(((2.0, 2.0, 4.0), (1.0, 3.0, 2.0)))
        mirrored = instant.reflect_points(points, plane)
        first, second = instant.plane_coordinates(points, plane), instant.plane_coordinates(mirrored, plane)
        np.testing.assert_allclose(first[:, 0], -second[:, 0])
        np.testing.assert_allclose(first[:, 1:], second[:, 1:])

    def test_transition_mismatch_names_guide(self):
        boundary = np.asarray(((0, 0, 1), (0, 1, 0), (0, 0, -1), (0, -1, 0)), dtype=float)
        ring = boundary + np.asarray((2, 0, 0)); plane = instant.SymmetryPlane(np.zeros(3), np.asarray((1, 0, 0)))
        with self.assertRaisesRegex(RuntimeError, "EyeGuide"):
            instant.make_transition("EyeGuide", (boundary, ring), 4.0, plane)

    def test_local_guide_closure_keeps_points(self):
        points = np.asarray(((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)))
        result = annuli.geodesic_closure(points, None, None, None, "Local")
        np.testing.assert_array_equal(result, points)

    def test_nonlocal_guide_closure_selects_vertex_rows(self):
        points, graph, tree, vertices = closure_fixture()
        result = annuli.geodesic_closure(points, graph, tree, vertices, "FIBER_18")
        np.testing.assert_array_equal(result[-2:], vertices[[1, 2]])

    def test_unreachable_guide_closure_keeps_points(self):
        points, graph, tree, vertices = closure_fixture(False)
        result = annuli.geodesic_closure(points, graph, tree, vertices, "Detached")
        np.testing.assert_array_equal(result, points)

    def test_invalid_guide_closure_names_guide(self):
        with self.assertRaisesRegex(RuntimeError, "BrokenGuide"):
            annuli.validated_path_indices((0, 5, 3), 0, 3, 4, "BrokenGuide")
        with self.assertRaisesRegex(RuntimeError, "WrongEnds"):
            annuli.validated_path_indices((1, 2, 3), 0, 3, 4, "WrongEnds")

    def test_capture_requires_current_root_skin(self):
        with self.assertRaisesRegex(ValueError, "draft skin"):
            capture_topology(root(), bpy.context.scene, bpy.context.evaluated_depsgraph_get())

    def test_capture_filters_closed_root_guides(self):
        root_obj = root(); draft_skin(root_obj)
        closed = root_obj.af_vcp_system.fibers.add(); closed.id = "F1"; closed.topology_mode = "LOOP"
        opened = root_obj.af_vcp_system.fibers.add(); opened.id = "F2"; opened.topology_mode = "OPEN"
        loop_proxy(root_obj, "F1", "Closed"); loop_proxy(root_obj, "F2", "Open")
        capture = capture_topology(root_obj, bpy.context.scene, bpy.context.evaluated_depsgraph_get())
        self.assertEqual([(guide.fiber_id, guide.object_name) for guide in capture.guides], [("F1", "Closed")])

    def test_custom_plane_uses_inverse_transpose_normal(self):
        root_obj = root(); draft_skin(root_obj)
        root_obj.scale = (2.0, 1.0, 0.5)
        settings = root_obj.af_topology_settings
        settings.symmetry_mode = "CUSTOM"; settings.custom_normal = (1.0, 0.0, 1.0)
        capture = capture_topology(root_obj, bpy.context.scene, bpy.context.evaluated_depsgraph_get())
        self.assertTrue(np.allclose(capture.plane.normal, np.asarray((0.25, 0, 1.0)) / np.linalg.norm((0.25, 0, 1.0))))

    def test_capture_includes_refinement_strategy(self):
        root_obj = root(); draft_skin(root_obj)
        root_obj.af_topology_settings.refinement_strategy = "NONE"
        capture = capture_topology(root_obj, bpy.context.scene, bpy.context.evaluated_depsgraph_get())
        self.assertEqual(capture.settings.refinement_strategy, "NONE")

    def test_atomic_output_replaces_mesh_and_writes_attributes(self):
        root_obj = root()
        first = replace_topology(bpy.context.scene, root_obj, topology_result())
        object_pointer, mesh_pointer = first.as_pointer(), first.data.as_pointer()
        second = replace_topology(bpy.context.scene, root_obj, topology_result(1.0))
        self.assertEqual((second.as_pointer(), second.name), (object_pointer, "AF_TOPOLOGY"))
        self.assertNotEqual(second.data.as_pointer(), mesh_pointer)
        self.assertIsNotNone(second.data.attributes.get("af_topology_region"))
        self.assertIsNotNone(second.data.attributes.get("af_topology_owner_scp_index"))
        self.assertIsNotNone(second.data.attributes.get("af_topology_target_edge_length"))
        self.assertEqual(second["af_topology_input_hash"], "1.0")

    def test_capture_includes_density_rule_and_scp_ownership_source(self):
        root_obj = root(); draft_skin(root_obj)
        obj = mesh_object("Cranium")
        scp = scp_with_object(root_obj, "Cranium", obj)
        obj["af_scp_geometry"], obj["af_root_name"], obj["af_scp_id"] = True, root_obj.name, scp.id
        scp.topology_density_mode, scp.topology_subtree_quads = "SUBTREE_BUDGET", 4000
        capture = capture_topology(root_obj, bpy.context.scene, bpy.context.evaluated_depsgraph_get())
        self.assertEqual((capture.density_rules[0].mode, capture.density_rules[0].subtree_quads),
                         ("SUBTREE_BUDGET", 4000))
        self.assertEqual(capture.ownership_sources[0].owner_scp_ids, (scp.id,))


if __name__ == "__main__":
    import unittest
    unittest.main()
