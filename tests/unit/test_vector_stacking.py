"""Vector transport, exact equations and neighborhood regressions."""
import unittest
from dataclasses import replace
import numpy as np
from core.muscle_stacking.constraints import MaterialConstraint
from core.muscle_stacking.model import StackingSettings
from core.muscle_pairs.model import DetectionSettings
from core.muscle_stacking.native import NativeStackEngine
from pair_fixture_adapter import wait
from stack_fixture_adapter import solve
from test_muscle_stacking import inflated
from test_explicit_stacking import config


def vector_settings(**kwargs):
    return DetectionSettings(stacking=StackingSettings(**kwargs))


class VectorStacking(unittest.TestCase):
    def test_provider_tangential_displacement_is_preserved(self):
        a = inflated('a', 0, .3, (-2, 2, -2, 2))
        a = replace(a, own=a.own+(.2, 0, 0), direction=np.tile((2/np.sqrt(13), 0, 3/np.sqrt(13)), (len(a.base), 1)))
        b = inflated('b', .1, .2)
        report, out = solve([a, b], vector_settings(strength=0))
        self.assertEqual(report['stacking']['status'], 'complete', report['stacking'])
        np.testing.assert_allclose(out['b'], b.own+(.2, 0, .3), atol=2e-7)

    def test_below_base_correction_follows_provider_vector(self):
        a = inflated('a', 0, .3, (-2, 2, -2, 2))
        a = replace(a, own=a.own+(.2, 0, 0), direction=np.tile((2/np.sqrt(13), 0, 3/np.sqrt(13)), (len(a.base), 1)))
        b = inflated('b', -.15, .1); setup = config()
        setup = replace(setup, stacking=replace(setup.stacking, strength=0))
        report, out = solve([a, b], setup)
        self.assertEqual(report['stacking']['status'], 'complete', report['stacking'])
        np.testing.assert_allclose(out['b'], b.own+(.3, 0, .45), atol=2e-7)

    def test_weighted_attachment_does_not_fix_contributing_vertices(self):
        a = inflated('a', 0, .2, (-1.4, -.6, -1.4, -.6))
        b = inflated('b', .1, .5); row = MaterialConstraint('midpoint', (0, 2), (.5, .5))
        b = replace(b, material=replace(b.material, constraints=(row,)))
        report, out = solve([a, b], vector_settings(radius=.2, blend_distance=5))
        self.assertEqual(report['stacking']['status'], 'complete', report['stacking'])
        delta = out['b']-b.own
        np.testing.assert_allclose((delta[0]+delta[2])*.5, 0, atol=2e-7)
        self.assertGreater(delta[0, 2], .01); self.assertLess(delta[2, 2], -.01)

    def test_provider_permutation_and_stable_tie(self):
        a = inflated('a', 0, .3, (-2, 2, -2, 2)); b = inflated('b', 0, .3, (-2, 2, -2, 2))
        a = replace(a, group='siblings', own=a.own+(.05, 0, 0))
        b = replace(b, group='siblings', own=b.own+(-.05, 0, 0)); c = inflated('c', .1, .2)
        _, first = solve([a, b, c], vector_settings(strength=0))
        _, second = solve([c, b, a], vector_settings(strength=0))
        np.testing.assert_allclose(first['c'], second['c'], atol=2e-7)
        self.assertGreater(np.max(np.abs(first['c'][:, 0]-c.own[:, 0])), .04)

    def test_smoothing_settings_reuse_correspondence_not_solve(self):
        values = [inflated('a', 0, .3), inflated('b', .1, .2)]
        with NativeStackEngine() as engine:
            engine.submit(values, vector_settings(), 1); wait(engine)
            engine.submit(values, vector_settings(radius=.25), 2); result = wait(engine)
            row = next(d for d in result['stacking']['domains'] if d['domain']['muscle'] == 'b')
            self.assertEqual(row['vector']['correspondence_ms'], 0)
            self.assertEqual(row['vector']['solve_cache_reused'], 0)
            self.assertGreater(row['vector']['piqp_ms'], 0)

    def test_missing_new_native_interface_is_explicit(self):
        from core.muscle_stacking.vector import bind
        with self.assertRaisesRegex(RuntimeError, 'STACK_VECTOR_NATIVE_UNAVAILABLE'):
            bind(object())

    def test_new_neighbor_beyond_search_allowance_blocks_publication(self):
        a = inflated('a', 0, .3, (-4, 4, -4, 4)); b = inflated('b', .1, .2)
        a = replace(a, group='peers', own=a.own+(2., 0, 0), direction=np.tile((2., 0, .3)/np.linalg.norm((2., 0, .3)), (len(a.base), 1)))
        c = inflated('c', 0, 0, (-.5, .5, .4, .8))
        base = np.column_stack((np.full(len(c.base), 2.), c.base[:, :2]))
        c = replace(c, group='peers', base=base, own=base, direction=np.tile((1., 0, 0), (len(base), 1)), material=replace(c.material, vertices=base))
        report, out = solve([a, b, c], replace(vector_settings(strength=0), displacement=0, search_distance=.01))
        self.assertEqual(report['stacking']['status'], 'incomplete', report)
        self.assertIn('STACK_UNRESOLVED_NEW_NEIGHBOR_CONTACT', str(report['stacking']))
        np.testing.assert_array_equal(out['b'], b.own); np.testing.assert_array_equal(out['c'], c.own)

    def test_crop_keeps_unobserved_attachment_variables(self):
        a = inflated('a', 0, .2, (-2, 2, -2, 2)); original = inflated('b', .1, .4, n=2)
        row = MaterialConstraint('crosses_crop', (0, 3), (.5, .5))
        m = replace(original.material, interpolation=original.material.interpolation[:3], weights=np.ones((3, 1)), constraints=(row,))
        b = replace(original, base=original.base[:3], own=original.own[:3], direction=original.direction[:3],
                    faces=np.array([[0, 1, 2]], dtype=np.int64), parts=np.array([0]), sources=np.array([0]), material=m)
        report, out = solve([a, b], vector_settings(strength=0))
        self.assertEqual(report['stacking']['status'], 'complete', report['stacking'])
        np.testing.assert_allclose(out['b'], b.own+(0, 0, .2), atol=2e-7)
        record = next(d for d in report['stacking']['domains'] if d['domain']['muscle'] == 'b')
        self.assertLessEqual(record['vector']['attachment_error'], 2e-7)


if __name__ == '__main__': unittest.main()
