import unittest
from dataclasses import replace
import numpy as np
from core.vcp.branched_surface import BranchInput, prepare_assembly, assemble
from core.vcp.branch_connector import connect


def fixture(side=-1, count=3):
    z = np.linspace(-2., 2., 17)
    main = tuple(np.column_stack((np.full(17, x), np.zeros(17), z)) for x in (-1., 1.))
    roots = (4, 8, 12) if count == 3 else (4, 12)
    children = tuple(np.linspace(main[side][i], main[side][i]+[0., 2., .3], 9) for i in roots)
    return main, BranchInput('branch', side, roots, children)


class BranchedSurfaceTests(unittest.TestCase):
    def test_float32_shared_root_roundoff_welds_but_real_mismatch_rejects(self):
        main, branch = fixture(count=2)
        fibers = tuple(np.array(row, copy=True) for row in branch.fibers)
        fibers[0][0, 0] = float(np.nextafter(np.float32(fibers[0][0, 0]), np.float32(2.)))
        prepared = prepare_assembly(main, (replace(branch, fibers=fibers),))
        np.testing.assert_array_equal(prepared.branches[0].grid[:, 0], prepared.main[-1, prepared.branches[0].seam])
        fibers[0][0, 0] += .001
        with self.assertRaisesRegex(ValueError, 'shared solved'):
            prepare_assembly(main, (replace(branch, fibers=fibers),))

    def test_multiple_disjoint_branches_on_both_sides(self):
        main, branch = fixture(count=2)
        configurations = ((0, (2, 5)), (0, (9, 14)), (-1, (4, 12)))
        branches = tuple(replace(branch, id=str(i), boundary=side, roots=roots,
            fibers=tuple(np.linspace(main[side][r], main[side][r]+[0, 2, 0], 9) for r in roots))
            for i, (side, roots) in enumerate(configurations))
        prepared = prepare_assembly(main, branches)
        inflated = connect(prepared, prepared.main, tuple(b.grid for b in prepared.branches))
        vertices, faces = assemble(prepared, *inflated)
        self.assertEqual(len(prepared.branches), 3)
        self.assertTrue(np.isfinite(vertices).all())
        self.assertEqual(len(faces.shape), 2)

    def test_exact_weld_and_oriented_manifold_edges_both_sides(self):
        for side in (0, -1):
            main, branch = fixture(side)
            prepared = prepare_assembly(main, (branch,))
            vertices, faces = assemble(prepared)
            edges = {}
            for face in faces:
                for a, b in zip(face, np.roll(face, -1)):
                    edges.setdefault(tuple(sorted((a, b))), []).append((a, b))
            self.assertTrue(all(len(e) <= 2 for e in edges.values()))
            self.assertTrue(all(e[0] == e[1][::-1] for e in edges.values() if len(e) == 2))
            self.assertTrue(np.isfinite(vertices).all())

    def test_curved_root_and_middle_branch_fiber_are_preserved(self):
        main, branch = fixture()
        main[-1][:, 1] = .2*np.sin(np.linspace(0, np.pi, 17))
        children = tuple(np.linspace(main[-1][i], main[-1][i]+[0, 2, 0], 9) for i in branch.roots)
        prepared = prepare_assembly(main, (replace(branch, fibers=children),))
        b = prepared.branches[0]
        np.testing.assert_array_equal(b.grid[:, 0], prepared.main[-1, b.seam])
        middle = np.argmin(abs(b.across-.5))
        np.testing.assert_allclose(b.grid[middle, -1], children[1][-1])

    def test_overlap_and_endpoint_roots_rejected(self):
        main, branch = fixture()
        with self.assertRaisesRegex(ValueError, 'overlap'):
            prepare_assembly(main, (branch, replace(branch, id='other')))
        with self.assertRaisesRegex(ValueError, 'inside'):
            prepare_assembly(main, (replace(branch, roots=(0, 8, 12)),))

    def test_fullness_orientation_and_fixed_ends(self):
        main, branch = fixture(count=2)
        base = prepare_assembly(main, (replace(branch, fullness=.1),))
        out = connect(base, base.main, (base.branches[0].grid,))
        flipped = connect(replace(base, flip=True), base.main, (base.branches[0].grid,))
        zero = replace(base, branches=(replace(base.branches[0], connection=branch),))
        flat = connect(zero, base.main, (base.branches[0].grid,))
        np.testing.assert_allclose(out[0]+flipped[0], 2*flat[0], atol=1e-12)
        np.testing.assert_array_equal(out[1][0][[0, -1]], base.branches[0].grid[[0, -1]])
        assemble(base, *out)
