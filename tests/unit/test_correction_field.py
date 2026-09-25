"""Numerical constraints and topology repair independent of Blender."""
import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.authoring.correction_field import basis, constraints
from core.authoring.correction_topology import split
from core.authoring.base_patch import topology
from core.authoring.errors import AuthoringError
from core.authoring.correction_fit import signed_volume, volume_terms


class CorrectionFieldTests(unittest.TestCase):
    def test_fixed_band_and_outside_influence_have_zero_displacement(self):
        vertices = np.array([[0., 0, 0], [.1, 0, 0], [.5, 0, 0], [2., 0, 0]])
        phi = basis(vertices, np.array([[.5, 0, 0]]), 1., np.array([0]), .3, [dict(center=[0, 0, 0], radius=1.)])
        self.assertEqual(phi[0, 0], 0); self.assertEqual(phi[3, 0], 0)
        self.assertGreater(phi[2, 0], phi[1, 0]); self.assertGreater(phi[1, 0], 0)

    def test_contact_remains_exact_for_arbitrary_free_coefficients(self):
        phi = np.eye(4); vertices = np.zeros((4, 3)); weights = [.2, .3, .5]
        contact = dict(indices=[0, 1, 2], weights=weights, target=np.array([.1, .2, .3]))
        part, null = constraints(phi, vertices, [contact]); rng = np.random.default_rng(1)
        controls = part+null @ rng.normal(size=(null.shape[1], 3))
        np.testing.assert_allclose(np.array(weights) @ controls[:3], contact['target'], atol=1e-12)

    def test_inconsistent_contact_constraints_are_rejected(self):
        a = dict(indices=[0, 1, 2], weights=[1., 0, 0], target=np.array([0., 0, 0]))
        b = dict(a, target=np.array([1., 0, 0]))
        with self.assertRaises(AuthoringError): constraints(np.eye(3), np.zeros((3, 3)), [a, b])

    def test_edge_touching_closed_shells_separate_without_shape_change(self):
        vertices = np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [0, -1, 0], [0, 0, -1]])
        tetra = np.array([[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]])
        faces = np.vstack((tetra, np.array([0, 1, 4, 5])[tetra])); out, tri = split(vertices, faces)
        report = topology(tri); self.assertEqual(report['boundary_edges'], 0); self.assertEqual(report['nonmanifold_edges'], 0)
        self.assertEqual(report['connected_components'], 2)
        a, b = vertices[faces], out[tri]
        area = lambda t: np.linalg.norm(np.cross(t[:, 1]-t[:, 0], t[:, 2]-t[:, 0]), axis=1).sum()
        self.assertAlmostEqual(area(a), area(b))

    def test_volume_derivative_matches_finite_difference(self):
        vertices = np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]])
        faces = np.array([[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]])
        basis = np.random.default_rng(3).normal(size=(4, 2)); field = dict(faces=faces, volume=signed_volume(vertices, faces))
        settings = dict(influence_radius=.7); _residual, derivative = volume_terms(vertices, basis, field, settings)
        for i in range(6):
            delta = np.zeros((2, 3)); delta.flat[i] = 1e-6
            a = volume_terms(vertices+basis @ delta, basis, field, settings)[0]
            b = volume_terms(vertices-basis @ delta, basis, field, settings)[0]
            self.assertAlmostEqual(float((a-b)[0]/2e-6), derivative[0, i], places=5)
