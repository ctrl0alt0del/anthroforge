"""Exercise real native constraints, not mocked optimizer responses."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np
from core.authoring.transfer_constraints_native import fit
from core.authoring.errors import AuthoringError
from test_shape_transfer_native import fixture


def rule(kind, ids, n=8, **values):
    return dict(type=kind, indices=ids, allowed=list(range(n)), tolerance=1e-6, weight=1., **values)


def solve(v, f, records, bones=(), settings=None):
    fixed = np.zeros(len(v), np.int32)
    for r in records:
        if r['type'] in ('attachment', 'protection') and r.get('enabled', True): fixed[r['indices']] = 1
    return fit(v, v, f, fixed, bones, records, np.zeros(len(v), np.int32), settings or dict(max_iterations=60))


class TransferConstraintsNativeTests(unittest.TestCase):
    def setUp(self):
        self.v, self.f, _fixed = fixture()
        self.pin = rule('protection', [0], targets=self.v)

    def test_zero_guide_has_no_hidden_attraction(self):
        goal = self.v.copy(); goal[1:] += [3, 2, 1]
        guide = rule('guide', list(range(8)), targets=goal); guide['weight'] = 0.
        result = solve(self.v, self.f, [self.pin, guide])
        np.testing.assert_allclose(result['vertices'], self.v, atol=1e-12)
        guide['weight'] = 1.; moved = solve(self.v, self.f, [self.pin, guide])
        np.testing.assert_allclose(moved['vertices'][1:], goal[1:], atol=1e-5)
        np.testing.assert_array_equal(moved['vertices'][0], self.v[0])

    def test_exact_conflict_fails_before_fit(self):
        goal = self.v.copy(); goal[0, 0] += .2
        with self.assertRaisesRegex(AuthoringError, 'Exact targets disagree'):
            solve(self.v, self.f, [self.pin, rule('attachment', [0], targets=goal)])

    def test_compatible_exact_constraints_and_order_independence(self):
        guide = rule('guide', [3, 4], targets=self.v+[.2, .4, 0])
        records = [self.pin, rule('attachment', [0], targets=self.v), guide]
        a = solve(self.v, self.f, records); b = solve(self.v, self.f, list(reversed(records)))
        np.testing.assert_allclose(a['vertices'], b['vertices'], atol=1e-12)

    def test_local_selection_and_compact_geodesic_falloff(self):
        guide = rule('guide', [7], targets=self.v+[0, 0, 1], falloff=2.5)
        result = solve(self.v, self.f, [self.pin, guide]); influence = result['constraint_arrays'][0][1]
        self.assertEqual(influence[7], 1.); self.assertTrue(any((influence > 0) & (influence < 1)))
        self.assertEqual(influence[0], 0.)
        np.testing.assert_allclose(result['vertices'][influence == 0], self.v[influence == 0], atol=1e-12)

    def test_coverage_detects_missing_end_even_with_exact_active_targets(self):
        attachment = rule('attachment', [0, 1, 2, 3], targets=self.v, intended=list(range(8)),
                          coverage=dict(axes=[[1, 0, 0], [0, 1, 0]], stations=[2, 2], minimum_fraction=.9))
        result = solve(self.v, self.f, [attachment]); data = result['constraint_arrays']
        self.assertEqual(data[3][0, 0], 0.); self.assertAlmostEqual(data[3][0, 2], .5)
        self.assertEqual(data[4][0, 1], 0.); self.assertLess(data[3][0, 3], .9)

    def test_clearance_has_scope_and_detects_hard_conflict(self):
        bone = SimpleNamespace(vertices=self.v, faces=self.f, identity='cube')
        source = self.v*.3+[.9, 0, 0]; pin = rule('protection', [7], targets=source)
        clearance = rule('clearance', [0], obstacle_instance_ids=['cube'], clearance=.01)
        result = solve(source, self.f, [pin, clearance], [bone])
        self.assertGreater(result['vertices'][0, 0], 1.)
        np.testing.assert_allclose(result['vertices'][1:], source[1:], atol=1e-12)
        with self.assertRaisesRegex(AuthoringError, 'Exact targets disagree'):
            solve(source, self.f, [rule('protection', [0], targets=source), clearance], [bone])

    def test_shape_and_guide_are_independent_terms(self):
        goal = self.v.copy(); goal[7] += [1., 0, 0]
        guide = rule('guide', [7], targets=goal); shape = rule('shape', list(range(8))); shape['weight'] = 100.
        a = solve(self.v, self.f, [self.pin, guide]); b = solve(self.v, self.f, [self.pin, guide, shape])
        self.assertLess(np.linalg.norm(b['vertices']-self.v), np.linalg.norm(a['vertices']-self.v))
        self.assertGreater(b['constraint_arrays'][3][1, 0], .1)

    def test_disabled_constraint_and_iteration_report(self):
        guide = rule('guide', list(range(8)), targets=self.v+4, enabled=False)
        result = solve(self.v, self.f, [self.pin, guide])
        np.testing.assert_allclose(result['vertices'], self.v, atol=1e-12)
        self.assertEqual(result['fitting']['method'], 'indexed_local_constraints.v1')
        self.assertEqual(result['fitting']['stop_reason'], 'step_tolerance')

    def test_coverage_detects_middle_hole_with_both_ends_present(self):
        v = np.array([[x, y, 0.] for x in range(5) for y in range(2)])
        faces = np.array([[2*x, 2*x+1, 2*x+2] for x in range(4)]+[[2*x+1, 2*x+3, 2*x+2] for x in range(4)])
        pins = rule('attachment', [0, 1, 8, 9], n=10, targets=v, intended=list(range(10)),
                    coverage=dict(axes=[[1, 0, 0], [0, 1, 0]], stations=[5, 2], minimum_fraction=.95))
        data = solve(v, faces, [pins])['constraint_arrays']
        self.assertEqual(data[4][0, 0], 1.); self.assertEqual(data[4][0, 4], 1.)
        np.testing.assert_array_equal(data[4][0, 1:4], [0, 0, 0])

    def test_invalid_compiled_inputs_fail_before_native_access(self):
        bad = [dict(self.pin, targets=np.zeros((1, 3))), dict(self.pin, indices=[999]), dict(self.pin, indices=[.5])]
        for row in bad:
            with self.assertRaises(AuthoringError):
                fit(self.v, self.v, self.f, np.array([1, 0, 0, 0, 0, 0, 0, 0]), [], [row], np.zeros(8), {})

    def test_reflected_and_scaled_initial_placement(self):
        for reflection in (-1, 1):
            target = self.v*[reflection*2.5, 2.5, 2.5]+[3, 2, 1]
            pin = dict(self.pin, targets=target)
            result = fit(self.v, target, self.f, np.array([1, 0, 0, 0, 0, 0, 0, 0]), [], [pin], np.zeros(8), {}, reflection)
            np.testing.assert_allclose(result['vertices'], target, atol=1e-12)

    def test_missing_native_export_fails_without_python_fallback(self):
        with patch('core.authoring.transfer_constraints_native.legacy.load_native', return_value=SimpleNamespace()):
            with self.assertRaises(AuthoringError) as caught: solve(self.v, self.f, [self.pin])
        self.assertEqual(caught.exception.code, 'TRANSFER_CONSTRAINT_NATIVE_UNAVAILABLE')
