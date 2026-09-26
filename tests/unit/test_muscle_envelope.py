"""Native bidirectional profiles, material topology and compatibility fixtures."""
from dataclasses import replace
import unittest
import numpy as np
from core.vcp.muscle_envelope_native import section, compose
from core.vcp.muscle_section_profile import SectionProfileSpec, apply_profile
from core.vcp.muscle_numeric import make_muscle_request, execute_muscle_batch
from core.vcp.muscle_envelope import MuscleEnvelopeSpec
from test_muscle_numeric_native import _spec


def grid():
    x, y = np.meshgrid(np.linspace(0, 1, 17), np.linspace(0, 1, 11))
    return np.stack((x, y, .05*np.sin(x*3)*y), axis=2)


class EnvelopeTests(unittest.TestCase):
    def test_section_native_parity_and_opposite_side(self):
        for direction in ('LOCAL', 'SMOOTH', 'SECTION'):
            p = SectionProfileSpec(direction=direction)
            a, b = section(grid(), p, 1), section(grid(), p, -1)
            np.testing.assert_allclose(a, apply_profile(grid(), p), atol=1e-14)
            np.testing.assert_allclose(a+b, 2*grid(), atol=1e-14)

    def test_mixed_laws_leave_primary_unchanged(self):
        spec = replace(_spec(inflation_mode='DISTRIBUTED', inflation_enabled=True), densify=False, target_count=17)
        request = make_muscle_request('M', grid(), spec)
        old = execute_muscle_batch((request,)).results[0]
        secondary = replace(spec, inflation_mode='SECTION_PROFILE', section_profile=SectionProfileSpec())
        result = execute_muscle_batch((replace(request, envelope=MuscleEnvelopeSpec((secondary,))),)).results[0]
        self.assertEqual(result.error, ''); np.testing.assert_array_equal(result.side_a, old.inflated_vertices)
        self.assertEqual(len(result.inflated_faces), 2*len(result.faces))
        np.testing.assert_array_equal(result.base_vertices, old.base_vertices)

    def test_zero_sides_display_once(self):
        points = np.array(((0., 0, 0), (1., 0, 0), (1., 1, 0), (0., 1, 0)))
        vertices, faces, sources, sides = compose(points, points, [[0, 1, 2, 3]])
        self.assertEqual(len(faces), 1); self.assertEqual(sides.tolist(), [0])
        np.testing.assert_array_equal(vertices, points)

    def test_reject_closed_domain_and_future_version(self):
        spec = _spec(inflation_mode='DISTRIBUTED', inflation_enabled=True); request = make_muscle_request('M', grid(), spec)
        for envelope in (MuscleEnvelopeSpec((spec,), version=9), MuscleEnvelopeSpec((replace(spec, closed_u=True),))):
            result = execute_muscle_batch((replace(request, envelope=envelope),)).results[0]
            self.assertTrue(result.error.startswith('ENVELOPE_'))

    def test_cropped_sides_share_material_mapping(self):
        spec = replace(_spec(inflation_mode='DISTRIBUTED', inflation_enabled=True), densify=False, target_count=17)
        request = make_muscle_request('M', grid(), spec, output_domain=dict(normal=(1, 0, 0), offset=.5, keep_positive=True))
        result = execute_muscle_batch((replace(request, envelope=MuscleEnvelopeSpec((spec,))),)).results[0]
        self.assertEqual(result.error, ''); self.assertEqual(result.side_a.shape, result.side_b.shape)
        self.assertTrue(np.all(result.base_vertices[:, 0] >= .5-1e-10))

    def test_secondary_edit_reuses_primary_and_prepared_base(self):
        from unittest.mock import patch
        from core.vcp import muscle_envelope as engine
        from core.vcp.muscle_profile_cache import clear_profile_cache
        spec = replace(_spec(inflation_mode='DISTRIBUTED', inflation_enabled=True), densify=False, target_count=17)
        request = replace(make_muscle_request('M', grid(), spec), envelope=MuscleEnvelopeSpec((spec,)))
        clear_profile_cache()
        with patch.object(engine, '_side_uncached', wraps=engine._side_uncached) as evaluate:
            a = engine.evaluate(request); self.assertEqual(evaluate.call_count, 2)
            b = engine.evaluate(replace(request, envelope=MuscleEnvelopeSpec((replace(spec, inflation_max_value=.13),))))
            self.assertEqual(evaluate.call_count, 3)
        np.testing.assert_array_equal(a.side_a, b.side_a); np.testing.assert_array_equal(a.base_vertices, b.base_vertices)

    def test_control_point_matches_independent_signed_evaluations(self):
        for falloff in ('GAUSSIAN', 'LINEAR', 'SMOOTHSTEP'):
            spec = replace(_spec(inflation_mode='CTRL_POINT', inflation_enabled=True), densify=False, target_count=17,
                           control_world=(.3,.6,.02), inflation_falloff_type=falloff)
            request = make_muscle_request('M', grid(), spec)
            value = execute_muscle_batch((replace(request, envelope=MuscleEnvelopeSpec((spec,))),)).results[0]
            for sign, side in ((False, value.side_a), (True, value.side_b)):
                independent = execute_muscle_batch((replace(request, spec=replace(spec, flip_normals=sign)),)).results[0]
                np.testing.assert_allclose(side, independent.inflated_vertices, atol=1e-12)

    def test_section_reflection_preserves_material_identity(self):
        p = SectionProfileSpec(direction='SMOOTH')
        reflection = np.diag([-1.,1.,1.]); first = section(grid(), p, 1)
        mirrored = section(grid()@reflection, p, -1)
        np.testing.assert_allclose(mirrored, first@reflection, atol=1e-14)

    def test_two_disjoint_branches_share_topology_on_each_side(self):
        from core.vcp.branched_numeric import BranchedMuscleRequest
        from core.vcp.branched_surface import BranchInput, prepare_assembly, assemble
        rows = tuple(np.column_stack((np.full(33,x),np.zeros(33),np.linspace(-2,2,33))) for x in (-1.,0.,1.))
        branch = lambda key, roots: BranchInput(key,-1,roots,tuple(np.linspace(rows[-1][i],rows[-1][i]+[1.,1.,0],17) for i in roots))
        assembly = prepare_assembly(rows, (branch('proximal',(4,8)), branch('distal',(20,24))))
        specs = (replace(_spec(inflation_mode='DISTRIBUTED', inflation_enabled=True), inflation_max_value=.1),)*3
        result = execute_muscle_batch((BranchedMuscleRequest('M',assembly,specs,envelope=MuscleEnvelopeSpec(specs)),)).results[0]
        self.assertEqual(result.error, ''); self.assertEqual(set(result.inflated_parts), {0,1,2})
        self.assertEqual(result.diagnostics['nonmanifold_edges'], 0)
        np.testing.assert_array_equal(result.faces, assemble(assembly)[1])
        self.assertTrue(np.isfinite(result.inflated_vertices).all())


if __name__ == '__main__': unittest.main()
