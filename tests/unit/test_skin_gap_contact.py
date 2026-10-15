"""Contact is allowed; solid material at a protected sample is still rejected."""
import unittest
from unittest.mock import patch
import numpy as np
from tests.unit.test_draft_skin import cube_mesh
from tests.unit.test_skin_gaps import capture
from tests.unit.test_skin_tiles import field_fixture
from core.draft_skin.gap_native import GapQueries
from core.draft_skin.gap_tiles import SkinTiles
from core.draft_skin.gap_quality import validate_gap_points, validate


def box(low, high):
    vertices, faces = cube_mesh()
    return vertices*(np.asarray(high)-low)+low, faces


def opposing_boxes(gap):
    a, f = box(np.array([-.1, -1.1, -1.1]), [.11-gap/2, 1.1, 1.1])
    b, g = box(np.array([.11+gap/2, -1.1, -1.1]), [.32, 1.1, 1.1])
    return np.vstack((a, b)), np.vstack((f, g+len(a)))


class SkinGapContactTests(unittest.TestCase):
    def test_arbitrarily_small_air_gap_and_exact_contact(self):
        for width in (.04, .002, 1e-9, 0):
            vertices, faces = opposing_boxes(width)
            rows = validate_gap_points(vertices, faces, [[.11, .2, .1]])
            self.assertEqual(rows[0, 1], 0, (width, rows))
            self.assertAlmostEqual(rows[0, 0], width/2)
            report, stats = validate(vertices, faces)
            self.assertTrue(report.valid, report.message)
            self.assertEqual(stats['components'], 2)

    def test_solid_bridge_is_rejected(self):
        vertices, faces = box(np.array([-.1, -1.1, -1.1]), [.32, 1.1, 1.1])
        self.assertEqual(validate_gap_points(vertices, faces, [[.11, .2, .1]])[0, 1], 1)

    def test_scale_translation_and_numerical_boundary(self):
        vertices, faces = box(np.zeros(3), np.ones(3))
        points = np.array([[0, .2, .3], [1e-3, .2, .3], [-1e-9, .2, .3]])
        for scale, offset in ((1e-4, 0), (1, 0), (1e4, 0), (1, 100)):
            rows = validate_gap_points(vertices*scale+offset, faces, points*scale+offset)
            np.testing.assert_array_equal(rows[:, 1], [0, 1, 0])
            self.assertLess(rows[:, 2].max(), 1e-3*scale)

    def test_tiled_validator_accepts_contact_and_small_gap(self):
        field, origin, h, grid = field_fixture(.22)
        with GapQueries(capture(.22, (.1, 1), (.1, 1))) as queries:
            with SkinTiles(queries, field, origin, h, grid, 4, .12, 256*1024**2) as tiles:
                for width in (0, .002):
                    stats = tiles.validation(*opposing_boxes(width))
                    self.assertGreater(stats['protected_gap_checks'], 0)
                    self.assertEqual(stats['protected_gap_violations'], 0, stats)
                    self.assertEqual(stats['source_vertices_outside'], 0)
                    self.assertEqual(stats['source_triangles_crossed'], 0)
                    self.assertEqual(stats['gap_validation_policy'], 'contact-permitted-v2')
                    self.assertAlmostEqual(stats['minimum_gap_clearance'], width/2)

    def test_warm_validator_accepts_contact(self):
        from dataclasses import replace
        from core.draft_skin.gap_warm import revalidate
        value = replace(capture(.22, (.1, 1), (.1, 1)), resolution=32)
        report, stats = revalidate(value, *opposing_boxes(0))
        self.assertTrue(report.valid, (report.message, stats))
        self.assertEqual(stats['protected_gap_violations'], 0)
        self.assertTrue(stats['gaps_revalidated'])

    def test_old_native_capability_is_rejected(self):
        from types import SimpleNamespace
        from core.draft_skin import gap_native
        old = SimpleNamespace(af_skin_gap_version=lambda: 3, af_skin_tiles_memory_version=lambda: 1)
        with patch('core.vcp.v2.collision_native.load_native', return_value=old):
            with self.assertRaisesRegex(RuntimeError, 'contact validation v2'):
                gap_native._load_library()

    def test_legacy_gap_signature_requires_regeneration(self):
        import hashlib
        import json
        from core.draft_skin.gap_settings import effective_gap, gap_signature
        from core.warm_start.invalidation import WarmChangeState, classify_change
        value = capture()
        rows = [(s.entity_type, s.entity_id, s.mirror_role, *effective_gap(s, value.settings)) for s in value.sources]
        legacy = (1, value.settings.gap_limit_ratio, value.settings.gap_strength, rows)
        old = hashlib.sha256(json.dumps(legacy, sort_keys=True).encode()).hexdigest()
        current = gap_signature(value)
        self.assertNotEqual(old, current)
        self.assertTrue(classify_change(WarmChangeState(gap_settings=old), WarmChangeState(gap_settings=current)).skin_rebuild)
        self.assertTrue(classify_change(WarmChangeState(), WarmChangeState(gap_settings=current)).skin_rebuild)


if __name__ == '__main__':
    unittest.main()
