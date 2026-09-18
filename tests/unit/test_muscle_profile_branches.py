"""Profiles and prepared branch inflation share dispatch, never mode encodings."""
from dataclasses import replace
import unittest
from unittest.mock import patch
import numpy as np
from core.vcp.branched_numeric import BranchedMuscleRequest
from core.vcp.branched_surface import prepare_assembly
from core.vcp.muscle_numeric import execute_muscle_batch, make_muscle_request
from core.vcp.muscle_section_profile import SectionProfileSpec
from core.vcp.prepared_inflation import inflate_prepared
from core.authoring import branched_evaluation
from core.authoring.errors import AuthoringError
from test_branched_surface import fixture
from test_muscle_numeric_native import _spec
from test_muscle_section_profile import grid


def branch_request():
    main, branch = fixture()
    assembly = prepare_assembly(main, (branch,))
    specs = (_spec(inflation_mode='DISTRIBUTED', inflation_enabled=True, inflation_max_value=.2),
             _spec(inflation_mode='CTRL_POINT', inflation_enabled=True, initialize_control=True))
    return BranchedMuscleRequest('branch', assembly, specs)


class ProfileBranchNumericTests(unittest.TestCase):
    def test_mixed_order_geometry_and_backend_metadata(self):
        profile = make_muscle_request('profile', grid(), _spec(target_count=21, inflation_enabled=True,
            inflation_mode='SECTION_PROFILE', section_profile=SectionProfileSpec()))
        legacy = make_muscle_request('legacy', grid(), _spec(target_count=21))
        requests = (branch_request(), profile, legacy, profile, branch_request())
        batch = execute_muscle_batch(requests, 'NATIVE')
        self.assertEqual(batch.backend, 'NATIVE+NUMPY_SECTION_PROFILE')
        self.assertEqual([r.muscle_id for r in batch.results], [r.muscle_id for r in requests])
        for request, result in zip(requests, batch.results):
            expected = execute_muscle_batch((request,), 'NATIVE').results[0]
            self.assertFalse(result.error, result.error)
            np.testing.assert_array_equal(result.inflated_vertices, expected.inflated_vertices)
            np.testing.assert_array_equal(result.faces, expected.faces)

    def test_branch_main_and_child_profile_rejected_before_native_packing(self):
        request = branch_request()
        for index in range(2):
            specs = list(request.part_specs)
            specs[index] = replace(specs[index], inflation_mode='SECTION_PROFILE', inflation_enabled=False)
            with patch('core.vcp.prepared_inflation_native.inflate_native', side_effect=AssertionError('packed')):
                result = execute_muscle_batch((replace(request, part_specs=tuple(specs)),), 'NATIVE').results[0]
            self.assertIn('PROFILE_DOMAIN_UNSUPPORTED', result.error)
            self.assertEqual(len(result.inflated_vertices), 0)

    def test_prepared_invalid_modes_reject_before_weights_for_both_backends(self):
        for backend in ('PYTHON', 'NATIVE'):
            for mode, code in (('SECTION_PROFILE', 'PROFILE_DOMAIN_UNSUPPORTED'), ('FUTURE', 'PROFILE_MODE_UNSUPPORTED')):
                with patch('core.vcp.prepared_inflation.weights', side_effect=AssertionError('evaluated')):
                    with self.assertRaisesRegex(ValueError, code):
                        inflate_prepared(grid(), np.zeros(grid().shape[:2], bool), _spec(inflation_mode=mode), backend)

    def test_invalid_branch_keeps_valid_profile_in_same_batch(self):
        request = branch_request()
        bad = replace(request, part_specs=(request.spec, replace(request.spec, inflation_mode='FUTURE')))
        profile = make_muscle_request('profile', grid(), _spec(inflation_mode='SECTION_PROFILE',
            section_profile=SectionProfileSpec(), target_count=21, inflation_enabled=True))
        results = execute_muscle_batch((bad, profile, request), 'NATIVE').results
        self.assertIn('PROFILE_MODE_UNSUPPORTED', results[0].error)
        self.assertFalse(results[1].error)
        self.assertFalse(results[2].error)
        self.assertGreater(np.max(abs(results[1].base_vertices-results[1].inflated_vertices)), .01)

    def test_branched_document_profile_rejects_before_fiber_evaluation(self):
        document = dict(muscles=dict(main=dict(volume_preset='shape')),
                        volume_presets=dict(shape=dict(mode='section_profile')))
        with patch.object(branched_evaluation, 'evaluate_muscle', side_effect=AssertionError('solved')):
            with self.assertRaises(AuthoringError) as error:
                branched_evaluation.evaluate(document, 'main', {}, None, None)
        self.assertEqual(error.exception.code, 'PROFILE_DOMAIN_UNSUPPORTED')

    def test_composed_profile_properties_reject_explicitly(self):
        part = dict(native_properties=dict(inflation_mode='SECTION_PROFILE', section_profile_version=1))
        with self.assertRaises(AuthoringError) as error:
            branched_evaluation._spec(part, grid())
        self.assertEqual(error.exception.code, 'PROFILE_DOMAIN_UNSUPPORTED')
