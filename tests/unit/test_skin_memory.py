"""Memory limits and deterministic fields across native thread counts."""
import unittest
import numpy as np
from core.draft_skin.gap_native import GapQueries
from core.draft_skin.gap_tiles import SkinTiles
from tests.unit.test_skin_gaps import capture
from tests.unit.test_skin_tiles import field_fixture


def measured_field(queries, budget, threads):
    queries.lib.af_fiber_set_worker_threads(threads)
    field, origin, h, grid = field_fixture(.22)
    with SkinTiles(queries, field, origin, h, grid, 4, .12, budget) as tiles:
        points = np.array([[.11, 0, 0], [0, 0, 0], [.22, .99, .99]])
        return tiles.sample(points), tiles.statistics(), tiles.mesh()


class SkinMemoryTests(unittest.TestCase):
    def test_incompatible_compact_library_is_rejected(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from core.draft_skin.gap_native import _load_library
        old = SimpleNamespace(af_skin_gap_version=lambda: 3)
        with patch('core.vcp.v2.collision_native.load_native', return_value=old):
            with self.assertRaisesRegex(RuntimeError, 'compact field v1'):
                _load_library()

    def test_thread_count_preserves_surface_and_gap(self):
        with GapQueries(capture(.22, (.1, 1), (.1, 1))) as queries:
            previous = queries.lib.af_fiber_worker_threads()
            try:
                first = measured_field(queries, 32*1024**2, 1)
                second = measured_field(queries, 32*1024**2, 4)
            finally:
                queries.lib.af_fiber_set_worker_threads(previous)
        np.testing.assert_array_equal(first[0], second[0])
        for a, b in zip(first[2], second[2]):
            np.testing.assert_array_equal(a, b)
        self.assertLess(first[0][0], 0)

    def test_failed_allocation_does_not_poison_next_job(self):
        with GapQueries(capture(.22)) as queries:
            with self.assertRaisesRegex(RuntimeError, 'memory budget'):
                measured_field(queries, 2*1024**2, 4)
            _, stats, _ = measured_field(queries, 32*1024**2, 4)
        self.assertLessEqual(stats['estimated_peak_native_bytes'], 32*1024**2)
        self.assertLessEqual(stats['resident_field_bytes'], stats['allocated_samples']*4)
        self.assertGreaterEqual(stats['propagation_tiles'], stats['initial_tiles'])

    def test_uniform_interior_is_stored_compactly(self):
        from dataclasses import replace
        from tests.unit.test_draft_skin import cube_mesh
        vertices, faces = cube_mesh(); value = capture()
        source = replace(value.sources[0], vertices=vertices*2-1, triangles=faces)
        value = replace(value, sources=(source,), lower=np.full(3, -1), upper=np.full(3, 1))
        origin = np.full(3, -1.6); h = .025; shape = np.full(3, 129)
        points = origin+np.moveaxis(np.indices(shape), 0, -1)*h
        field = 1.2-np.max(np.abs(points), axis=-1)
        with GapQueries(value) as queries:
            with SkinTiles(queries, field, origin, h, (origin, shape, h), 4, .2, 32*1024**2) as tiles:
                stats = tiles.statistics(); self.assertGreater(tiles.sample([[0, 0, 0]])[0], 0)
        self.assertLess(stats['resident_field_bytes'], stats['allocated_samples']*4)


if __name__ == '__main__':
    unittest.main()
