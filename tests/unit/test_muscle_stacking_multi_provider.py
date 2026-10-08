"""Production regressions for joint support, retained thickness and strict rejection."""
from dataclasses import replace
import unittest
import numpy as np
from pair_fixture_adapter import PairDetector, Side, wait
from stack_fixture_adapter import solve
from stack_multi_fixtures import providers, chain, settings, duplicate, deepen, fixed_conflict, exclude
from core.muscle_stacking.native import NativeStackEngine
from test_muscle_stacking import inflated


def carrier_clearance(provider, cover, surfaces):
    carrier = surfaces[cover.key.muscle] - (cover.own-cover.base)
    final = surfaces[provider.key.muscle]
    with PairDetector(2.) as detector:
        detector.add(Side('cover', 'c', carrier, carrier, cover.direction, cover.faces))
        detector.add(Side('provider', 'p', final, final, provider.direction, provider.faces))
        evidence = detector.detect()['fragments']
    gaps = [f['gap_max'] for f in evidence if f['receiver_id'] == 'cover']
    assert gaps, 'Missing independently mapped triangle-interior support'
    return -max(gaps)


class MultiProvider(unittest.TestCase):
    def check_support(self, values, config):
        copies = [(d.base.copy(), d.own.copy()) for d in values]
        report, surfaces = solve(values, config); lookup = {d.key.muscle: d for d in values}
        self.assertEqual(report['stacking']['status'], 'complete', report['stacking'])
        for pair in report['pairs']:
            order = pair['order']
            if order['status'] != 'supported': continue
            a, b = (lookup[order[k]['muscle']] for k in ('underlying', 'covering'))
            self.assertGreaterEqual(carrier_clearance(a, b, surfaces), config.stacking.clearance-2e-6)
        for d, (base, own) in zip(values, copies):
            np.testing.assert_array_equal(d.base, base); np.testing.assert_array_equal(d.own, own)
            np.testing.assert_allclose(surfaces[d.key.muscle][d.material.fixed], d.own[d.material.fixed], atol=2e-7)
        return surfaces

    def test_overlapping_and_disjoint_smooth_providers(self):
        for disjoint in (False, True):
            for clearance in (0., .015):
                with self.subTest(disjoint=disjoint, clearance=clearance):
                    self.check_support(providers(disjoint), settings(clearance))

    def test_chain_preserves_each_intrinsic_thickness(self):
        self.check_support(chain(), settings())
        values = [inflated('lower', 0, .38), inflated('middle', .07, .17), inflated('top', .14, .22)]
        surfaces = self.check_support(values, settings())
        for name, peak in [('lower', .38), ('middle', .55), ('top', .70)]:
            np.testing.assert_allclose(surfaces[name][:, 2].max(), peak, atol=2e-6)

    def test_joint_envelope_is_maximum_not_sum(self):
        values = providers(); flat = []
        for d, height in zip(values, (.4, .44, .055)):
            flat.append(replace(d, own=d.base+[0, 0, height], material=replace(d.material, fixed=np.array([], dtype='int64'))))
        surfaces = self.check_support(flat, settings(strength=0))
        np.testing.assert_allclose(surfaces['cover'][len(flat[-1].base)//2, 2], .595, atol=2e-6)

    def test_duplicate_and_redundant_ancestor(self):
        values = providers(); _, baseline = solve(values, settings())
        _, duplicated = solve(duplicate(values), settings())
        np.testing.assert_allclose(duplicated['cover'], baseline['cover'], atol=2e-6)
        values = chain(); _, baseline = solve(values, settings())
        _, reduced = solve(values, settings(exclusions=(exclude(values[0], values[2]),)))
        np.testing.assert_allclose(reduced['top'], baseline['top'], atol=2e-6)

    def test_provider_updates_match_fresh_evaluation(self):
        values = providers()
        with NativeStackEngine() as engine:
            for generation, current in enumerate((values, deepen(values), values[1:]), 1):
                engine.submit(current, settings(), generation); report = wait(engine)
                self.assertEqual(report['stacking']['status'], 'complete')
                _, fresh = solve(current, settings())
                for key, points in engine.surfaces().items():
                    np.testing.assert_array_equal(points, fresh[key.muscle])

    def test_fixed_conflict_and_search_allowance(self):
        values = fixed_conflict(providers()); report, surfaces = solve(values, settings())
        self.assertEqual(report['stacking']['status'], 'incomplete')
        np.testing.assert_array_equal(surfaces['cover'], values[-1].own)
        self.check_support(providers(), replace(settings(), displacement=.05))

    def test_resolution_strength_and_zero_intrinsic_height(self):
        self.check_support(providers(n=27), settings(radius=.4))
        values = providers(); values[-1] = replace(values[-1], own=values[-1].base.copy())
        self.check_support(values, settings())

    def test_rotated_material_frame(self):
        values = providers(n=13); _, original = solve(values, settings())
        angle = .65; c, s = np.cos(angle), np.sin(angle)
        rotation = np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
        rotated = [replace(d, base=d.base@rotation.T, own=d.own@rotation.T, direction=d.direction@rotation.T,
                   material=replace(d.material, vertices=d.material.vertices@rotation.T)) for d in values]
        surfaces = self.check_support(rotated, settings())
        for name, points in surfaces.items(): np.testing.assert_allclose(points, original[name]@rotation.T, atol=2e-6)
