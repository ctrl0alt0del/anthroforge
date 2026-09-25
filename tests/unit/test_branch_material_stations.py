import unittest
from dataclasses import replace
import numpy as np
from core.vcp.branched_surface import prepare_assembly
from tests.unit.test_branched_surface import fixture


class BranchMaterialStationTests(unittest.TestCase):
    def test_authored_sections_survive_unequal_curve_lengths(self):
        main, branch = fixture(count=2)
        main[0][:, 1] = np.sin(np.linspace(0, np.pi, 17))*3
        stations = tuple(np.linspace(0, 1, len(r)) for r in main)
        prepared = prepare_assembly(main, (branch,), main_stations=stations)
        np.testing.assert_allclose(prepared.main[0], main[0])
        np.testing.assert_allclose(prepared.main[-1], main[-1])
        np.testing.assert_array_equal(prepared.branches[0].grid[:, 0], prepared.main[-1, prepared.branches[0].seam])
        legacy = prepare_assembly(main, (branch,))
        self.assertGreater(len(legacy.along), len(prepared.along))

    def test_child_material_samples_and_invalid_stations(self):
        main, branch = fixture(count=2)
        branch.fibers[0][:, 0] += np.sin(np.linspace(0, np.pi, 9))*2
        branch = replace(branch, stations=tuple(np.linspace(0, 1, 9) for _ in branch.fibers))
        prepared = prepare_assembly(main, (branch,))
        child = prepared.branches[0]
        np.testing.assert_allclose(child.grid[0, ::2], branch.fibers[0])
        with self.assertRaisesRegex(ValueError, 'CORRESPONDENCE_STATIONS'):
            prepare_assembly(main, (replace(branch, stations=([0]*9, [0]*9)),))
