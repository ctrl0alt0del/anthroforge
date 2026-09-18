"""Semantic clefts, shared seams and geometric holes are different constraints."""
import copy
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import numpy as np
from core.authoring.base_structure import prepare
from core.authoring.errors import AuthoringError
from core.authoring.geometry import surface_distance
from tests.unit._base_structure_fixture import example


class BaseStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.definition = example(); cls.result = prepare(cls.definition)

    def test_two_heads_form_one_hole_free_surface(self):
        self.assertEqual(self.result['status'], 'geometry_candidate')
        self.assertEqual(len(self.result['heads']), 2); self.assertEqual(len(self.result['patches']), 3)
        self.assertEqual(len(self.result['connections']), 2)
        self.assertEqual(self.result['topology']['euler'], 1)
        self.assertEqual(self.result['topology']['nonmanifold_edges'], 0)
        self.assertEqual(self.result['topology']['pinched_boundary_vertices'], 0)

    def test_missing_samples_are_filled_but_head_cleft_stays_empty(self):
        triangles = self.result['vertices'][self.result['triangles']]
        self.assertLess(surface_distance(triangles, np.array([0., 1., 0.])), 1e-9)
        self.assertGreater(surface_distance(triangles, np.array([0., 3.5, 0.])), .2)
        self.assertEqual(self.result['patches'][0]['head_ids'], ['left', 'right'])

    def test_shared_boundaries_are_welded_by_identity(self):
        patches = self.result['patches']; original = sum(len(p['vertices']) for p in patches)
        self.assertEqual(original-len(self.result['vertices']), 22)
        for patch in patches:
            self.assertLess(patch['quality']['orientation']['opposed_area_fraction'], 1e-12)
            self.assertEqual(patch['quality']['orientation']['near_zero_triangles'], 0)

    def test_unknown_heads_and_invalid_shared_boundaries_fail(self):
        wrong = copy.deepcopy(self.definition); wrong['patches'][0]['head_ids'] = ['invented']
        with self.assertRaises(AuthoringError): prepare(wrong)
        wrong = copy.deepcopy(self.definition); wrong['arcs'][2]['role'] = 'cleft'
        with self.assertRaises(AuthoringError): prepare(wrong)
        wrong = copy.deepcopy(self.definition); wrong['patches'][1]['boundary'][0]['reverse'] = False
        with self.assertRaises(AuthoringError): prepare(wrong)


if __name__ == '__main__':
    unittest.main()
