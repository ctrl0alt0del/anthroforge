import unittest

import numpy as np

from core.vcp.v2 import V2Settings
from tools.fiber_v2_high_order_basis import (
    build_high_order_basis, structural_energy, structural_system,
)


def _seed(count=64):
    t = np.linspace(0.0, 1.0, count)
    return np.column_stack((t, .2 * np.sin(3.0 * t), .1 * np.cos(5.0 * t)))


class FiberV2HighOrderBasisTests(unittest.TestCase):
    def test_stride_one_interpolates_seed_and_hard_pins(self):
        seed = _seed(); pins = (0, 12, 32, 56, 63)
        basis = build_high_order_basis(seed, pins, 1.0, 4)
        np.testing.assert_allclose(basis.output @ basis.controls, seed, atol=2.0e-12)
        np.testing.assert_allclose(basis.controls[list(basis.pin_controls)], seed[list(pins)])

    def test_dense_proxy_contains_every_output_sample(self):
        seed = _seed(); basis = build_high_order_basis(seed, (0, 12, 32, 56, 63), 1.4, 4)
        proxy, output = basis.proxy @ basis.controls, basis.output @ basis.controls
        np.testing.assert_allclose(proxy[::4], output, atol=2.0e-12)
        self.assertEqual(len(proxy), 4 * (len(seed) - 1) + 1)

    def test_reduced_basis_has_expected_control_count(self):
        basis = build_high_order_basis(_seed(), (0, 12, 32, 56, 63), 1.4, 4)
        self.assertEqual(len(basis.controls), 48)
        self.assertEqual(basis.spans, ((0, 12, 10), (12, 32, 16), (32, 56, 19), (56, 63, 6)))

    def test_structural_gradient_matches_finite_difference(self):
        seed = _seed(17); pins = (0, 8, 16); settings = V2Settings(node_count=17)
        basis = build_high_order_basis(seed, pins, 1.3, 3); matrix, rhs = structural_system(basis, seed, settings, pins)
        controls = basis.controls.copy(); direction = np.sin(np.arange(controls.size)).reshape(controls.shape)
        epsilon = 1.0e-6; analytic = 2.0 * np.sum((matrix @ controls - rhs) * direction)
        plus = structural_energy(controls + epsilon * direction, basis, seed, settings, pins)
        minus = structural_energy(controls - epsilon * direction, basis, seed, settings, pins)
        self.assertAlmostEqual(analytic, (plus - minus) / (2.0 * epsilon), places=7)


if __name__ == "__main__":
    unittest.main()
