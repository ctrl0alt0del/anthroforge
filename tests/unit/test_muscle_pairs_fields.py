from dataclasses import replace
import unittest
import numpy as np
from core.muscle_pairs.field import export, limiting
from core.vcp.muscle_numeric import make_muscle_request, execute_muscle_batch
from core.vcp.muscle_envelope import MuscleEnvelopeSpec
from core.vcp.muscle_section_profile import SectionProfileSpec
from test_muscle_envelope import grid
from test_muscle_numeric_native import _spec


def evaluate(spec, **options):
    request = replace(make_muscle_request('M', grid(), spec), **options)
    result = execute_muscle_batch((request,), 'NATIVE').results[0]
    if result.error: raise ValueError(result.error)
    return request, result, export('R', 'M', '', 'revision', request, result, .5)


class FieldTests(unittest.TestCase):
    def spec(self, mode='DISTRIBUTED', **changes):
        return _spec(inflation_enabled=True, inflation_mode=mode, target_count=17,
            section_profile=SectionProfileSpec(), **changes)

    def test_all_laws_actual_and_zero_displacements(self):
        for mode in ('DISTRIBUTED', 'CTRL_POINT', 'SECTION_PROFILE'):
            request, result, domains = evaluate(self.spec(mode)); d = domains[0]
            np.testing.assert_array_equal(d.own, result.inflated_vertices)
            delta = d.own-d.base; length = np.linalg.norm(delta, axis=1); moving = length > 1e-12
            np.testing.assert_allclose(d.direction[moving], delta[moving]/length[moving, None], atol=1e-12)
            expected = limiting(result.base_vertices.reshape(result.row_count, result.column_count, 3), request.spec).reshape(-1, 3)
            np.testing.assert_allclose(d.direction[~moving], expected[~moving], atol=1e-12)

    def test_cropped_fields_keep_canonical_geometry(self):
        plane = dict(normal=(1, 0, 0), offset=.43, keep_positive=True)
        _, result, domains = evaluate(self.spec(), output_domain=plane)
        np.testing.assert_array_equal(domains[0].base, result.base_vertices)
        np.testing.assert_array_equal(domains[0].sources, result.source_faces)
        np.testing.assert_allclose(np.linalg.norm(domains[0].direction, axis=1), 1, atol=1e-12)

    def test_bidirectional_and_disabled_sides(self):
        spec = self.spec('SECTION_PROFILE'); envelope = MuscleEnvelopeSpec((spec,))
        _, result, domains = evaluate(spec, envelope=envelope)
        self.assertEqual([d.key.side for d in domains], ['A', 'B'])
        np.testing.assert_array_equal(domains[0].own, result.side_a)
        np.testing.assert_array_equal(domains[1].own, result.side_b)
        _, _, domains = evaluate(spec, envelope=replace(envelope, secondary=(replace(spec, inflation_enabled=False),)))
        self.assertEqual([d.key.side for d in domains], ['A'])

    def test_zero_height_uses_native_law(self):
        _, _, domains = evaluate(self.spec('CTRL_POINT', inflation_max_value=0))
        np.testing.assert_array_equal(domains[0].base, domains[0].own)
        self.assertTrue(np.isfinite(domains[0].direction).all())

    def test_smoothing_result_is_preserved_without_a_second_solve(self):
        from core.vcp.height_smoothing import HeightSmoothing
        from unittest.mock import patch
        request = make_muscle_request('M', grid(), self.spec('SECTION_PROFILE', smoothing=HeightSmoothing(mode='HEIGHT')))
        result = execute_muscle_batch((request,), 'NATIVE').results[0]
        with patch('core.vcp.height_smoothing_native.smooth', side_effect=AssertionError('second solve')):
            domains = export('R', 'M', '', '', request, result, .5)
        np.testing.assert_array_equal(domains[0].own, result.inflated_vertices)

    def test_branched_provenance_and_crop(self):
        from test_branched_surface import fixture
        from core.vcp.branched_surface import prepare_assembly
        from core.vcp.branched_numeric import BranchedMuscleRequest
        main, branch = fixture(); assembly = prepare_assembly(main, (branch,))
        request = BranchedMuscleRequest('M', assembly, (self.spec(), self.spec()),
            output_domain=dict(normal=(0, 0, 1), offset=.1, keep_positive=True))
        result = execute_muscle_batch((request,), 'NATIVE').results[0]
        values = export('R', 'M', '', '', request, result, .5)
        self.assertEqual(set(values[0].parts), {0, 1})
        np.testing.assert_array_equal(values[0].own, result.inflated_vertices)

    def test_disabled_branch_is_absent_without_losing_main_provenance(self):
        from test_branched_surface import fixture
        from core.vcp.branched_surface import prepare_assembly
        from core.vcp.branched_numeric import BranchedMuscleRequest
        main, branch = fixture(); assembly = prepare_assembly(main, (branch,))
        spec = self.spec(); request = BranchedMuscleRequest('M', assembly, (spec, replace(spec, inflation_enabled=False)))
        result = execute_muscle_batch((request,), 'NATIVE').results[0]
        values = export('R', 'M', '', '', request, result, .5)
        self.assertEqual(set(values[0].parts), {0})
        self.assertLess(len(values[0].faces), len(result.faces)*2)
        self.assertEqual(len(np.unique(values[0].faces)), len(values[0].base))
