import unittest
from dataclasses import replace
import numpy as np
from pair_fixtures import rectangle
from stack_fixture_adapter import payload, solve
from core.muscle_pairs.model import DetectionSettings
from core.muscle_stacking.model import StackingSettings


def inflated(key, base, outer, bounds=(-1, 1, -1, 1), n=3):
    side = rectangle(key, bounds, base, n=n)
    own = side.own.copy(); own[:, 2] = outer
    return payload(replace(side, own=own))


class Stacking(unittest.TestCase):
    def test_support(self):
        result, out = solve([inflated('under', 0, .3), inflated('cover', .1, .2)])
        self.assertEqual(result['pairs'][0]['order']['status'], 'supported')
        self.assertEqual(result['stacking']['status'], 'complete')
        np.testing.assert_allclose(out['cover'][:, 2], .5, atol=2e-6)

    def test_joint_envelope_and_ancestry(self):
        values = [inflated('a', 0, .3), inflated('b', .1, .4), inflated('c', .2, .25)]
        result, out = solve(values)
        self.assertEqual(result['stacking']['status'], 'complete')
        # Own + provider's full displacement; simultaneous ancestors are not summed.
        np.testing.assert_allclose(out['b'][:, 2], .7, atol=2e-6)
        np.testing.assert_allclose(out['c'][:, 2], .85, atol=2e-6)

    def test_off_is_intrinsic(self):
        config = DetectionSettings(stacking=StackingSettings(enabled=False))
        result, out = solve([inflated('a', 0, .3), inflated('b', .1, .2)], config)
        np.testing.assert_array_equal(out['b'][:, 2], .2)

    def test_fixed_conflict(self):
        a, b = inflated('a', 0, .3), inflated('b', .1, .2)
        b = replace(b, material=replace(b.material, fixed=np.array([0], dtype=np.int64)))
        result, out = solve([a, b])
        self.assertEqual(result['stacking']['status'], 'incomplete')
        np.testing.assert_array_equal(out['b'], b.own)

    def test_pair_search_allowance_does_not_cap_displacement(self):
        result, out = solve([inflated('a', 0, .9), inflated('b', .1, .2)])
        self.assertEqual(result['stacking']['status'], 'complete')
        np.testing.assert_allclose(out['b'][:, 2], 1.1, atol=2e-6)

    def test_coincident(self):
        result, _ = solve([inflated('a', 0, .2), inflated('b', 0, .3)])
        self.assertEqual(result['pairs'][0]['order']['status'], 'coincident_bases')
        self.assertEqual(result['stacking']['status'], 'incomplete')

    def test_edge_aligned_crossing(self):
        a, b = inflated('a', 0, .1), inflated('b', 0, .1)
        base = b.base.copy(); base[:, 2] = base[:, 0]*.1
        b = replace(b, base=base, own=base+np.array([0, 0, .1]))
        result, _ = solve([a, b])
        self.assertEqual(result['pairs'][0]['order']['status'], 'intersecting_bases')

    def test_small_interior_footprint(self):
        a, b = inflated('a', 0, .3, (-.02, .02, -.02, .02)), inflated('b', .1, .2)
        result, out = solve([a, b])
        self.assertEqual(result['pairs'][0]['order']['status'], 'supported')
        self.assertGreater(out['b'][4, 2], .399)


if __name__ == '__main__': unittest.main()
