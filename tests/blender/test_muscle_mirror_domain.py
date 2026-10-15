"""Material crops follow independently evaluated muscle instances."""
from types import SimpleNamespace
import unittest
import numpy as np
from mathutils import Matrix
from anthroforge.core.visualization.geometry_instance import mirrored, domain
from anthroforge.core.visualization.mirror_rules import mirror_matrix
from anthroforge.core.visualization.muscle_numeric_runtime import capture_domain
from anthroforge.core.vcp.muscle_output_domain import capture


def fixture():
    matrix = Matrix.Translation((2., -3., 1.)) @ Matrix.Rotation(.4, 4, 'Z')
    return SimpleNamespace(id_data=SimpleNamespace(matrix_world=matrix), output_domain_mode='PLANE',
                           output_domain_origin=(1., 2., 3.), output_domain_normal=(.3, -.7, .4),
                           output_domain_keep_positive=True)


class MirrorDomainTests(unittest.TestCase):
    def test_independent_mirror_retains_same_material_halfspace(self):
        muscle = fixture(); source = capture(muscle); rule = ('Y', (0., 1.4, 0.))
        n = np.array(source['normal']); origin = n * source['offset']
        samples = origin + np.array([[-.2], [0.], [.4]]) * n
        matrix = np.array(mirror_matrix(*rule)); reflected = samples @ matrix[:3, :3].T + matrix[:3, 3]
        with mirrored(rule): actual = capture_domain(muscle)
        before = samples @ n - source['offset']
        after = reflected @ actual['normal'] - actual['offset']
        np.testing.assert_allclose(after, before, atol=2e-6, rtol=0)
        self.assertEqual(actual['keep_positive'], source['keep_positive'])

    def test_source_capture_and_nested_scope_remain_unchanged(self):
        muscle = fixture(); source = capture(muscle)
        self.assertEqual(capture_domain(muscle), source)
        with mirrored(('X', (2., 0., 0.))):
            first = capture_domain(muscle)
            with mirrored(('Z', (0., 0., 1.))): self.assertNotEqual(capture_domain(muscle), first)
            self.assertEqual(capture_domain(muscle), first)
        self.assertEqual(capture_domain(muscle), source)

    def test_full_domain_stays_full(self):
        with mirrored(('Y', (0., 3., 0.))): self.assertIsNone(domain(None))
