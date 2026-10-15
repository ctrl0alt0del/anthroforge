from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.unit.test_skin_gaps import capture
from core.draft_skin.gap_native import GapQueries
from core.draft_skin.gap_tiles import SkinTiles
from core.draft_skin.validation import validate_mesh
from core.draft_skin.mesh import orient_outward


def field_fixture(gap):
    h = .025; origin = np.array([-.2, -1.2, -1.2])
    shape = np.ceil((np.array([gap+.2, 1.2, 1.2])-origin)/h).astype(int)+1
    points = origin + np.moveaxis(np.indices(shape), 0, -1)*h
    x, y, z = np.moveaxis(points, -1, 0)
    field = np.minimum.reduce((x+.1, gap+.1-x, 1.05-np.abs(y), 1.05-np.abs(z)))
    return field, origin, h, (origin, shape, h)


def run_field(gap, first=(.1, 1), second=(.1, 1), y=0):
    value = capture(gap, first, second); field, origin, h, grid = field_fixture(gap)
    with GapQueries(value) as queries:
        with SkinTiles(queries, field, origin, h, grid, 4, .12, 256*1024**2) as tiles:
            return tiles.sample([[gap/2, y, 0]])[0]


class SkinTileTests(unittest.TestCase):
    def test_exterior_precision_does_not_treat_enclosed_voids_as_openings(self):
        from dataclasses import replace
        from tests.unit.test_draft_skin import cube_mesh
        from core.draft_skin.gap_tiles import exterior_precision
        value = capture(.22, (.01, 1), (.01, 1)); vertices, faces = cube_mesh()
        shell = replace(value.sources[0], source_index=2, vertices=vertices*6-3, triangles=faces)
        enclosed = replace(value, sources=(*value.sources, shell), lower=np.full(3, -3), upper=np.full(3, 3))
        origin = np.full(3, -3.2); h = .1; points = origin+np.moveaxis(np.indices((65, 65, 65)), 0, -1)*h
        field = 3.1-np.max(np.abs(points), axis=-1)
        with GapQueries(enclosed) as queries:
            self.assertEqual(exterior_precision(queries, field, origin, h, 4)[1], 0)
        field, origin, h, _ = field_fixture(.22)
        with GapQueries(value) as queries:
            self.assertAlmostEqual(exterior_precision(queries, field, origin, h, 4)[0], .22)

    def test_warm_validation_rejects_a_bridge_over_a_protected_gap(self):
        from dataclasses import replace
        from core.draft_skin.gap_warm import revalidate
        field, origin, h, grid = field_fixture(.22)
        with GapQueries(capture(.22)) as queries:
            with SkinTiles(queries, field, origin, h, grid, 4, .12, 256*1024**2) as tiles:
                vertices, faces = tiles.mesh()
        current = replace(capture(.22, (.1, 1), (.1, 1)), resolution=32)
        report, stats = revalidate(current, vertices, orient_outward(vertices, faces))
        self.assertFalse(report.valid)
        self.assertGreater(stats['protected_gap_violations'], 0)

    def test_precision_uses_original_opposing_geometry(self):
        from core.draft_skin.gap_tiles import precision
        with GapQueries(capture(.22, (.1, 1), (.1, 1))) as queries:
            width, count = precision(queries, 4)
        self.assertAlmostEqual(width, .22)
        self.assertGreater(count, 0)
        with GapQueries(capture(.18, (.1, 1), (.1, 1))) as queries:
            self.assertEqual(precision(queries, 4)[0], 0)

    def test_smoothed_mesh_covers_sources_and_preserves_gap(self):
        from core.draft_skin.gap_quality import validate
        field, origin, h, grid = field_fixture(.22)
        with GapQueries(capture(.22, (.1, 1), (.1, 1))) as queries:
            with SkinTiles(queries, field, origin, h, grid, 4, .12, 256*1024**2) as tiles:
                vertices, faces = tiles.mesh(); vertices = tiles.smooth(vertices, faces, 2)
                stats = tiles.validation(vertices, faces)
        report, _ = validate(vertices, orient_outward(vertices, faces))
        self.assertTrue(report.valid, report.message)
        self.assertEqual((stats['source_vertices_outside'], stats['source_triangles_crossed'], stats['protected_gap_violations']), (0, 0, 0))
        self.assertGreater(stats['protected_gap_checks'], 0)

    def test_final_validation_detects_moved_mesh(self):
        field, origin, h, grid = field_fixture(.22)
        with GapQueries(capture(.22, (.1, 1), (.1, 1))) as queries:
            with SkinTiles(queries, field, origin, h, grid, 4, .12, 256*1024**2) as tiles:
                vertices, faces = tiles.mesh()
                stats = tiles.validation(vertices + [3, 0, 0], faces)
        self.assertGreater(stats['source_vertices_outside'], 0)

    def test_empty_island_removal_keeps_both_supported_components(self):
        from core.draft_skin.gap_quality import supported_components, validate
        field, origin, h, grid = field_fixture(.22)
        with GapQueries(capture(.22, (.1, 1), (.1, 1))) as queries:
            with SkinTiles(queries, field, origin, h, grid, 4, .12, 256*1024**2) as tiles:
                vertices, faces = tiles.mesh()
            faces = np.vstack((faces, [len(vertices), len(vertices)+1, len(vertices)+2]))
            vertices = np.vstack((vertices, [[10, 10, 10], [10.1, 10, 10], [10, 10.1, 10]]))
            vertices, faces, removed = supported_components(vertices, faces, queries)
        report, stats = validate(vertices, orient_outward(vertices, faces))
        self.assertEqual((removed, stats['components']), (1, 2))
        self.assertTrue(report.valid, report.message)

    def test_below_at_and_above_limit(self):
        self.assertGreater(run_field(.18), 0)
        self.assertGreater(run_field(.2), 0)
        self.assertLess(run_field(.22), 0)

    def test_zero_half_and_full_strength(self):
        values = [run_field(.18, (.1, strength), y=1.02) for strength in (0, .5, 1)]
        self.assertLess(values[0], values[1])
        self.assertLess(values[1], values[2])
        self.assertLess(values[0], 0)

    def test_stricter_neighbor_and_zero_limit(self):
        self.assertLess(run_field(.18, (.2, 1), (.01, 1)), 0)
        self.assertLess(run_field(.18, (0, 1)), 0)
        self.assertLess(run_field(.22, (.1, .5)), 0)

    def test_memory_limit_fails_explicitly(self):
        field, origin, h, grid = field_fixture(.22)
        with GapQueries(capture(.22)) as queries:
            with self.assertRaisesRegex(RuntimeError, "memory budget"):
                SkinTiles(queries, field, origin, h, grid, 4, .12, 1024)

    def test_native_cancellation_releases_failed_job(self):
        field, origin, h, grid = field_fixture(.22)
        with GapQueries(capture(.22)) as queries:
            from core.draft_skin.gap_tiles import _configure
            _configure(queries.lib); queries.lib.af_skin_gap_cancel(queries.handle)
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                SkinTiles(queries, field, origin, h, grid, 4, .12, 256*1024**2)

    def test_tile_boundaries_have_watertight_consistent_mesh(self):
        field, origin, h, grid = field_fixture(.18)
        with GapQueries(capture(.18)) as queries:
            with SkinTiles(queries, field, origin, h, grid, 4, .12, 256*1024**2) as tiles:
                vertices, faces = tiles.mesh()
        validation = validate_mesh(vertices, orient_outward(vertices, faces))
        self.assertTrue(validation.valid, validation.message)


if __name__ == '__main__':
    unittest.main()
