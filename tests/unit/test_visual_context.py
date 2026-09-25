"""Automatic context, transformed measurements and stable visible identities."""
import unittest
import numpy as np
from core.authoring import visual_context as context, visual_labels as labels
from test_authoring_visual import geometry


def inventory():
    source, near, far = geometry(), geometry(), geometry()
    near['matrix'][0][3], far['matrix'][0][3] = 2.25, 20
    return dict(geometry=dict(source=source, near=near, far=far))


class ContextTests(unittest.TestCase):
    def test_default_includes_near_but_not_far(self):
        keys, report = context.context(inventory(), 'source', {})
        self.assertEqual(keys, ['near'])
        self.assertAlmostEqual(report['candidates'][0]['aabb_gap'], .25)
        self.assertIn('not proof', report['method'])

    def test_explicit_isolation_and_combined_context(self):
        self.assertEqual(context.context(inventory(), 'source', dict(context_ids=[]))[0], [])
        options = dict(context_ids=['far'], automatic_context=True)
        self.assertEqual(context.context(inventory(), 'source', options)[0], ['far', 'near'])

    def test_transform_aware_area_extents_and_neighborhood(self):
        value = inventory()
        value['geometry']['source']['matrix'][0][0] = 2
        self.assertEqual(context.context(value, 'source', dict(neighbor_distance=0))[0], ['near'])
        measures = context.measurements(value['geometry']['source'])
        np.testing.assert_allclose(measures['world_extents'], [4, 2, 2])
        self.assertAlmostEqual(measures['surface_area'], 40)
        np.testing.assert_allclose(measures['surface_centroid'], [0, 0, 0])

    def test_labels_are_distinct_stable_and_visible(self):
        first, second = labels.identity('source', 'O'), labels.identity('near', 'O')
        self.assertNotEqual(first, second)
        pixels = np.zeros((64, 64, 3), dtype=np.uint8)
        labels.stamp(pixels, first, 63, 63)
        self.assertGreater(np.count_nonzero(pixels), 0)
        self.assertEqual(first, labels.identity('source', 'O'))

    def test_packet_links_labels_to_geometry_and_revision(self):
        data = inventory(); data['instances'] = []
        scene = dict(owner='source', scene_revision='revision', geometry=data['geometry'])
        report = context.packet(scene, {}, data)
        self.assertEqual(report['scene_revision'], 'revision')
        self.assertEqual(len(report['objects']), 3)
        self.assertEqual(report['objects'][0]['label'], labels.identity('source', 'O'))

    def test_clustered_labels_have_nonoverlapping_boxes(self):
        pixels = np.zeros((256, 256, 3), dtype=np.uint8)
        occupied = []
        for index in range(8):
            labels.place(pixels, labels.identity(str(index), 'O'), (128, 128), occupied)
        self.assertEqual(len(occupied), 8)
        for index, (x, y, w, h) in enumerate(occupied):
            for a, b, width, height in occupied[index+1:]:
                self.assertFalse(x < a+width and x+w > a and y < b+height and y+h > b)
