"""Wire/document strictness, lowering boundaries and shared numeric geometry."""
from copy import deepcopy
import unittest
import numpy as np
from core.authoring.profile_config import wire, normalize
from core.vcp.muscle_section_profile import reset_profile
from core.authoring import schema, native_geometry, inflation, lowering, reconciliation, fitting
from core.authoring.errors import AuthoringError
from test_muscle_section_profile import grid


def request(configuration):
    return dict(dsl='anthroforge.authoring.protocol', version='0.4.0', message_type='request', request_id='profile',
        op='muscles.profile_preview', params=dict(scene_id='root', target=dict(muscle_id='MUSCLE_1'),
        expected_scene_revision='scene', expected_base_revision='base', configuration=configuration))


class AuthoringSectionProfileTests(unittest.TestCase):
    def test_strict_wire_rejects_partial_unknown_and_wrong_units(self):
        valid = wire(reset_profile(.1))
        schema.validate(request(valid), 'protocol')
        with self.assertRaises(AuthoringError): schema.validate(dict(request(valid), version='0.3.0'), 'protocol')
        for change in (dict(profile_version=2), dict(direction='axis'), dict(peaks=[.01]*4),
                       dict(depths=[dict(value=.1, unit='mm')]*4), dict(amount=.1), dict(depths=[dict(value=11, unit='scene')]*4)):
            with self.assertRaises(AuthoringError): schema.validate(request(dict(valid, **change)), 'protocol')
        missing = deepcopy(valid); missing.pop('roundness')
        with self.assertRaises(AuthoringError): schema.validate(request(missing), 'protocol')
        with self.assertRaises(ValueError): normalize(dict(valid, peaks=['0.5']*4))

    def test_document_profile_retains_metadata_and_forbids_legacy_fields(self):
        root = schema.bundled('authoring', '0.4.0')
        self.assertIn('section_profile', schema.bundled('authoring', '0.3.0')['$defs'])
        value = dict(wire(reset_profile(.1)), applies_to=['fan'], calibration='candidate',
            shape_checks=[dict(metric='height', statistic='max', s=.5, u_range=[0, 1], minimum=dict(value=0, unit='scene'),
                               maximum=dict(value=1, unit='scene'))], evidence=dict(basis='designer_authored', sources=[], note='test'))
        value['shape_checks'][0]['metric'] = 'normal_height'
        native = root['$defs']['native_section_profile']
        schema._check(value, native, root, '')
        with self.assertRaises(AuthoringError): schema._check(dict(value, amount=dict(value=1, unit='scene')), native, root, '')

    def test_height_intent_scales_every_depth_and_other_intents_are_explicit(self):
        value = wire(reset_profile(.2))
        lowering.shape_intent(value, dict(height_scale=2))
        np.testing.assert_allclose([v['value'] for v in value['depths']], [.2, .4, .4, .2])
        for field in ('width_scale', 'belly_position', 'taper'):
            with self.assertRaisesRegex(AuthoringError, 'PROFILE_INTENT_UNSUPPORTED|Profile intent unsupported'):
                lowering.shape_intent(value, {field: 1})

    def test_document_and_native_numeric_share_profile_evaluator(self):
        config = wire(reset_profile(.2)); config['depths'] = [row['value'] for row in config['depths']]
        base = grid(); u, s = np.linspace(0, 1, len(base)), np.linspace(0, 1, base.shape[1])
        result, native, _ = native_geometry.evaluate(base, u, s, config, False)
        expected = inflation.inflate(result.base_vertices.reshape(base.shape), u, s, config)
        np.testing.assert_allclose(result.inflated_vertices.reshape(base.shape), expected, atol=1e-14)
        self.assertEqual(native['inflation_mode'], 'SECTION_PROFILE')
        self.assertNotIn('inflation_max_value', native)

    def test_every_depth_uses_measurement_resolver_and_fitting_is_rejected(self):
        class Resolver:
            def measure(self, value, references):
                return value['value'] * references['scale']
        config = inflation.resolved_preset(wire(reset_profile(.1)), Resolver(), dict(scale=2))
        np.testing.assert_allclose(config['depths'], [.1, .2, .2, .1])
        with self.assertRaises(AuthoringError) as error:
            fitting.fit(dict(config=config), dict(fitting=dict(enabled=True)))
        self.assertEqual(error.exception.code, 'PROFILE_FITTING_UNSUPPORTED')

    def test_semantic_adoption_reconstructs_complete_profile(self):
        values = dict(section_profile_version=1, section_depths=(.1, .2, .3, .4), section_peaks=(.2, .4, .6, .8),
                      section_roundness=2, section_direction='SECTION', inflation_enabled=False, flip_normals=True)
        preset = dict(native=dict(applies_to=['fan'], calibration='candidate', shape_checks=[], evidence={}), intent=dict(width_scale=2))
        patch = reconciliation.profile_patch(preset, 'muscle', 'MUSCLE_1', values)
        shape = patch[0]['value']
        self.assertNotIn('intent', shape)
        self.assertEqual(shape['native']['depths'][2], dict(value=float(np.float32(.3)), unit='scene'))
        self.assertEqual(shape['native']['direction'], 'section')
        self.assertFalse(shape['native']['enabled']); self.assertTrue(shape['native']['flip_normals'])
