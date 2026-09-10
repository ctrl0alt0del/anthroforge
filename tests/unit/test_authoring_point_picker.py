"""Closed world-point request contract, including nonfinite and stale inputs."""
import unittest
from core.authoring.errors import AuthoringError
from core.authoring.schema import validate, bundled
from tools.authoring_schema_v04 import snap_points_operation


def request(**params):
    values = dict(scene_id='root', instance_id='AFI_owner', expected_scene_revision='current', points=[[1, 2, 3]])
    values.update(params)
    return dict(version='0.4.0', message_type='request', request_id='snap', op='anatomy.snap_points', params=values)


class PointPickerContractTests(unittest.TestCase):
    def test_valid_request_and_generated_schema_match(self):
        validate(request(max_distance=2, collision_radius=.001), 'protocol')
        operations = bundled('protocol', '0.4.0')['oneOf']
        self.assertIn(snap_points_operation(), operations)

    def test_invalid_coordinates_options_and_bounds_are_rejected(self):
        cases = [dict(points=[]), dict(points=[[1, 2]]), dict(points=[[0, 0, float('nan')]]),
                 dict(points=[[0, 0, float('inf')]]), dict(max_distance=-1), dict(collision_radius=-1),
                 dict(points=[[0, 0, 0]] * 257), dict(normal_offset=.1), dict(instance_id='')]
        for params in cases:
            with self.subTest(params=params), self.assertRaises(AuthoringError):
                validate(request(**params), 'protocol')

    def test_revision_is_required(self):
        value = request()
        del value['params']['expected_scene_revision']
        with self.assertRaises(AuthoringError):
            validate(value, 'protocol')
