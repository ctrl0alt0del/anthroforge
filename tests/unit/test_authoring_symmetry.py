"""Mirror planes preserve chart semantics and earlier-document intent."""
import unittest
from dataclasses import replace
import numpy as np
from test_authoring_core import fixture, cube
from core.authoring.charts import frame
from core.authoring.errors import AuthoringError
from core.authoring.migration import migrate
from core.authoring.schema import validate
from core.authoring.symmetry import native_plane


class AuthoringSymmetryTests(unittest.TestCase):
    def test_reflected_nonuniform_frame_preserves_plane_coordinate(self):
        matrix = np.diag([2., -3., 4., 1.]); matrix[:3, 3] = [7, 8, 9]
        chart = frame(dict(kind='anatomical_box', axes_owner_local=np.eye(3)), replace(cube(), matrix=matrix))
        plane = native_plane(chart, dict(plane_axis='y', plane_coordinate=.25))
        self.assertEqual(plane, dict(axis='Y', origin=[0., 7.25, 0.]))

    def test_native_runtime_rejects_oblique_plane_instead_of_rounding_axis(self):
        matrix = np.eye(4); c = 2**-.5
        matrix[:2, :2] = [[c,-c],[c,c]]
        chart = frame(dict(kind='anatomical_box', axes_owner_local=np.eye(3)), replace(cube(), matrix=matrix))
        with self.assertRaises(AuthoringError) as raised:
            native_plane(chart, dict(plane_axis='y', plane_coordinate=.5))
        self.assertEqual(raised.exception.code, 'UNSUPPORTED_NATIVE_MIRROR_PLANE')

    def test_migration_preserves_native_mirror_reference(self):
        value = fixture()
        for muscle in value['muscles'].values():
            muscle['symmetry'] = dict(mode='native_mirror', plane_frame='origin', plane_axis='y', plane_coordinate=.5)
        migrated = migrate(value)
        validate(migrated)
        for instance in migrated['instances'].values():
            self.assertEqual(instance['symmetry']['plane_frame'], '/skeleton_profiles/default/frames/origin')
            self.assertEqual(instance['symmetry']['mode'], 'native_mirror')
