import unittest
import numpy as np
from core.authoring.smooth_native import fit, evaluate, coordinates
from core.authoring.errors import AuthoringError


def grid(left=0, right=1):
    uv = coordinates(9, 17)
    return np.c_[left+(right-left)*uv[:, 0], uv[:, 1]*4, uv[:, 0]*.1+uv[:, 1]*.2].reshape(9, 17, 3)


def pins(grids):
    return [[i, u, v, *g[-1 if u else 0, -1 if v else 0]] for i, g in enumerate(grids) for u in (0, 1) for v in (0, 1)]


class SmoothNativeTests(unittest.TestCase):
    def test_affine_recovery_and_world_scale(self):
        for scale in (.001, 1., 1000.):
            g = grid()*scale+np.array([2, -3, 5]); control = fit([g], pins([g]), [], {})[0]
            np.testing.assert_allclose(evaluate(control, coordinates(9, 17)), g.reshape(-1, 3), atol=scale*1e-7)

    def test_joint_boundary_is_exact_between_pins(self):
        a, b = grid(-1, 0), grid(0, 1); b[:, :, 2] += .25*np.sin(np.linspace(0, np.pi, 17))[None]
        values = pins([a, b]); values[4][3:] = values[2][3:]; values[5][3:] = values[3][3:]
        controls = fit([a, b], values, [[0, 1, 1, 0]], {})
        t = np.linspace(0, 1, 57)
        first = evaluate(controls[0], np.c_[np.ones(len(t)), t]); second = evaluate(controls[1], np.c_[np.zeros(len(t)), t])
        np.testing.assert_allclose(first, second, atol=1e-8)

    def test_contradictory_seam_pins_fail(self):
        a, b = grid(-1, 0), grid(0, 1)
        with self.assertRaises(AuthoringError): fit([a, b], pins([a, b]), [[0, 1, 1, 0]], {})

    def test_noise_is_reduced_without_adding_controls(self):
        g = grid(); g[:, 1:-1, 2] += .02*np.cos(np.arange(15)*np.pi)[None]
        control = fit([g], pins([g]), [], {})[0]; result = evaluate(control, coordinates(9, 17)).reshape(g.shape)
        self.assertEqual(control.shape, (4, 6, 3))
        self.assertLess(np.linalg.norm(np.diff(result, n=2, axis=1)), np.linalg.norm(np.diff(g, n=2, axis=1))*.1)

    def test_invalid_nonfinite_input_rejected(self):
        g = grid(); g[2, 3, 0] = float('nan')
        with self.assertRaises(AuthoringError): fit([g], pins([g]), [], {})

    def test_ruled_fit_shared_boundary_and_sparse_shape(self):
        a, b = grid(-1, 0), grid(0, 1); b[:, :, 2] += .1
        controls = fit([a, b], pins([a, b]), [[0, 1, 1, 0]], {}, [3, 2])
        self.assertEqual([c.shape for c in controls], [(3, 6, 3), (2, 6, 3)])
        t = np.linspace(0, 1, 61)
        np.testing.assert_allclose(evaluate(controls[0], np.c_[t*0+1, t], True), evaluate(controls[1], np.c_[t*0, t], True), atol=1e-8)
        for c in controls:
            left = evaluate(c, np.c_[t*0, t], True); right = evaluate(c, np.c_[t*0+1, t], True)
            self.assertTrue(np.all(right[:, 0]-left[:, 0] > .9))

    def test_native_boundary_rejects_malformed_array_shapes(self):
        with self.assertRaises(AuthoringError): fit([grid()], [], [], {}, [2, 3])
        with self.assertRaises(AuthoringError): evaluate(np.zeros((4, 6, 3)), np.zeros((3, 3)))

    def test_indexed_triangle_chart_matches_planar_grid(self):
        from core.authoring.smooth_chart import grid as chart_grid
        from core.authoring.smooth_native import faces
        g = grid(); v = g.reshape(-1, 3); f = faces(9, 17)
        out = chart_grid(v, f, dict(source_triangles=list(range(len(f))), boundary_vertex_ids=[0, 136, 152, 16]))
        self.assertEqual(out.shape, (17, 49, 3))
        np.testing.assert_allclose(out[0, 0], v[0], atol=1e-8)
        np.testing.assert_allclose(out[-1, -1], v[152], atol=1e-8)
