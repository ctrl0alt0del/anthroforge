import unittest
from dataclasses import replace
import numpy as np
from test_muscle_numeric_backends import _spec
from core.vcp.branched_surface import BranchInput, prepare_assembly, assemble
from core.vcp.prepared_inflation import inflate_assembly, boundary_masks


def fixture():
    z = np.linspace(-2., 2., 17)
    main = tuple(np.column_stack((np.full(17, x), np.zeros(17), z)) for x in (-1., 1.))
    roots = (4, 8, 12)
    children = tuple(np.linspace(main[-1][i], main[-1][i]+[1., 2., .2], 9) for i in roots)
    return prepare_assembly(main, (BranchInput('branch', -1, roots, children),))


class BranchedInflationTests(unittest.TestCase):
    def test_prepared_native_python_parity_and_fixed_exterior(self):
        assembly = fixture()
        for mode in ('DISTRIBUTED', 'CTRL_POINT'):
            specs = (_spec(mode), _spec('CTRL_POINT', inflation_max_value=.3))
            python = inflate_assembly(assembly, specs, 'PYTHON')
            native = inflate_assembly(assembly, specs, 'NATIVE')
            a, _ = assemble(assembly, *python); b, _ = assemble(assembly, *native)
            np.testing.assert_allclose(a, b, atol=1e-6)
            for original, result, mask in zip((assembly.main, assembly.branches[0].grid),
                                              (native[0], native[1][0]), boundary_masks(assembly)):
                np.testing.assert_array_equal(original[mask], result[mask])

    def test_distributed_flip_changes_inflation_direction(self):
        assembly = fixture(); specs = (_spec('DISTRIBUTED'),)*2
        normal = inflate_assembly(assembly, specs, 'NATIVE')
        reversed_result = inflate_assembly(replace(assembly, flip=True), specs, 'NATIVE')
        delta = normal[0][4, 8]-assembly.main[4, 8]
        reverse = reversed_result[0][4, 8]-assembly.main[4, 8]
        self.assertGreater(np.linalg.norm(delta), .01)
        np.testing.assert_allclose(reverse, -delta, atol=1e-10)
