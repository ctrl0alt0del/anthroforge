import unittest
from dataclasses import FrozenInstanceError

import numpy as np

from core.vcp.muscle_domain_clip import clip_domain
from core.vcp.branched_surface import BranchInput, prepare_assembly, assemble


def plane(offset=0., normal=(1., 0., 0.), keep_positive=True):
    return dict(normal=normal, offset=offset, keep_positive=keep_positive)


def points(xy):
    return np.column_stack((np.asarray(xy, dtype=float), np.zeros(len(xy))))


def area(result):
    triangles = result.base_vertices[result.faces]
    return np.linalg.norm(np.cross(triangles[:, 1] - triangles[:, 0],
                                   triangles[:, 2] - triangles[:, 0]), axis=1).sum() / 2


def affine(values):
    matrix = np.array([[-2., .3, 1.], [.2, 3., -.4], [1., .5, 2.]])
    return values @ matrix + [-10., 3., 1.]


def branched_fixture():
    z = np.linspace(-2., 2., 17)
    main = tuple(np.column_stack((np.full(17, x), np.zeros(17), z)) for x in (-1., 1.))
    children = tuple(np.linspace(main[-1][i], main[-1][i] + [0., 2., .3], 9) for i in (4, 12))
    prepared = prepare_assembly(main, (BranchInput('child', -1, (4, 12), children),))
    base, faces = assemble(prepared)
    main_faces = (prepared.main.shape[0] - 1) * (prepared.main.shape[1] - 1)
    parts = np.r_[np.zeros(main_faces, dtype=int), np.ones(len(faces) - main_faces, dtype=int)]
    return base, faces, parts


