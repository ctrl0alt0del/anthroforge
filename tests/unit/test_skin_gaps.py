from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.draft_skin.model import SkinCapture, SkinSource, SkinSolverSettings
from core.draft_skin.gap_settings import effective_gap, record_gap, gap_signature
from core.draft_skin.gap_native import GapQueries
from core.draft_skin.protocol import capture_hash, read_capture, write_capture
from core.warm_start.invalidation import WarmChangeState, classify_change


def plane(index, x, limit, strength, reverse=False):
    vertices = np.array([(x, -1, -1), (x, 1, -1), (x, 1, 1), (x, -1, 1)], dtype=float)
    faces = np.array([(0, 1, 2), (0, 2, 3)], dtype=np.int32)
    if reverse:
        faces = faces[:, ::-1].copy()
    return SkinSource(index, "SCP", str(index), "ORIGINAL", str(index), vertices, faces,
                      gap_limit_ratio=limit, gap_strength=strength)


def capture(gap=0.4, first=(0.5, 1.0), second=(0.5, 1.0), reverse=False):
    sources = (plane(0, 0, *first), plane(1, gap, *second, reverse))
    return SkinCapture("ROOT", sources, np.array([0, -1, -1.]), np.array([gap, 1, 1.]), "", 0.01)


class GapSettingsTests(unittest.TestCase):
    def test_defaults_and_inherited_overrides(self):
        settings = SkinSolverSettings()
        self.assertEqual(record_gap(None, settings), (0.005, 1.0))
        record = SimpleNamespace(skin_gap_mode="OVERRIDE", skin_gap_limit_percent=0.2, skin_gap_strength_percent=25)
        self.assertEqual(record_gap(record, settings), (0.002, 0.25))
        inherited = replace(capture().sources[0], gap_limit_ratio=-1, gap_strength=-1)
        self.assertEqual(effective_gap(inherited, settings), (0.005, 1.0))

    def test_invalid_settings_rejected(self):
        source = capture().sources[0]
        for kwargs in ({"gap_limit_ratio": np.nan}, {"gap_strength": 1.1}, {"gap_strength": np.inf}):
            with self.assertRaises(ValueError):
                effective_gap(replace(source, **kwargs), SkinSolverSettings())

    def test_round_trip_and_policy_hash(self):
        value = capture()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "capture.npz"
            write_capture(path, value)
            loaded = read_capture(path)
        self.assertEqual(effective_gap(loaded.sources[0], loaded.settings), (0.5, 1.0))
        changed = replace(value, sources=(replace(value.sources[0], gap_strength=0.5), value.sources[1]))
        self.assertNotEqual(gap_signature(value), gap_signature(changed))
        self.assertNotEqual(capture_hash("ROOT", value.sources), capture_hash("ROOT", changed.sources))

    def test_any_policy_change_invalidates_and_legacy_rebuilds(self):
        for previous, current in (("", "new"), ("old", "new")):
            result = classify_change(WarmChangeState(gap_settings=previous), WarmChangeState(gap_settings=current))
            self.assertTrue(result.skin_rebuild)


class NativeGapTests(unittest.TestCase):
    def test_incompatible_native_package_is_rejected_without_fallback(self):
        from unittest import mock
        from core.draft_skin import gap_native
        for result in (SimpleNamespace(af_skin_gap_version=lambda: 2), OSError('missing library')):
            options = {'side_effect': result} if isinstance(result, Exception) else {'return_value': result}
            with mock.patch.object(gap_native, '_LIBRARY', None):
                with mock.patch('core.vcp.v2.collision_native.load_native', **options):
                    with self.assertRaisesRegex(RuntimeError, 'Previous output retained'):
                        gap_native.library()

    def test_source_coverage_ignores_vertices_unused_by_surface_triangles(self):
        from tests.unit.test_draft_skin import cube_mesh
        from core.draft_skin.gap_quality import source_coverage
        vertices, faces = cube_mesh()
        original = np.insert(vertices, 4, [100, 100, 100], axis=0)
        indexed = np.where(faces >= 4, faces+1, faces)
        source = SkinSource(0, 'SCP', 'cube', 'ORIGINAL', 'cube', original, indexed)
        value = replace(capture(), sources=(source,))
        with GapQueries(value) as queries:
            stats = source_coverage(vertices*1.2-.1, faces, queries, 1.e-6)
        self.assertEqual(stats['source_vertices_outside'], 0)
        self.assertEqual(stats['source_vertices_checked'], 8)

    def test_invalid_query_arrays_rejected_before_native_call(self):
        with GapQueries(capture()) as queries:
            for points in ([[0, 0]], [[np.nan, 0, 0]], [0, 0, 0]):
                with self.assertRaises(ValueError):
                    queries.sample(points, 4)

    def test_native_binding_retains_noncontiguous_source_identifiers(self):
        from core.draft_skin.gap_bindings import bind
        value = capture()
        value = replace(value, sources=tuple(replace(s, source_index=10+i*7) for i, s in enumerate(value.sources)))
        with GapQueries(value) as queries:
            binding, quality = bind([[0.15, 0, 0], [0.25, 0, 0]], queries)
        self.assertEqual(set(binding.source_indices[binding.source_indices >= 0]), {10, 17})
        np.testing.assert_allclose(binding.weights.sum(axis=1), 1)
        np.testing.assert_allclose(binding.barycentric.sum(axis=2)[binding.weights > 0], 1)
        self.assertEqual(quality["unbound_percent"], 0)

    def test_exact_gap_and_stricter_two_sided_settings(self):
        value = capture(first=(0.3, 0.75), second=(0.1, 0.25))
        with GapQueries(value) as queries:
            result = queries.sample([[0.2, 0, 0]], 4)[0]
        self.assertAlmostEqual(result[1], 0.4)
        self.assertAlmostEqual(result[2], 0.2)
        self.assertAlmostEqual(result[3], 0.25)
        self.assertTrue(result[4] >= 0 and result[5] >= 0)

    def test_winding_does_not_change_measurement(self):
        results = []
        for reverse in (False, True):
            with GapQueries(capture(reverse=reverse)) as queries:
                results.append(queries.sample([[0.2, 0, 0]], 4)[0, :4])
        np.testing.assert_allclose(*results)

    def test_disjoint_patches_of_one_contributor(self):
        value = capture(); first, second = value.sources
        merged = replace(first, vertices=np.vstack((first.vertices, second.vertices)),
                         triangles=np.vstack((first.triangles, second.triangles + 4)))
        with GapQueries(replace(value, sources=(merged,))) as queries:
            self.assertAlmostEqual(queries.sample([[0.2, 0, 0]], 4)[0, 1], 0.4)

    def test_model_scale_preserves_relative_limits(self):
        value = capture(); scaled = replace(value, lower=value.lower*10, upper=value.upper*10,
            sources=tuple(replace(s, vertices=s.vertices*10) for s in value.sources))
        with GapQueries(value) as a, GapQueries(scaled) as b:
            small = a.sample([[0.2, 0, 0]], 4)[0]
            large = b.sample([[2, 0, 0]], 40)[0]
        np.testing.assert_allclose(large[:3], small[:3]*10)


if __name__ == "__main__":
    unittest.main()
