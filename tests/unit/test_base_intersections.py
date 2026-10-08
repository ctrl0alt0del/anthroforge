"""Actual native triangle tests, including cases the stacking candidate scan excludes."""
import unittest
import numpy as np
from core.authoring.base_intersections import scan


def triangle(name, vertices):
    return dict(identity=dict(muscle_id=name), vertices=np.array(vertices, float), triangles=np.array([[0, 1, 2]], np.int64))


def sheet(name='a'):
    return triangle(name, [[-2, -2, 0], [2, -2, 0], [0, 2, 0]])


def crossing(name='b'):
    return triangle(name, [[0, -.5, -1], [0, -.5, 1], [0, 1, 0]])


class BaseIntersectionTests(unittest.TestCase):
    def test_crossing_through_triangle_interiors(self):
        report = scan([sheet(), crossing()]); pair = report['pairs'][0]
        self.assertTrue(pair['intersection']); self.assertEqual(pair['triangle_pair_counts']['crossing'], 1)
        points = np.array(pair['witnesses'][0]['segment'])
        np.testing.assert_allclose(points[:, [0, 2]], 0, atol=1e-9)
        self.assertEqual(report['tested_surface_pairs'], 1)

    def test_separated_overlapping_bounds_do_not_report_collision(self):
        a = triangle('a', [[0, 0, 0], [2, 0, 0], [0, 2, 0]])
        b = triangle('b', [[2, 2, 0], [2, 1.1, 0], [1.1, 2, 0]])
        report = scan([a, b]); self.assertEqual(report['broad_phase_pairs'], 1)
        self.assertEqual(report['pairs'], [])

    def test_coplanar_containment_and_opposite_winding(self):
        b = triangle('b', [[-.1, -.1, 0], [0, .1, 0], [.1, -.1, 0]])
        pair = scan([sheet(), b])['pairs'][0]
        self.assertEqual(pair['triangle_pair_counts']['coplanar_overlap'], 1)
        self.assertAlmostEqual(pair['coplanar_area'], .02)

    def test_coplanar_edge_and_point_are_contacts(self):
        a = triangle('a', [[0, 0, 0], [1, 0, 0], [0, 1, 0]])
        for p in ([[1, 0, 0], [1, 1, 0], [0, 1, 0]], [[1, 0, 0], [2, 0, 0], [1, -1, 0]]):
            pair = scan([a, triangle('b', p)])['pairs'][0]
            self.assertFalse(pair['intersection']); self.assertEqual(pair['triangle_pair_counts']['contact'], 1)

    def test_coplanar_edges_cross_without_contained_vertices(self):
        a = triangle('a', [[0, 2, 0], [-2, -1, 0], [2, -1, 0]])
        b = triangle('b', [[0, -2, 0], [-2, 1, 0], [2, 1, 0]])
        pair = scan([a, b])['pairs'][0]
        self.assertEqual(pair['triangle_pair_counts']['coplanar_overlap'], 1)
        self.assertAlmostEqual(pair['coplanar_area'], 4.)

    def test_folded_shared_boundary_is_contact(self):
        a = triangle('a', [[0, 0, 0], [1, 0, 0], [0, 1, 0]])
        b = triangle('b', [[0, 0, 0], [1, 0, 0], [0, 0, 1]])
        self.assertFalse(scan([a, b])['pairs'][0]['intersection'])

    def test_mirror_and_same_family_not_filtered(self):
        a, b = sheet('same'), crossing('same')
        a['identity']['instance'], b['identity']['instance'] = 'source', 'mirror'
        self.assertTrue(scan([a, b])['pairs'][0]['intersection'])

    def test_witness_limit_does_not_truncate_pairs_or_counts(self):
        a, b, c = sheet(), crossing(), crossing('c'); b['triangles'] = np.tile(b['triangles'], (20, 1))
        report = scan([a, b, c], witness_limit=1)
        self.assertEqual(len(report['pairs']), 3)
        pair = report['pairs'][0]; self.assertEqual(pair['triangle_pair_counts']['crossing'], 20)
        self.assertEqual(len(pair['witnesses']), 1); self.assertTrue(pair['witnesses_truncated'])

    def test_degenerate_triangles_are_reported(self):
        report = scan([sheet(), triangle('b', [[0, 0, 0], [0, 0, 0], [1, 0, 0]])])
        self.assertEqual(report['issues'][0]['code'], 'BASE_DEGENERATE_TRIANGLES')
        self.assertEqual(report['pairs'], [])

    def test_translation_rotation_and_scale(self):
        a, b = sheet(), crossing()
        rotation = np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0]])
        for scale in (.001, 1., 1000.):
            meshes = [dict(m, vertices=m['vertices']@rotation*scale+1e5) for m in (a, b)]
            self.assertEqual(scan(meshes)['pairs'][0]['triangle_pair_counts']['crossing'], 1)

    def test_empty_single_and_invalid_inputs(self):
        self.assertEqual(scan([])['pairs'], []); self.assertEqual(scan([sheet()])['pairs'], [])
        for kwargs in (dict(tolerance=float('nan')), dict(tolerance=0), dict(witness_limit=-1)):
            with self.assertRaises(ValueError): scan([sheet()], **kwargs)
        bad = sheet(); bad['triangles'][0, 0] = 30
        with self.assertRaises(ValueError): scan([bad])

    def test_vertex_order_and_input_order(self):
        a, b = sheet(), crossing(); expected = scan([a, b])['pairs'][0]['triangle_pair_counts']
        for order in ([0, 2, 1], [2, 0, 1], [1, 2, 0]):
            b['triangles'] = np.array([order]); self.assertEqual(scan([b, a])['pairs'][0]['triangle_pair_counts'], expected)

    def test_positive_gap_and_disabled_witnesses(self):
        a, b = sheet(), sheet('b'); b['vertices'][:, 2] += 1e-5
        self.assertEqual(scan([a, b], tolerance=1e-7)['pairs'], [])
        pair = scan([sheet(), crossing()], witness_limit=0)['pairs'][0]
        self.assertEqual(pair['witnesses'], []); self.assertTrue(pair['intersection'])