class MuscleDomainClipTests(unittest.TestCase):
    def setUp(self):
        self.base = points([(-1, -1), (1, -1), (1, 1), (-1, 1)])
        self.faces = np.array([(0, 1, 2), (0, 2, 3)])

    def test_retained_quad_compacts_and_preserves_area(self):
        base = np.vstack((self.base, [99., 99., 99.]))
        result = clip_domain(base, affine(base), [(0, 1, 2, 3)], plane(-2), ['H'])
        np.testing.assert_array_equal(result.base_vertices, self.base)
        np.testing.assert_array_equal(result.faces, self.faces)
        np.testing.assert_array_equal(result.source_faces, [0, 0])
        np.testing.assert_array_equal(result.face_parts, ['H', 'H'])
        self.assertEqual(area(result), 4.)

    def test_removed_domain_has_consistent_empty_shapes(self):
        result = clip_domain(self.base, self.base, self.faces, plane(2), ['H', 'U'])
        self.assertEqual(result.base_vertices.shape, (0, 3))
        self.assertEqual(result.inflated_vertices.shape, (0, 3))
        self.assertEqual(result.faces.shape, (0, 3))
        self.assertEqual(result.source_faces.shape, (0,))
        self.assertEqual(result.face_parts.shape, (0,))
        self.assertEqual(result.face_parts.dtype.kind, 'U')

    def test_empty_mesh_and_faceless_mesh(self):
        for base in (np.empty((0, 3)), self.base):
            result = clip_domain(base, base, [], plane())
            self.assertEqual(result.base_vertices.shape, (0, 3))
            self.assertEqual(result.faces.shape, (0, 3))
            self.assertIsNone(result.face_parts)

    def test_base_decides_cut_and_both_positions_share_weights(self):
        result = clip_domain(self.base, affine(self.base), self.faces, plane(.25))
        self.assertTrue(np.all(result.base_vertices[:, 0] >= .25))
        self.assertTrue(np.all(result.inflated_vertices[:, 0] < 0))
        np.testing.assert_allclose(result.inflated_vertices, affine(result.base_vertices))
        self.assertAlmostEqual(area(result), 1.5)

    def test_reversed_shared_edge_produces_one_welded_intersection(self):
        result = clip_domain(self.base, self.base, self.faces, plane(), [11, 29])
        center = np.flatnonzero(np.all(result.base_vertices == 0., axis=1))
        self.assertEqual(len(center), 1)
        self.assertEqual(len(result.base_vertices), 5)
        self.assertEqual(len(result.faces), 3)
        incident = np.any(result.faces == center[0], axis=1)
        self.assertEqual(set(result.face_parts[incident]), {11, 29})
        np.testing.assert_array_equal(result.face_parts, np.array([11, 29])[result.source_faces])
        self.assertAlmostEqual(area(result), 2.)

    def test_distinct_coincident_vertices_are_not_implicitly_welded(self):
        base = np.vstack((self.base, self.base))
        faces = np.array([(0, 1, 2), (4, 6, 7)])
        result = clip_domain(base, base, faces, plane())
        self.assertEqual(np.sum(np.all(result.base_vertices == 0., axis=1)), 2)

    def test_tangent_line_and_point_remnants_are_omitted(self):
        for xy in ([(-1, 0), (0, 0), (0, 1)], [(-1, 0), (-1, 1), (0, 0)]):
            base = points(xy)
            result = clip_domain(base, base, [(0, 1, 2)], plane())
            self.assertEqual(result.faces.shape, (0, 3))
            self.assertEqual(result.base_vertices.shape, (0, 3))

    def test_coplanar_face_is_retained_without_duplicate_vertices(self):
        base = np.array([(0., 0., 0.), (0., 2., 0.), (0., 0., 3.)])
        result = clip_domain(base, affine(base), [(0, 1, 2)], plane())
        np.testing.assert_array_equal(result.base_vertices, base)
        np.testing.assert_array_equal(result.faces, [(0, 1, 2)])
        self.assertEqual(area(result), 3.)

    def test_cut_through_existing_vertex_uses_its_identity(self):
        base = points([(0, 0), (1, 1), (-1, 1)])
        result = clip_domain(base, base, [(0, 1, 2)], plane())
        self.assertEqual(len(result.base_vertices), 3)
        self.assertEqual(len(result.faces), 1)
        self.assertEqual(np.sum(np.all(result.base_vertices == 0., axis=1)), 1)
        self.assertAlmostEqual(area(result), .5)

    def test_complementary_sides_conserve_input_area(self):
        positive = clip_domain(self.base, self.base, self.faces, plane(.3))
        negative = clip_domain(self.base, self.base, self.faces, plane(.3, keep_positive=False))
        equivalent = clip_domain(self.base, self.base, self.faces, plane(-.3, (-1., 0., 0.)))
        self.assertAlmostEqual(area(positive) + area(negative), 4.)
        np.testing.assert_array_equal(negative.base_vertices, equivalent.base_vertices)
        np.testing.assert_array_equal(negative.faces, equivalent.faces)

    def test_mirrored_plane_preserves_corresponding_material_domain(self):
        mirror = np.diag([-1., 1., 1.])
        first = clip_domain(self.base, affine(self.base), self.faces, plane(.2))
        second = clip_domain(self.base @ mirror, affine(self.base) @ mirror,
                             self.faces, plane(.2, (-1., 0., 0.)))
        np.testing.assert_allclose(second.base_vertices, first.base_vertices @ mirror)
        np.testing.assert_allclose(second.inflated_vertices, first.inflated_vertices @ mirror)
        np.testing.assert_array_equal(second.faces, first.faces)
        np.testing.assert_array_equal(second.source_faces, first.source_faces)

    def test_actual_native_branch_retains_one_shared_cut_vertex(self):
        base, faces, parts = branched_fixture()
        result = clip_domain(base, affine(base), faces, plane(.137, (0., 0., 1.)), parts)
        seam = np.flatnonzero(np.all(np.isclose(result.base_vertices, [1., 0., .137]), axis=1))
        self.assertEqual(len(seam), 1)
        incident = np.any(result.faces == seam[0], axis=1)
        self.assertEqual(set(result.face_parts[incident]), {0, 1})
        edges = np.sort(result.faces[:, (0, 1, 1, 2, 2, 0)].reshape((-1, 2)), axis=1)
        _, counts = np.unique(edges, axis=0, return_counts=True)
        self.assertLessEqual(counts.max(), 2)
        np.testing.assert_allclose(result.inflated_vertices, affine(result.base_vertices))

    def test_nonplanar_quad_cut_conserves_its_triangulated_area(self):
        base = self.base.copy()
        base[2, 2] = 1.
        full = clip_domain(base, base, [(0, 1, 2, 3)], plane(-2))
        positive = clip_domain(base, base, [(0, 1, 2, 3)], plane(.2))
        negative = clip_domain(base, base, [(0, 1, 2, 3)], plane(.2, keep_positive=False))
        self.assertAlmostEqual(area(positive) + area(negative), area(full))
        np.testing.assert_array_equal(full.faces, self.faces)

    def test_concave_polygon_cut_does_not_bridge_disconnected_arms(self):
        base = points([(0, 0), (3, 0), (3, 3), (2, 3), (2, 1), (1, 1), (1, 3), (0, 3)])
        for face in (tuple(range(8)), tuple(reversed(range(8)))):
            result = clip_domain(base, affine(base), [face], plane(2, (0., 1., 0.)), ['U'])
            triangles = result.base_vertices[result.faces]
            no_bridge = (triangles[:, :, 0].max(axis=1) <= 1) | (triangles[:, :, 0].min(axis=1) >= 2)
            self.assertTrue(np.all(no_bridge))
            self.assertAlmostEqual(area(result), 2.)
            np.testing.assert_allclose(result.inflated_vertices, affine(result.base_vertices))
            self.assertTrue(np.all(result.source_faces == 0))

    def test_concave_quad_and_reversed_winding_have_correct_area(self):
        base = points([(0, 0), (3, 0), (.5, .5), (0, 3)])
        for face in ((0, 1, 2, 3), (3, 2, 1, 0)):
            result = clip_domain(base, base, [face], plane(-1))
            self.assertAlmostEqual(area(result), 1.5)
            normals = np.cross(*np.moveaxis(result.base_vertices[result.faces][:, 1:] -
                                           result.base_vertices[result.faces][:, :1], 1, 0))
            self.assertTrue(np.all(normals[:, 2] > 0) if face[0] == 0 else np.all(normals[:, 2] < 0))

    def test_small_nondegenerate_geometry_is_not_removed_by_absolute_area(self):
        base = points([(0, 0), (1e-9, 0), (0, 1e-9)])
        result = clip_domain(base, base, [(0, 1, 2)], plane(-1))
        self.assertEqual(len(result.faces), 1)
        self.assertAlmostEqual(area(result) / 5e-19, 1.)

    def test_degenerate_and_repeated_closing_vertices(self):
        base = np.vstack((self.base, points([(0, 2), (0, 3), (0, 4)])))
        faces = [(4, 5, 6), (0, 0, 1, 2, 3, 0), (1, 1, 1)]
        result = clip_domain(base, base, faces, plane(-2))
        self.assertEqual(len(result.faces), 2)
        np.testing.assert_array_equal(result.source_faces, [1, 1])
        self.assertAlmostEqual(area(result), 4.)

    def test_near_plane_tolerance_does_not_move_original_coordinates(self):
        base = points([(-1e-12, 0), (1, 0), (-1e-12, 1)])
        result = clip_domain(base, base, [(0, 1, 2)], plane())
        np.testing.assert_array_equal(result.base_vertices, base)
        strict = clip_domain(base, base, [(0, 1, 2)], plane(), tolerance=0.)
        self.assertTrue(np.all(strict.base_vertices[:, 0] >= -1e-16))

    def test_plane_scaling_preserves_locus_and_metric_tolerance(self):
        expected = clip_domain(self.base, self.base, self.faces, plane(.25))
        result = clip_domain(self.base, self.base, self.faces, plane(2.5, (10., 0., 0.)))
        np.testing.assert_array_equal(result.base_vertices, expected.base_vertices)
        np.testing.assert_array_equal(result.faces, expected.faces)

    def test_determinism_input_immutability_and_independent_output_arrays(self):
        base, inflated, faces = self.base.copy(), affine(self.base), self.faces.copy()
        saved = (base.copy(), inflated.copy(), faces.copy())
        first = clip_domain(base, inflated, faces, plane())
        second = clip_domain(base, inflated, faces, plane())
        np.testing.assert_array_equal(first.base_vertices, second.base_vertices)
        np.testing.assert_array_equal(first.faces, second.faces)
        for current, original in zip((base, inflated, faces), saved):
            np.testing.assert_array_equal(current, original)
        self.assertFalse(np.shares_memory(base, first.base_vertices))
        self.assertFalse(np.shares_memory(inflated, first.inflated_vertices))
        with self.assertRaises(FrozenInstanceError):
            first.faces = faces

    def test_invalid_vertex_and_attribute_arrays(self):
        cases = [(self.base[:, :2], self.base), (self.base, self.base[:2]),
                 (np.full_like(self.base, np.nan), self.base), (self.base, np.full_like(self.base, np.inf))]
        for base, inflated in cases:
            with self.subTest(shape=base.shape), self.assertRaises(ValueError):
                clip_domain(base, inflated, self.faces, plane())

    def test_invalid_face_indices_labels_and_crossing_polygon(self):
        cases = [([(0, 1, 4)], None), ([(0, -1, 2)], None), ([(0., 1., 2.)], None),
                 ([(0, 1, 2, 1)], None), ([(0, 2, 1, 3)], None), (self.faces, ['one'])]
        for faces, labels in cases:
            with self.subTest(faces=faces), self.assertRaises(ValueError):
                clip_domain(self.base, self.base, faces, plane(-2), labels)

    def test_invalid_plane_and_tolerance(self):
        bad_planes = [plane(normal=(0, 0, 0)), plane(np.nan), plane(normal=(1, 2)),
                      plane(normal=(np.inf, 0, 0)), plane(keep_positive='yes')]
        for value in bad_planes:
            with self.subTest(plane=value), self.assertRaises(ValueError):
                clip_domain(self.base, self.base, self.faces, value)
        for tolerance in (-1., np.nan, np.inf):
            with self.subTest(tolerance=tolerance), self.assertRaises(ValueError):
                clip_domain(self.base, self.base, self.faces, plane(), tolerance=tolerance)


if __name__ == '__main__':
    unittest.main()
