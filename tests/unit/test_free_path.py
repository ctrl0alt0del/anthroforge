import unittest
from types import SimpleNamespace
import numpy as np
from core.vcp import free_path as path


def fixture(topology='OPEN'):
    points = [(0, 0, 0), (.5, .2, 0), (1, 0, 0)]
    return path.make(points, topology, [('a', 'START'), ('b', 'END')], [0, 2])


class FreePathTests(unittest.TestCase):
    def test_codec_exact_and_count_independent(self):
        value = fixture(); raw = path.encode(value)
        fiber = SimpleNamespace(behavior_mode='FREE', free_path_json=raw, node_count=64)
        self.assertEqual(path.decode(raw), value)
        self.assertEqual(path.fiber_geometry_point_count(fiber), 3)
        fiber.behavior_mode = 'CONTROLLED'
        self.assertEqual(path.fiber_geometry_point_count(fiber), 64)

    def test_malformed_and_degenerate_reject(self):
        for points in ([(0, 0, 0)] * 3, [(0, 0, 0), (1, float('nan'), 0)], [(0, 0)] * 3):
            with self.assertRaises(ValueError): path.coordinates(points)
        with self.assertRaises(ValueError): path.decode('{}')

    def test_exact_structural_mapping_and_order(self):
        value = fixture()
        self.assertEqual(path.point_indices(value, ['b', 'a']), (2, 0))
        value['structural'].reverse()
        with self.assertRaises(ValueError): path.validate(value)

    def test_ambiguous_junction_rejects(self):
        value = fixture(); value['structural'][1]['point_id'] = 'a'
        with self.assertRaises(ValueError): path.point_indices(value, ['a'])

    def test_local_anchor_adjustment_preserves_other_spans(self):
        points = np.array([(0, 0, 0), (.25, .1, 0), (.5, 0, 0), (.75, .1, 0), (1, 0, 0)])
        result = path.adjust_anchors(points, [0, 2, 4], [(0, 1, 0), (.5, 0, 0), (1, 0, 0)])
        np.testing.assert_array_equal(result[2:], points[2:])
        np.testing.assert_allclose(result[1] - points[1], (0, .5, 0))

    def test_loop_wrap_and_rebase(self):
        points = np.array([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], dtype=float)
        moved = path.adjust_anchors(points, [0, 2], [(0, 0, .2), (1, 1, 0)], True)
        self.assertGreater(moved[-1, 2], 0)
        draft = points[:3].copy(); draft[1, 2] = .3
        rebased = path.rebase_span(points[:3], draft, points[:3] + (0, 0, 1))
        np.testing.assert_allclose(rebased[:, 2], (1, 1.3, 1))

    def test_duplicate_remaps_sample_occurrence_and_point_ids(self):
        value = fixture(); result = path.decode(path.remap(path.encode(value), {'a': 'c', 'b': 'd'}))
        self.assertEqual([row['point_id'] for row in result['structural']], ['c', 'd'])
        self.assertNotEqual(value['samples'][0]['sample_id'], result['samples'][0]['sample_id'])
        self.assertNotEqual(value['structural'][0]['occurrence_id'], result['structural'][0]['occurrence_id'])

    def test_budget_and_solver_guard(self):
        with self.assertRaises(ValueError): path.coordinates(np.zeros((4097, 3)))
        with self.assertRaisesRegex(ValueError, 'FREE_SOLVER_FORBIDDEN'):
            path.require_controlled(SimpleNamespace(behavior_mode='FREE'))
        path.require_controlled(SimpleNamespace())
