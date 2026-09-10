"""Region membership follows indexed vertices through deformation and face reordering."""
import unittest
from copy import deepcopy
import numpy as np
from core.authoring import indexed_patches, surface_patch, substrate, visual_selection
from core.authoring.model import Budget
from core.authoring.errors import AuthoringError
from test_authoring_visual import geometry


def selected(data, query):
    chart = substrate.box_frame(dict(axes=np.eye(3)), dict(instance_id='cube'), data)
    rows, _ = surface_patch.partition(list(substrate.surface(chart)), query, chart, Budget())
    return np.concatenate([substrate.world(chart, row) for row in rows])


class IndexedRegionTests(unittest.TestCase):
    def test_partial_boundary_follows_deformed_vertices(self):
        data = geometry()
        rows = [dict(triangle=0, polygon=[[1, 0, 0], [.5, .5, 0], [.5, 0, .5]])]
        query = indexed_patches.bind(data, rows)
        before = deepcopy(query)
        matrix = np.array([[2, .2, 0], [0, .7, .3], [0, 0, 1.4]])
        expected = selected(data, query) @ matrix.T + [3, 2, 1]
        data['vertices'] = (np.asarray(data['vertices']) @ matrix.T + [3, 2, 1]).tolist()
        np.testing.assert_allclose(sorted(map(tuple, selected(data, query))), sorted(map(tuple, expected)), atol=1e-8)
        self.assertEqual(query, before)
        self.assertNotIn('triangle', query['patches'][0])
        self.assertEqual(query['patches'][0]['tri_vidx'], [0, 1, 3])

    def test_reordered_and_rotated_faces_keep_boundary(self):
        data = geometry()
        query = indexed_patches.bind(data, [dict(triangle=0, polygon=np.eye(3).tolist())])
        expected = selected(data, query)
        data['triangles'] = [face[1:]+face[:1] for face in data['triangles'][::-1]]
        np.testing.assert_allclose(sorted(map(tuple, selected(data, query))), sorted(map(tuple, expected)), atol=1e-8)

    def test_changed_connectivity_requires_rebinding(self):
        data = geometry()
        query = indexed_patches.bind(data, [dict(triangle=0, polygon=np.eye(3).tolist())])
        data['triangles'][0] = [0, 1, 4]
        with self.assertRaises(AuthoringError) as raised:
            selected(data, query)
        self.assertEqual(raised.exception.code, 'SURFACE_PATCH_REBIND_REQUIRED')

    def test_polygon_diagonal_change_stays_on_current_surface(self):
        data = quad()
        query = indexed_patches.bind(data, [dict(triangle=0, polygon=np.eye(3).tolist())])
        data['triangles'] = [[0, 1, 3], [1, 2, 3]]
        data['vertices'][2][2] = 1
        rows = indexed_patches.resolve(data, query)
        polygons = visual_selection.world_polygons(data, rows)
        self.assertEqual(len(polygons), 2)
        points = np.concatenate(polygons)
        self.assertTrue(any(np.allclose(p, [.5, .5, 0]) for p in points))
        self.assertFalse(any(np.allclose(p, [.5, .5, .5]) for p in points))
        self.assertEqual(query['patches'][0]['face_vidx'], [0, 1, 2, 3])

    def test_retriangulation_preserves_partial_mask_area(self):
        data = quad()
        rows = [dict(triangle=0, polygon=[[.5, .5, 0], [0, 1, 0], [0, 0, 1]])]
        query = indexed_patches.bind(data, rows)
        expected = visual_selection.area(data, rows)
        data['triangles'] = [[0, 1, 3], [1, 2, 3]]
        actual = visual_selection.area(data, indexed_patches.resolve(data, query))
        self.assertAlmostEqual(actual, expected)


def quad():
    return dict(vertices=[[0., 0., 0.], [1., 0., 0.], [1., 1., 0.], [0., 1., 0.]],
                triangles=[[0, 1, 2], [0, 2, 3]], polygons=[[0, 1, 2, 3]], triangle_polygons=[0, 0], matrix=np.eye(4))
