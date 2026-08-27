import unittest

import numpy as np

from core.vcp.v2.contracts import V2Settings
from core.vcp.v2.structural import _normal_gradient, _static_settings, structural_energy
from core.vcp.v2.subfiber_sqp import _span_settings
from core.vcp.v2.trust_sqp import (_proximal_model, model_reduction, objective_energy,
                                   objective_gradient)


class TestFiberV2TrueLengthIrls(unittest.TestCase):
    def setUp(self):
        self.points = np.array(((0., 0., 0.), (.6, .2, 0.), (1., .7, .1), (1.8, .8, 0.)))
        self.reference = self.points + np.array((0., .1, .05))
        self.settings = V2Settings(node_count=4, length_weight=.9, curvature_weight=0.)

    def test_disabled_path_is_quadratic_compatible(self):
        expected = structural_energy(self.points, self.reference, self.settings)
        actual = objective_energy(self.points, self.reference, self.settings)
        self.assertEqual(actual, expected)
        gradient = _normal_gradient(self.points, self.reference, _static_settings(self.settings))
        np.testing.assert_allclose(objective_gradient(self.points, self.reference, self.settings), gradient)

    def test_true_length_energy_matches_smoothed_arc_length(self):
        epsilon = 1.0e-5; edges = np.diff(self.points, axis=0)
        expected = self.settings.fidelity_weight * np.sum((self.points - self.reference) ** 2)
        expected += self.settings.length_weight * np.sum(np.sqrt(np.sum(edges ** 2, axis=1) + epsilon ** 2))
        self.assertAlmostEqual(objective_energy(self.points, self.reference, self.settings, epsilon).total, expected)

    def test_true_length_gradient_matches_finite_difference(self):
        epsilon = 1.0e-5; direction = np.arange(12, dtype=float).reshape((4, 3)) / 11.
        step = 1.0e-6; plus = self.points + step * direction; minus = self.points - step * direction
        numeric = (objective_energy(plus, self.reference, self.settings, epsilon).total -
                   objective_energy(minus, self.reference, self.settings, epsilon).total) / (2. * step)
        analytic = 2. * np.sum(objective_gradient(
            self.points, self.reference, self.settings, epsilon) * direction)
        self.assertAlmostEqual(numeric, analytic, places=6)

    def test_true_length_span_preserves_global_length_weight(self):
        quadratic = _span_settings(self.settings, 3, True, False)
        true_length = _span_settings(self.settings, 3, True, True)
        self.assertGreater(quadratic.length_weight, self.settings.length_weight)
        self.assertEqual(true_length.length_weight, self.settings.length_weight)

    def test_spacing_gradient_matches_finite_difference(self):
        weight = .7; direction = np.arange(12, dtype=float).reshape((4, 3)) / 11.
        step = 1.0e-6; plus = self.points + step * direction
        minus = self.points - step * direction
        numeric = (objective_energy(plus, self.reference, self.settings, 1e-5, weight).total -
                   objective_energy(minus, self.reference, self.settings, 1e-5, weight).total) / (2 * step)
        analytic = 2 * np.sum(objective_gradient(
            self.points, self.reference, self.settings, 1e-5, weight) * direction)
        self.assertAlmostEqual(numeric, analytic, places=6)

    def test_proximal_model_anchors_only_the_temporary_step(self):
        bands = (np.ones(4), np.zeros(4), np.zeros(4)); rhs = np.zeros((4, 3))
        output, target = _proximal_model(bands, rhs, self.points, 2.0)
        np.testing.assert_allclose(output[0], 3.0); np.testing.assert_allclose(target, 2.0 * self.points)
        self.assertEqual(objective_energy(self.points, self.reference, self.settings),
                         structural_energy(self.points, self.reference, self.settings))

    def test_model_prediction_contains_proximal_step_cost(self):
        candidate = self.points + .01; arguments = (self.points, candidate, self.reference,
            self.settings, (), {}, True, 1.0e-5, 0.0)
        plain = model_reduction(*arguments, 0.0); regularized = model_reduction(*arguments, 3.0)
        expected = 3.0 * np.sum((candidate - self.points) ** 2)
        self.assertAlmostEqual(plain - regularized, expected)


if __name__ == "__main__":
    unittest.main()
