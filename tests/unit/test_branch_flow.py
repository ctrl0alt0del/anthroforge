import unittest
from types import SimpleNamespace
import numpy as np
from core.vcp.branched_surface import BranchInput, prepare_assembly, assemble
from core.topology.flow_patches import branch_grids, grid_samples


def fixture(flip=False):
    main = [np.array([[x, y, 0.] for x in range(5)]) for y in (0., 1., 2.)]
    rows = tuple(np.array([[x, y, 0.] for y in (2., 3., 4.)]) for x in (1., 2., 3.))
    assembly = prepare_assembly(main, (BranchInput('branch', -1, (1, 2, 3), rows),), flip)
    base, faces = assemble(assembly)
    result = SimpleNamespace(error='', faces=faces, inflated_vertices=base + [0., 0., .25])
    return assembly, result


class BranchFlowTests(unittest.TestCase):
    def test_shared_seam_identity_and_evaluated_positions(self):
        assembly, result = fixture(); patches = branch_grids(assembly, result)
        main, child = patches[0][1], patches[1][1]; seam = assembly.branches[0].seam
        np.testing.assert_array_equal(main[-1, seam], child[:, 0])
        self.assertTrue(np.all(child[:, :, 2] == .25))
        self.assertEqual(patches[1][3]['parent_samples'], seam.tolist())

    def test_branch_normal_orientation_and_axis_exchange(self):
        for flip in (False, True):
            patches = branch_grids(*fixture(flip))
            a, b = [grid_samples(g, i, f) for i, (_,g,f,_) in enumerate(patches)]
            self.assertGreater(np.dot(a[0,6:9], b[0,6:9]), .999)
            self.assertAlmostEqual(np.dot(a[0,3:6], b[0,3:6]), 0.)
            self.assertEqual(set(b[:,9]), {1.})

    def test_invalid_connectivity_is_not_silently_reinterpreted(self):
        assembly, result = fixture(); result.faces = result.faces[::-1]
        with self.assertRaisesRegex(ValueError, 'connectivity'): branch_grids(assembly, result)

    def test_degenerate_samples_are_excluded(self):
        self.assertEqual(len(grid_samples(np.zeros((5,5,3)), 0)), 0)

    def test_patch_metadata_survives_capture_and_changes_hash(self):
        import tempfile
        from pathlib import Path
        from core.topology.model import TopologyCapture, TopologySettings
        from core.topology.protocol import write_capture, read_capture, capture_hash
        v=np.eye(3); f=np.array([[0,1,2]]); regions=({'owner':0,'patch':'branch','seam':{'parent_samples':[1,2]}},)
        settings=TopologySettings(symmetry_mode='NONE')
        h=capture_hash('root',v,f,(),settings,None,regions=regions)
        self.assertNotEqual(h,capture_hash('root',v,f,(),settings,None))
        capture=TopologyCapture('root',v,f,(),v.min(0),v.max(0),h,settings,flow_regions=regions)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'capture.npz'; write_capture(path,capture)
            self.assertEqual(read_capture(path).flow_regions,regions)


if __name__ == '__main__': unittest.main()
