import unittest
import numpy as np
from core.authoring.base_partition import calculate
from core.authoring.errors import AuthoringError


def fixture():
    t = np.linspace(0, 4, 33); bump = .2*np.sin(np.pi*t/4)-.05
    a = np.array([np.c_[t, t*0-1, t*0], np.c_[t, bump, t*0]])
    b = np.array([np.c_[t, -bump, .05*np.sin(np.pi*t/4)], np.c_[t, t*0+1, t*0]])
    return [a, b]


def settings():
    return dict(along_axis=[1, 0, 0], across_axis=[0, 1, 0], blend_distance=.25,
        max_displacement=.3, max_depth_gap=.1, max_outline_error=1e-5)


class BasePartitionTests(unittest.TestCase):
    def test_ragged_and_nonfinite_inputs_report_validation_errors(self):
        paths = [p.tolist() for p in fixture()]; paths[0][0].pop()
        with self.assertRaises(AuthoringError): calculate(paths, [1, 0], settings())
        paths = fixture(); paths[0][0, 3, 2] = np.nan
        with self.assertRaises(AuthoringError): calculate(paths, [1, 0], settings())

    def test_overlap_becomes_one_border_without_losing_outline(self):
        paths = fixture(); result = calculate(paths, [1, 0], settings()); a, b = map(np.asarray, result['paths'])
        t = np.linspace(.5, 3.5, 79)
        for axis in (1, 2):
            np.testing.assert_allclose(np.interp(t, a[-1, :, 0], a[-1, :, axis]), np.interp(t, b[0, :, 0], b[0, :, axis]), atol=1e-10)
        np.testing.assert_allclose(a[0, :, 1], -1); np.testing.assert_allclose(b[-1, :, 1], 1)
        for old, new in zip(paths, (a, b)): np.testing.assert_array_equal(old[:, [0, -1]], new[:, [0, -1]])
        self.assertLess(result['outer_border_resampling_error'], 1e-12)

    def test_reversed_curves_retain_direction_and_shared_border(self):
        paths = fixture(); paths[1] = paths[1][:, ::-1]; out = calculate(paths, [1, 0], settings())
        self.assertGreater(out['paths'][1][0][0][0], out['paths'][1][0][-1][0])
        self.assertTrue(all(np.all(np.diff(s) > 0) for rows in out['stations'] for s in rows))

    def test_layer_separation_and_large_changes_are_rejected(self):
        for key, value, code in [('max_depth_gap', .001, 'DEPTH_GAP'), ('max_displacement', .001, 'DISPLACEMENT_LIMIT')]:
            with self.assertRaises(AuthoringError) as error: calculate(fixture(), [1, 0], dict(settings(), **{key: value}))
            self.assertIn(code, error.exception.code)

    def test_locked_endpoints_and_wrong_sides_are_rejected(self):
        paths = fixture(); paths[0][-1, 0, 1] = .2
        with self.assertRaises(AuthoringError) as error: calculate(paths, [1, 0], settings())
        self.assertIn('LOCKED_ENDPOINT', error.exception.code)
        with self.assertRaises(AuthoringError): calculate(fixture(), [0, 0], settings())

    def test_nonmonotone_chart_fails_without_guessing(self):
        paths = fixture(); paths[0][0, 10, 0] = -1
        with self.assertRaises(AuthoringError) as error: calculate(paths, [1, 0], settings())
        self.assertIn('NONMONOTONE', error.exception.code)

    def test_disjoint_borders_do_not_get_joined(self):
        paths = fixture(); paths[0][-1, :, 1] = -.2; paths[1][0, :, 1] = .2
        result = calculate(paths, [1, 0], settings())
        self.assertFalse(result['changed']); self.assertEqual(result['maximum_displacement'], 0)

    def test_multiple_local_overlap_intervals(self):
        paths = fixture(); bump = .2*np.sin(np.linspace(0, 3*np.pi, 33))-.05
        paths[0][-1, :, 1] = bump; paths[1][0, :, 1] = -bump
        result = calculate(paths, [1, 0], settings()); a, b = map(np.asarray, result['paths'])
        self.assertGreater(np.interp(2, b[0, :, 0], b[0, :, 1])-np.interp(2, a[-1, :, 0], a[-1, :, 1]), .3)

    def test_rigid_transform_equivariance(self):
        paths = fixture(); rotation = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]]); translation = [5, -3, 7]
        spec = dict(settings(), along_axis=rotation[0], across_axis=rotation[1])
        out = calculate([p@rotation+translation for p in paths], [1, 0], spec)
        expected = calculate(paths, [1, 0], settings())
        for a, b in zip(out['paths'], expected['paths']): np.testing.assert_allclose(a, np.asarray(b)@rotation+translation, atol=1e-9)
