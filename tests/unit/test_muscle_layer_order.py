"""The 28 frozen base-ray cases promoted from the reviewed experiment."""
import unittest
from dataclasses import replace
import numpy as np
from layer_order_cases import cases
from core.muscle_pairs.model import DetectionSettings
from core.muscle_stacking.model import StackingSettings, material
from stack_fixture_adapter import solve
from core.muscle_stacking.native import NativeStackEngine
from pair_fixture_adapter import wait


def owned(domain):
    indices = np.arange(len(domain.base))[:, None]
    return replace(domain, material=material(domain.base, domain.faces, indices, np.ones(indices.shape)))


def evaluate(values, exhaustive=False):
    points = np.concatenate([d.base for d in values]); extent = np.linalg.norm(points.max(0)-points.min(0))+1e-6
    with NativeStackEngine() as engine:
        engine.submit([owned(d) for d in values], DetectionSettings(search_distance=extent, stacking=StackingSettings(enabled=False)), 1)
        wait(engine)
        return engine.resolve_pair(values[0].key, values[1].key, exhaustive)


class Ordering(unittest.TestCase):
    def test_frozen_28_and_reversed(self):
        aliases = dict(conflicting_local_order='conflicting_directions_or_local_order', projection_failure='projection_requires_review')
        fixtures = cases(); self.assertEqual(len(fixtures), 28)
        for case in fixtures:
            with self.subTest(case=case['name']):
                for values in (case['domains'], case['domains'][::-1]):
                    result = evaluate(values); status = aliases.get(result['status'], result['status'])
                    self.assertIn(status, case['allowed'])
                    if status == 'supported': self.assertEqual(result['underlying']['muscle'], case['domains'][case['underlying']].key.muscle)

    def test_inflation_invariance(self):
        for case in cases():
            with self.subTest(case=case['name']):
                original = evaluate(case['domains'])
                changed = evaluate([replace(d, own=d.base+d.direction*3) for d in case['domains']])
                self.assertEqual(original['status'], changed['status'])
                self.assertEqual(original.get('underlying'), changed.get('underlying'))

    def test_exhaustive_parity(self):
        for case in cases():
            with self.subTest(case=case['name']):
                a, b = evaluate(case['domains']), evaluate(case['domains'], True)
                self.assertEqual(a['status'], b['status'])
                np.testing.assert_allclose(a['positive_fragment_area'], b['positive_fragment_area'], atol=1e-10)


if __name__ == '__main__': unittest.main()
