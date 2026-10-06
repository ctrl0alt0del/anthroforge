from dataclasses import replace
import unittest
import numpy as np
from test_muscle_stacking import inflated
from test_muscle_pairs_fields import evaluate
import test_muscle_pairs_fields as fields
from stack_fixture_adapter import solve
from core.muscle_stacking.material import boundary_pins
from core.muscle_stacking.obstacles import Obstacle


def box(low, high):
    points = np.array([[x, y, z] for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])])
    faces = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1],
        [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]], dtype=np.int64)
    return Obstacle(points, faces)


class StackingMaterialTests(unittest.TestCase):
    def test_strided_triangle_input_boundary_pins(self):
        domain = inflated('a', 0, .1)
        pins = boundary_pins(domain.faces[:, ::-1], len(domain.base))
        self.assertEqual(set(pins), set(range(9))-{4})

    def test_crop_interpolation_is_exact_without_new_border_pins(self):
        _, result, domains = evaluate(fields.FieldTests().spec(), output_domain=dict(normal=(1, 0, 0), offset=.43, keep_positive=True))
        d = domains[0]; m = d.material
        reconstructed = (m.vertices[m.interpolation]*m.weights[:, :, None]).sum(axis=1)
        np.testing.assert_allclose(reconstructed, d.base, atol=1e-12)
        cut = np.isclose(d.base[:, 0], .43)
        self.assertTrue(cut.any())
        fixed = np.isin(m.interpolation, m.fixed) | (m.weights == 0)
        self.assertTrue(np.any(cut & ~fixed.all(axis=1)))

    def test_welded_branch_interface_is_not_pinned(self):
        from test_branched_surface import fixture
        from core.vcp.branched_surface import prepare_assembly, assemble
        from core.muscle_pairs.field import triangles
        main, branch = fixture(); assembly = prepare_assembly(main, (branch,)); vertices, faces = assemble(assembly)
        tri, _, _ = triangles(faces, np.zeros(len(faces)), np.arange(len(faces)))
        pins = boundary_pins(tri, len(vertices))
        seam = (len(assembly.main)-1)*assembly.main.shape[1]+assembly.branches[0].seam
        self.assertTrue(set(seam[1:-1]).isdisjoint(pins))
        self.assertTrue({int(seam[0]), int(seam[-1])}.issubset(pins))

    def test_interior_protected_constraint_is_preserved(self):
        a, b = inflated('under', 0, .3), inflated('cover', .1, .2)
        b = replace(b, material=replace(b.material, fixed=np.array([4], dtype=np.int64)))
        report, out = solve([a, b]); self.assertEqual(report['stacking']['status'], 'incomplete')
        np.testing.assert_array_equal(out['cover'], b.own)

    def test_new_bone_penetration_rejects_and_restores_own(self):
        a, b = inflated('under', 0, .3), inflated('cover', .1, .2)
        # The retained-thickness final surface is z=.4; place the obstacle across it.
        bone = box((-.25, -.25, .35), (.25, .25, .45))
        report, out = solve([replace(a, obstacles=(bone,)), replace(b, obstacles=(bone,))])
        self.assertEqual(report['stacking']['status'], 'incomplete')
        self.assertIn('BONE', str(report['stacking']['domains']))
        np.testing.assert_array_equal(out['cover'], b.own)

    def test_each_inflation_law_keeps_own_and_native_material(self):
        for mode in ('DISTRIBUTED', 'CTRL_POINT', 'SECTION_PROFILE'):
            _, result, domains = evaluate(fields.FieldTests().spec(mode))
            report, out = solve(domains)
            self.assertEqual(report['stacking']['status'], 'complete')
            np.testing.assert_array_equal(out['M'], result.inflated_vertices)
