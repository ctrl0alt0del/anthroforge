"""Explicit order permits crossing bases without weakening support certification."""
import unittest
from dataclasses import replace
import numpy as np
from core.muscle_relationships.policy import RelationshipPolicy
from core.muscle_stacking.native import NativeStackEngine
from test_muscle_stacking import inflated
from stack_multi_fixtures import settings
from pair_fixture_adapter import wait


def crossing():
    a, b = inflated('a', 0, .2, n=7), inflated('b', 0, .1, n=7)
    base = b.base.copy(); base[:, 2] = base[:, 0]*.1
    b = replace(b, base=base, own=base+np.array([0, 0, .1]), material=replace(b.material, vertices=base))
    return [a, b]


def config(mode='explicit'):
    pair = (('a', 'source', 'A'), ('b', 'source', 'A'))
    return replace(settings(), relationships=(RelationshipPolicy(pair, pair[1], mode=mode),))


class ExplicitStacking(unittest.TestCase):
    def test_opposing_directions_are_not_hidden_by_crossings(self):
        values = crossing(); values[1] = replace(values[1], direction=-values[1].direction)
        with NativeStackEngine() as engine:
            engine.submit(values, config(), 1); result = wait(engine)
            self.assertEqual(result['pairs'][0]['order']['status'], 'intersecting_bases')
            self.assertEqual(result['pairs'][0]['effective_order']['status'], 'incompatible_directions')
            self.assertEqual(result['stacking']['status'], 'incomplete')

    def test_explicit_assignment_without_projection_is_inactive(self):
        values = crossing(); b = values[1]; shift = np.array([10, 0, 0])
        values[1] = replace(b, base=b.base+shift, own=b.own+shift, material=replace(b.material, vertices=b.material.vertices+shift))
        with NativeStackEngine() as engine:
            engine.submit(values, config(), 1); result = wait(engine)
            self.assertEqual(result['pairs'][0]['effective_order']['status'], 'no_upward_evidence')
            self.assertEqual(result['stacking']['status'], 'complete')

    def test_crossing_preserves_raw_evidence_and_separates(self):
        with NativeStackEngine() as engine:
            setup = config(); setup = replace(setup, stacking=replace(setup.stacking, strength=0))
            engine.submit(crossing(), setup, 1); result = wait(engine)
            self.assertEqual(result['pairs'][0]['order']['status'], 'intersecting_bases')
            self.assertEqual(result['pairs'][0]['effective_order']['status'], 'supported')
            self.assertEqual(result['stacking']['status'], 'complete')
            output = {k.muscle: v for k, v in engine.surfaces().items()}
            expected = .3 + np.maximum(0, crossing()[1].base[:, 2])
            np.testing.assert_allclose(output['b'][:, 2], expected, atol=2e-6)

    def test_request_does_not_authorize_crossing(self):
        with NativeStackEngine() as engine:
            engine.submit(crossing(), config('requested'), 1); result = wait(engine)
            self.assertEqual(result['stacking']['status'], 'incomplete')

    def test_assignment_clear_and_unchanged_do_not_accumulate(self):
        values = crossing()
        with NativeStackEngine() as engine:
            engine.submit(values, config(), 1); wait(engine); original = engine.surfaces()
            engine.submit(values, config(), 2); wait(engine)
            for k, v in engine.surfaces().items(): np.testing.assert_array_equal(v, original[k])
            engine.submit(values, settings(), 3); wait(engine)
            for k, v in engine.surfaces().items(): np.testing.assert_array_equal(v, values[k.muscle == 'b'].own)

    def test_fixed_constraint_is_not_released(self):
        values = crossing(); b = values[1]
        values[1] = replace(b, material=replace(b.material, fixed=np.array([0], dtype=np.int64)))
        with NativeStackEngine() as engine:
            engine.submit(values, config(), 1); result = wait(engine)
            self.assertEqual(result['stacking']['status'], 'incomplete')
            for k, v in engine.surfaces().items(): np.testing.assert_array_equal(v, values[k.muscle == 'b'].own)

    def test_explicit_pair_outside_broad_phase(self):
        values = [inflated('a', 0, .2), inflated('b', 3, 3.1)]
        with NativeStackEngine() as engine:
            engine.submit(values, config(), 1); result = wait(engine)
            self.assertEqual(len(result['pairs']), 1)
            self.assertEqual(result['stacking']['status'], 'complete')

    def test_explicit_pair_respects_cache_budget_after_broad_filter(self):
        values = [inflated('a', 0, .2), inflated('b', 3, 3.1)]
        with NativeStackEngine() as engine:
            for generation in (1, 2):
                engine.submit(values, replace(config(), cache_bytes=1), generation); result = wait(engine)
                self.assertEqual(result['stacking']['status'], 'complete')
                self.assertLessEqual(result['timings']['pair_summary_cache_bytes'], 1)
                self.assertEqual(len(result['pairs']), 1)
