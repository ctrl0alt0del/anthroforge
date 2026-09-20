"""Legacy native inflation edits retain strict guarded protocol semantics."""
import unittest
from core.authoring.profile_config import normalize, native_values
from core.authoring.schema import validate
from core.authoring.errors import AuthoringError
from test_authoring_section_profile import request


class LegacyProfileTests(unittest.TestCase):
    def test_partial_parameters_and_explicit_world_control_are_supported(self):
        value = dict(mode='control_point', native=dict(inflation_max_value=.3, inflation_ctrl_world=[1, 2, 3]), surface_flip_normals=True)
        validate(request(value), 'protocol')
        native = native_values(value)
        self.assertEqual(native['inflation_mode'], 'CTRL_POINT')
        self.assertTrue(native['inflation_ctrl_initialized'])
        self.assertEqual(native['inflation_ctrl_world'], [1., 2., 3.])
        self.assertNotIn('surface_flip_normals', native)
        self.assertEqual(native_values(dict(mode='distributed')), dict(inflation_mode='DISTRIBUTED'))

    def test_invalid_native_values_never_rely_on_rna_clamping(self):
        for native in (dict(inflation_max_value=11), dict(inflation_max_value=True), dict(inflation_direction_depth=0),
                       dict(inflation_ctrl_world=[1, 2]), dict(inflation_ctrl_world=[0, float('nan'), 0]),
                       dict(inflation_ctrl_initialized=False), dict(inflation_enabled=1), dict(inflation_falloff_type='OTHER')):
            with self.subTest(native=native):
                with self.assertRaises(AuthoringError): normalize(dict(mode='control_point', native=native))

    def test_side_requires_explicit_native_variant_and_boolean(self):
        for value in (dict(mode='distributed', surface_flip_normals=True), dict(mode='distributed', native={}, surface_flip_normals=1)):
            with self.assertRaises(AuthoringError): normalize(value)
            with self.assertRaises(AuthoringError): validate(request(value), 'protocol')
