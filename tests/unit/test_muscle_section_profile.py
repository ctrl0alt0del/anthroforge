"""PCHIP oracle, equivariance, validation and native routing contracts."""
from dataclasses import replace
import unittest
from unittest.mock import patch
import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.ndimage import gaussian_filter1d
from core.vcp.muscle_section_profile import SectionProfileSpec, apply_profile, canonical_profile, pchip, scale_profile
from core.vcp.muscle_profile_frames import gaussian
from core.vcp.muscle_profile_cache import CACHE, clear_profile_cache
from core.vcp.muscle_numeric import execute_muscle_batch, make_muscle_request
from test_muscle_numeric_native import _spec


def grid():
    x, y = np.meshgrid(np.linspace(0, 1, 21), np.linspace(0, 1, 13))
    return np.stack((x, y, .03*np.sin(x*3)*y), axis=2)


class SectionProfileTests(unittest.TestCase):
    def test_pchip_matches_scipy_including_extrema_and_flat_segments(self):
        random = np.random.default_rng(13)
        for values in (*random.uniform(0, 10, (30, 6)), (0, 0, 1, 1, 0, 0), (1, 1, 1, 1, 1, 1)):
            samples = np.linspace(0, 1, 333)
            np.testing.assert_allclose(pchip(values, samples), PchipInterpolator(np.linspace(0, 1, 6), values)(samples), atol=2e-14)

    def test_gaussian_matches_nearest_edge_scipy(self):
        values = grid()
        for axis in (0, 1):
            for sigma in (1., 1.56, 2.1):
                np.testing.assert_allclose(gaussian(values, sigma, axis), gaussian_filter1d(values, sigma, axis=axis, mode='nearest'), atol=1e-15)

    def test_perimeter_exact_and_zero_disabled_identity(self):
        base = grid()
        for direction in ('LOCAL', 'SMOOTH', 'SECTION'):
            spec = SectionProfileSpec(direction=direction)
            outer = apply_profile(base, spec)
            self.assertTrue(np.array_equal(outer[[0, -1]], base[[0, -1]]))
            self.assertTrue(np.array_equal(outer[:, [0, -1]], base[:, [0, -1]]))
            self.assertTrue(np.array_equal(apply_profile(base, spec, False), base))
            self.assertTrue(np.array_equal(apply_profile(base, replace(spec, depths=(0,)*4)), base))

    def test_rigid_and_reflected_equivariance(self):
        base = grid()
        rotation = np.array(((0, -1, 0), (1, 0, 0), (0, 0, 1)))
        reflection = np.diag((-1., 1., 1.))
        for mode in ('LOCAL', 'SMOOTH', 'SECTION'):
            spec = SectionProfileSpec(direction=mode)
            outer = apply_profile(base, spec)
            np.testing.assert_allclose(apply_profile(base@rotation+3, spec), outer@rotation+3, atol=1e-14)
            np.testing.assert_allclose(apply_profile(base@reflection, spec, parity=-1), outer@reflection, atol=1e-14)
            np.testing.assert_allclose(apply_profile(base[::-1], spec, parity=-1), outer[::-1], atol=1e-14)

    def test_ranges_versions_precision_and_scaling(self):
        valid = canonical_profile(SectionProfileSpec(depths=(.0123456789,)*4))
        self.assertEqual(valid.depths[0], float(np.float32(.0123456789)))
        for values in (dict(version=0), dict(version=2), dict(depths=(11,)*4), dict(depths=(float('nan'),)*4),
                       dict(peaks=(0,)*4), dict(roundness=.1), dict(direction='ANATOMICAL')):
            with self.assertRaises(ValueError): canonical_profile(replace(valid, **values))
        with self.assertRaises(ValueError): scale_profile(valid, float('inf'))
        with self.assertRaises(ValueError): scale_profile(valid, 100000)
        self.assertEqual(scale_profile(valid, 0).depths, (0,)*4)

    def test_degenerate_frames_only_fail_for_moving_samples(self):
        base = np.zeros((4, 5, 3))
        self.assertTrue(np.array_equal(apply_profile(base, SectionProfileSpec(), False), base))
        with self.assertRaisesRegex(ValueError, 'FRAME_DEGENERATE'): apply_profile(base, SectionProfileSpec())
        with self.assertRaisesRegex(ValueError, 'VERSION'): apply_profile(base, SectionProfileSpec(version=0), False)
        with self.assertRaisesRegex(ValueError, 'GRID'): apply_profile(base[:2], SectionProfileSpec(), False)
        with self.assertRaisesRegex(ValueError, 'PARITY'): apply_profile(base, SectionProfileSpec(), False, parity=True)

    def test_native_mixed_batch_cache_and_winding(self):
        clear_profile_cache()
        spec = _spec(target_count=21, inflation_enabled=True, inflation_mode='SECTION_PROFILE', section_profile=SectionProfileSpec())
        profile = make_muscle_request('profile', grid(), spec)
        legacy = make_muscle_request('legacy', grid(), _spec(target_count=21))
        batch = execute_muscle_batch((legacy, profile, legacy), 'NATIVE')
        self.assertEqual([row.muscle_id for row in batch.results], ['legacy', 'profile', 'legacy'])
        self.assertFalse(batch.results[1].error)
        count = len(CACHE)
        changed = replace(profile, spec=replace(spec, section_profile=replace(spec.section_profile, roundness=2)))
        self.assertFalse(execute_muscle_batch((changed,), 'NATIVE').results[0].error)
        self.assertEqual(len(CACHE), count)
        flipped = replace(profile, spec=replace(spec, topology_flip_normals=True))
        np.testing.assert_array_equal(execute_muscle_batch((flipped,), 'NATIVE').results[0].inflated_vertices, batch.results[1].inflated_vertices)

    def test_invalid_modes_parity_and_domains_never_reach_native(self):
        for changes in (dict(inflation_mode='FUTURE'), dict(inflation_mode='SECTION_PROFILE', closed_u=True)):
            request = make_muscle_request('bad', grid(), _spec(**changes))
            with patch('core.vcp.muscle_numeric_native._pack_requests', side_effect=AssertionError('packed')):
                self.assertTrue(execute_muscle_batch((request,), 'NATIVE').results[0].error)
        request = make_muscle_request('bad', grid(), _spec(), orientation_parity=-1)
        self.assertIn('PARITY_UNSUPPORTED', execute_muscle_batch((request,), 'NATIVE').results[0].error)


if __name__ == '__main__':
    unittest.main()
