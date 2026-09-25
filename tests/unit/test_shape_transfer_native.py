import ctypes as ct
import unittest
from types import SimpleNamespace
import numpy as np
from core.authoring.shape_transfer_native import fit, Input, library
from core.authoring.errors import AuthoringError


def fixture():
    v = np.array([[x, y, z] for x in (-1., 1.) for y in (-1., 1.) for z in (-1., 1.)])
    f = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1],
                  [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]])
    return v, f, np.array([1, 0, 0, 0, 0, 0, 0, 1])


def settings(**overrides):
    return dict(dict(collision_strength=0., max_iterations=40), **overrides)


class ShapeTransferNativeTests(unittest.TestCase):
    def test_proper_and_reflected_similarity_recovery(self):
        v, f, fixed = fixture(); angle = .76
        rotation = np.array([[np.cos(angle), -np.sin(angle), 0], [np.sin(angle), np.cos(angle), 0], [0, 0, 1.]])
        for orientation in (1, -1):
            for scale in (.001, 1., 1000.):
                target = v*np.array([orientation, 1, 1])@rotation.T*scale+[7, -5, 3]
                result = fit(v, target, f, fixed, [], settings(), orientation)
                np.testing.assert_allclose(result['vertices'], target, atol=scale*1e-10)
                self.assertEqual(result['fitting']['stop_reason'], 'step_tolerance')

    def test_bands_exact_and_deterministic_for_nonrigid_target(self):
        v, f, fixed = fixture(); target = v.copy(); target[:, 0] *= .35; target[0] += [.1, .2, .3]
        a = fit(v, target, f, fixed, [], settings()); b = fit(v, target, f, fixed, [], settings())
        np.testing.assert_array_equal(a['vertices'][fixed.astype(bool)], target[fixed.astype(bool)])
        np.testing.assert_array_equal(a['vertices'], b['vertices'])
        self.assertGreater(np.linalg.norm(a['vertices']-target), .01)

    def test_collision_moves_free_vertices_preserves_locked_ones(self):
        v, f, fixed = fixture(); source = v*.3+[.9, 0, 0]
        bone = SimpleNamespace(vertices=v, faces=f, identity='cube')
        before = fit(source, source, f, fixed, [], settings())
        after = fit(source, source, f, fixed, [bone], dict(collision_strength=100., max_iterations=80))
        movable = ~fixed.astype(bool); inside = movable & (source[:, 0] < 1)
        self.assertGreater(after['vertices'][inside, 0].mean(), before['vertices'][inside, 0].mean())
        np.testing.assert_array_equal(after['vertices'][fixed.astype(bool)], source[fixed.astype(bool)])

    def test_malformed_inputs_rejected_before_native_call(self):
        v, f, fixed = fixture()
        invalid = [(v, v, f+100, fixed, settings()), (v, v, f+.1, fixed, settings()),
                   (v, v, f, fixed*0, settings()), (v, v, f, fixed, settings(radius_fraction=0)),
                   (v*np.nan, v, f, fixed, settings()), (v[:, :2], v, f, fixed, settings())]
        for source, target, faces, pins, config in invalid:
            with self.assertRaises(AuthoringError): fit(source, target, faces, pins, [], config)

    def test_missing_obstacles_and_invalid_abi_fail_explicitly(self):
        v, f, fixed = fixture()
        with self.assertRaises(AuthoringError): fit(v, v, f, fixed, [])
        self.assertEqual(library().af_transfer_shape_fit(None), 1)
        self.assertEqual(library().af_transfer_shape_fit(ct.byref(Input())), 1)

    def test_budget_stop_is_distinct_from_convergence(self):
        v, f, fixed = fixture(); target = v*np.array([.3, 1., 1.])
        result = fit(v, target, f, fixed, [], settings(max_iterations=1, convergence=1e-14))
        self.assertEqual(result['fitting']['iterations'], 1)
        self.assertEqual(result['fitting']['stop_reason'], 'iteration_limit')
