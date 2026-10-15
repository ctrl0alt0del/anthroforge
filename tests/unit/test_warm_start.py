import unittest
from dataclasses import replace
import tempfile
import sys
from pathlib import Path
from unittest import mock

import numpy as np

from core.draft_skin.bindings import build_skin_bindings
from core.draft_skin.model import SkinCapture, SkinSolverSettings, SkinSource
from core.topology.bindings import build_topology_guide_binding, build_topology_skin_binding
from core.warm_start.model import SkinWarmCapture, WarmInvalidationReason
from core.warm_start.invalidation import (
    WarmChangeClass, WarmChangeState, classify_change, guide_pairing_signature,
    source_contact_signature,
)
from core.warm_start.signatures import (
    geometry_state_hash, source_connectivity_signature, source_identity_signature,
    structural_signature,
)
from core.warm_start.skin_solver import predict_skin_vertices, solve_warm_skin
from core.warm_start.skin_solver import inversion_safe_vertices, restore_offsets, source_triangle_transformations
from core.warm_start.arap import constrained_arap
from core.warm_start.migration import prepare_legacy_skin
from core.warm_start.topology_solver import enforce_symmetry, rebind_topology, reproject_topology
from core.warm_start.metrics import symmetry_error
from core.topology.model import SymmetryPlane
from core.warm_start.job import _replace_with_retry, read_status, write_status
from core.warm_start.model import WarmUpdateStatus
from core.warm_start.arap import arap_cache_stats, clear_arap_cache, constrained_arap
from adapters.warm_update import jobs as warm_jobs
from workers import warm_update_worker


class WarmStartTests(unittest.TestCase):
    def test_barycentric_binding_reconstructs_surface_point(self):
        source = _triangle_source()
        point = np.asarray(((0.25, 0.25, 0.2),))
        binding, _quality = build_skin_bindings(point, (source,))
        face = source.vertices[source.triangles[binding.triangle_indices[0, 0]]]
        projected = binding.barycentric[0, 0] @ face
        np.testing.assert_allclose(projected, (0.25, 0.25, 0.0), atol=1e-6)

    def test_multi_source_weights_are_normalized(self):
        first, second = _triangle_source(0, 0.0), _triangle_source(1, 0.1)
        binding, _quality = build_skin_bindings(np.asarray(((0.2, 0.2, 0.05),)), (first, second))
        np.testing.assert_allclose(binding.weights.sum(axis=1), 1.0)
        self.assertEqual(set(binding.source_indices[0, :2]), {0, 1})

    def test_occluded_source_triangle_is_rejected(self):
        sources = (_triangle_source(0, 0.0), _triangle_source(1, -1.0))
        binding, quality = build_skin_bindings(np.asarray(((0.2, 0.2, 1.0),)), sources)
        used = binding.source_indices[0][binding.weights[0] > 0.0]
        self.assertNotIn(1, used.tolist())
        self.assertEqual(quality["visibility_rejected_percent"], 0.0)

    def test_source_frame_transformation_maps_triangle(self):
        old = _triangle_source(0, 0.0)
        rotation = np.asarray(((0, -1, 0), (1, 0, 0), (0, 0, 1)), float)
        moved = old.vertices @ rotation.T + np.asarray((2.0, 3.0, 0.0))
        new = SkinSource(0, "SCP", "S0", "ORIGINAL", "Source", moved, old.triangles)
        transform, translation = source_triangle_transformations((old,), (new,))[0]
        mapped = transform[0] @ old.vertices[1] + translation[0]
        np.testing.assert_allclose(mapped, new.vertices[1], atol=1e-6)

    def test_arap_constraints_follow_uniform_translation(self):
        vertices, faces = _skin(0.0); targets = vertices + (0.0, 0.0, 0.5)
        result = constrained_arap(vertices, faces, targets, "unit-arap", iterations=3)
        np.testing.assert_allclose(result, targets, atol=1e-5)

    def test_inversion_backtracking_keeps_valid_orientation(self):
        reference = np.asarray(((0, 0, 0), (1, 0, 0), (0, 1, 0)), float)
        proposal = reference.copy(); proposal[2, 1] = -1.0
        faces = np.asarray(((0, 1, 2),), np.int32)
        result = inversion_safe_vertices(reference, proposal, faces)
        normal = np.cross(result[1] - result[0], result[2] - result[0])
        self.assertGreater(normal[2], 0.0)

    def test_collagen_normal_offset_is_restored(self):
        source = _triangle_source(); point = np.asarray(((0.2, 0.2, 0.3),))
        binding, _quality = build_skin_bindings(point, (source,))
        predicted = predict_skin_vertices(binding, (source,))
        restored = restore_offsets(predicted, binding, (source,))
        np.testing.assert_allclose(restored, point, atol=1e-6)

    def test_structural_signature_changes_only_with_connectivity(self):
        _vertices, faces = _skin(0.0)
        same = structural_signature(4, faces.copy())
        changed = structural_signature(4, faces[:, ::-1])
        self.assertEqual(same, structural_signature(4, faces))
        self.assertNotEqual(same, changed)

    def test_warm_solver_is_deterministic(self):
        old, new = _source(0.0), _source(0.1)
        points = np.asarray(((0.2, 0.2, 0.1), (0.7, 0.2, 0.1), (0.2, 0.7, 0.1)))
        faces = np.asarray(((0, 1, 2),), np.int32)
        binding, _quality = build_skin_bindings(points, (old,))
        capture = _warm_capture(points, faces, binding, old, new)
        np.testing.assert_allclose(solve_warm_skin(capture).vertices,
                                   solve_warm_skin(capture).vertices)

    def test_arap_reuses_edges_and_factorization(self):
        vertices, faces = _skin(0.0); clear_arap_cache()
        constrained_arap(vertices, faces, vertices, "stable", iterations=1)
        before = arap_cache_stats()
        constrained_arap(vertices, faces, vertices, "stable", iterations=1)
        after = arap_cache_stats()
        self.assertEqual(after["factor_builds"], before["factor_builds"])
        self.assertGreater(after["factor_hits"], before["factor_hits"])

    def test_topology_projection_avoids_global_rebind_when_bound(self):
        skin, triangles = _skin(0.0); vertices = skin.copy()
        quads = np.asarray(((0, 1, 2, 3),), np.int32)
        binding = build_topology_skin_binding(vertices, skin, triangles)
        guide = _empty_guides(4)
        with mock.patch("core.warm_start.topology_solver.build_topology_skin_binding",
                        wraps=build_topology_skin_binding) as rebuild:
            result = reproject_topology(vertices, quads, skin, triangles, binding, guide)
        self.assertTrue(result[1].valid); rebuild.assert_not_called()

    def test_legacy_skin_migration_preserves_geometry(self):
        vertices, faces = _cube()
        capture = _skin_capture(_cube_source())
        result = prepare_legacy_skin(vertices, faces, np.ones(len(vertices)), capture)
        np.testing.assert_array_equal(result.vertices, vertices)
        self.assertEqual(result.binding.weights.shape, (len(vertices), 4))

    def test_four_influence_binding_is_complete(self):
        source = _source(0.0)
        points = np.asarray(((0.2, 0.2, 0.1), (0.8, 0.8, 0.1)))
        binding, quality = build_skin_bindings(points, (source,))
        self.assertEqual(binding.weights.shape, (2, 4))
        np.testing.assert_allclose(binding.weights.sum(axis=1), 1.0)
        self.assertEqual(quality["unbound_percent"], 0.0)

    def test_skin_prediction_follows_source_translation(self):
        old, new = _source(0.0), _source(2.0)
        points = np.asarray(((0.2, 0.2, 0.1), (0.7, 0.2, 0.1), (0.2, 0.7, 0.1)))
        binding, _quality = build_skin_bindings(points, (old,))
        baseline = predict_skin_vertices(binding, (old,))
        predicted = predict_skin_vertices(binding, (new,))
        np.testing.assert_allclose(predicted[:, 0] - baseline[:, 0], 2.0, atol=1e-6)

    def test_warm_skin_rejects_connectivity_change(self):
        old, changed = _source(0.0), _source(0.0, flipped=True)
        points = np.asarray(((0.2, 0.2, 0.1), (0.7, 0.2, 0.1), (0.2, 0.7, 0.1)))
        faces = np.asarray(((0, 1, 2),), np.int32)
        binding, _quality = build_skin_bindings(points, (old,))
        capture = _warm_capture(points, faces, binding, old, changed)
        result = solve_warm_skin(capture)
        self.assertEqual(result.status.reason, WarmInvalidationReason.SOURCE_CONNECTIVITY_CHANGED)

    def test_invalid_binding_stops_before_deformation(self):
        source = _source(0.0); points, faces = _skin(0.0)
        binding, _quality = build_skin_bindings(points, (source,))
        invalid = ({"source_indices": np.full_like(binding.source_indices, 99)},
                   {"triangle_indices": np.full_like(binding.triangle_indices, 99)},
                   {"weights": np.full_like(binding.weights, np.nan)}, {"weights": np.ones(4)})
        for change in invalid:
            capture = _warm_capture(points, faces, replace(binding, **change), source, source)
            with self.subTest(change=tuple(change)), mock.patch("core.warm_start.skin_solver.constrained_arap") as arap:
                result = solve_warm_skin(capture)
                self.assertFalse(result.status.valid)
                self.assertEqual(result.status.reason, WarmInvalidationReason.BINDING_QUALITY)
                arap.assert_not_called()

    def test_topology_reprojection_preserves_connectivity_and_order(self):
        skin, triangles = _skin(0.0)
        moved, _unused = _skin(1.0)
        topology = np.asarray(((0.1, 0.1, 0.0), (0.9, 0.1, 0.0),
                               (0.9, 0.9, 0.0), (0.1, 0.9, 0.0)))
        quads = np.asarray(((0, 1, 2, 3),), np.int32)
        binding = build_topology_skin_binding(topology, skin, triangles)
        guide = _empty_guides(4)
        result, status, _report = reproject_topology(topology, quads, moved,
                                                     triangles, binding, guide)
        self.assertTrue(status.valid)
        self.assertEqual(result.shape, topology.shape)

    def test_arbitrary_plane_symmetry_is_exact_after_warm_projection(self):
        origin = np.asarray((0.2, -0.1, 0.3)); normal = np.asarray((1.0, 1.0, 0.0))
        normal /= np.linalg.norm(normal); first = np.asarray((1.0, 0.5, 0.2))
        second = first - 2.0 * np.dot(first - origin, normal) * normal
        reference = np.asarray((first, second)); proposal = reference + ((0.1, 0, 0), (0, 0.2, 0))
        result = enforce_symmetry(reference, proposal, SymmetryPlane(origin, normal))
        self.assertLess(symmetry_error(result, origin, normal)["max"], 1e-10)

    def test_rebind_keeps_quad_connectivity(self):
        skin, triangles = _skin(0.0)
        topology = np.asarray(((0.1, 0.1, 0.0), (0.9, 0.1, 0.0),
                               (0.9, 0.9, 0.0), (0.1, 0.9, 0.0)))
        quads = np.asarray(((0, 1, 2, 3),), np.int32)
        regions, guides = np.zeros(1, np.int32), np.full(1, -1, np.int32)
        skin_binding, _guide_binding, status, _report = rebind_topology(
            topology, quads, skin, triangles, regions, guides, ())
        self.assertTrue(status.valid)
        self.assertEqual(len(skin_binding.triangle_indices), len(topology))

    def test_guide_binding_records_structured_rows(self):
        outer = np.asarray(((-2, -2, 0), (2, -2, 0), (2, 2, 0), (-2, 2, 0)), float)
        inner = outer * 0.5; vertices = np.vstack((outer, inner))
        quads = np.asarray(((0, 1, 5, 4), (1, 2, 6, 5),
                            (2, 3, 7, 6), (3, 0, 4, 7)), np.int32)
        binding = build_topology_guide_binding(vertices, quads, np.full(4, 2),
                                               np.zeros(4), (outer,))
        np.testing.assert_array_equal(binding.rows[:4], 0)
        np.testing.assert_array_equal(binding.rows[4:], 1)

    def test_guide_rows_remain_exact_during_reprojection(self):
        skin, triangles = _skin(0.0); vertices, quads = _annulus()
        old = _guide_from_points(0, vertices[:4]); new = _guide_from_points(0, vertices[:4] + (0.05, 0, 0))
        skin_binding = build_topology_skin_binding(vertices, skin, triangles)
        guide_binding = build_topology_guide_binding(vertices, quads, np.full(4, 2),
                                                     np.zeros(4), (old,))
        result, status, _report = reproject_topology(vertices, quads, skin, triangles,
                                                     skin_binding, guide_binding, (old,), (new,))
        self.assertTrue(status.valid)
        np.testing.assert_allclose(result, vertices + (0.05, 0, 0), atol=1e-6)

    def test_change_classifier_separates_rebuild_scope(self):
        baseline = _change_state()
        skin = _change_state(source_contact="contact-b")
        topology = _change_state(guide_layout="guides-b")
        full = _change_state(source_contact="contact-b", guide_layout="guides-b")
        self.assertEqual(classify_change(baseline, baseline).change_class, WarmChangeClass.GEOMETRY_ONLY)
        self.assertEqual(classify_change(baseline, skin).change_class, WarmChangeClass.SKIN_REBUILD)
        self.assertEqual(classify_change(baseline, topology).change_class, WarmChangeClass.TOPOLOGY_REBUILD)
        self.assertEqual(classify_change(baseline, full).change_class, WarmChangeClass.FULL_REBUILD)

    def test_change_classifier_honors_force_modes(self):
        state = _change_state()
        self.assertEqual(classify_change(state, state, "SKIN").change_class, WarmChangeClass.SKIN_REBUILD)
        self.assertEqual(classify_change(state, state, "TOPOLOGY").change_class, WarmChangeClass.TOPOLOGY_REBUILD)
        unsafe = _change_state(source_connectivity="changed")
        self.assertEqual(classify_change(state, unsafe, "TOPOLOGY").change_class, WarmChangeClass.FULL_REBUILD)

    def test_each_skin_invalidation_trigger(self):
        changes = ({"source_identity": "new"}, {"source_connectivity": "new"},
                   {"source_contact": "new"}, {"collagen_settings": (0.03, 0.02)},
                   {"skin_valid": False})
        for change in changes:
            with self.subTest(change=change):
                decision = classify_change(_change_state(), _change_state(**change))
                self.assertTrue(decision.skin_rebuild)

    def test_each_topology_invalidation_trigger(self):
        changes = ({"guide_layout": "new"}, {"guide_pairing": "new"},
                   {"symmetry_settings": "new"}, {"density_settings": "new"},
                   {"topology_valid": False})
        for change in changes:
            with self.subTest(change=change):
                decision = classify_change(_change_state(), _change_state(**change))
                self.assertTrue(decision.topology_rebuild)

    def test_distortion_quality_does_not_rebuild_topology(self):
        decision = classify_change(_change_state(), _change_state(quad_distortion=9.0))
        self.assertFalse(decision.topology_rebuild)

    def test_contact_and_pairing_signatures_are_deterministic(self):
        sources = (_source(0.0), _source(0.5))
        guides = (_guide("outer", 2.0), _guide("inner", 1.0))
        self.assertEqual(source_contact_signature(sources), source_contact_signature(sources))
        self.assertEqual(guide_pairing_signature(guides), guide_pairing_signature(guides))

    def test_warm_status_round_trip_preserves_reason(self):
        status = WarmUpdateStatus(False, "Fallback", 0.5, "Changed",
                                  WarmInvalidationReason.STRUCTURE_CHANGED,
                                  state="RUNNING", update_type="rebound")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "status.json"; write_status(path, status)
            loaded = read_status(path)
        self.assertEqual(loaded, status)

    def test_atomic_status_replace_retries_windows_sharing_violation(self):
        with mock.patch("core.warm_start.job.os.replace",
                        side_effect=(PermissionError("busy"), None)) as replace:
            with mock.patch("core.warm_start.job.time.sleep") as sleep:
                _replace_with_retry("temporary", "target")
        self.assertEqual(replace.call_count, 2); sleep.assert_called_once()

    def test_coordinated_job_enforces_one_per_scene(self):
        scene, process = _FakeScene(), _FakeProcess()
        with mock.patch.object(warm_jobs, "_prepare", return_value=process):
            warm_jobs.start_job(scene, "Root", "AUTO", "blender", lambda _path: None)
            with self.assertRaises(RuntimeError):
                warm_jobs.start_job(scene, "Root", "AUTO", "blender", lambda _path: None)
            self.assertTrue(warm_jobs.cancel_job(scene))
        warm_jobs.finish_job(scene, True); warm_jobs.shutdown_jobs()

    def test_warm_service_is_reused_for_subsequent_jobs(self):
        process, folder = _FakeProcess(), Path(tempfile.mkdtemp())
        with mock.patch.object(warm_jobs, "_SERVICE", None):
            with mock.patch.object(warm_jobs, "_launch_service", return_value=process) as launch:
                first = warm_jobs._ensure_service("blender")
                second = warm_jobs._ensure_service("blender")
        self.assertIs(first[0], second[0]); launch.assert_called_once()
        import shutil; shutil.rmtree(first[1], ignore_errors=True)

    def test_full_skin_fallback_rebinds_topology_before_rebuild(self):
        decision = mock.Mock(topology_rebuild=False)
        with mock.patch.object(warm_update_worker, "_topology_object", return_value=object()):
            with mock.patch.object(warm_update_worker, "_try_warm_topology", return_value="warm"):
                result = warm_update_worker._solve_topology(None, None, None, decision, "rebuilt", None)
        self.assertEqual(result, ("warm", "rebound"))

    def test_topology_rebuild_occurs_only_when_classified(self):
        decision = mock.Mock(topology_rebuild=True)
        with mock.patch.object(warm_update_worker, "_status"):
            with mock.patch.object(warm_update_worker, "_full_topology", return_value="full") as full:
                result = warm_update_worker._solve_topology(None, None, None, decision, "warm", None)
        self.assertEqual(result, ("full", "rebuilt")); full.assert_called_once()

    def test_prepare_skin_falls_back_only_after_binding_failure(self):
        state = {"skin": True}
        migration = mock.Mock(); migration.prepare_skin.side_effect = ValueError("bad")
        with mock.patch("adapters.draft_skin.capture.capture_skin", return_value="capture"):
            with mock.patch.dict(sys.modules, {"adapters.warm_update.migration": migration}):
                with mock.patch.object(warm_update_worker, "_append_log"):
                    with mock.patch.object(warm_update_worker, "_rebuild_skin", return_value="full") as rebuild:
                        result = warm_update_worker._prepare_skin_stage(None, None, None, None, state)
        self.assertEqual(result[0:2], ("full", "rebuilt")); rebuild.assert_called_once()


def _source(offset, flipped=False):
    vertices, triangles = _skin(offset)
    if flipped:
        triangles = triangles[:, ::-1].copy()
    return SkinSource(0, "SCP", "S1", "ORIGINAL", "Source", vertices, triangles)


def _triangle_source(index=0, z=0.0):
    vertices = np.asarray(((0, 0, z), (1, 0, z), (0, 1, z)), float)
    return SkinSource(index, "SCP", f"S{index}", "ORIGINAL", "Source",
                      vertices, np.asarray(((0, 1, 2),), np.int32))


def _cube():
    vertices = np.asarray(((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                           (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)), float)
    faces = np.asarray(((0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
                        (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
                        (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)), np.int32)
    return vertices, faces


def _cube_source():
    vertices, faces = _cube()
    return SkinSource(0, "SCP", "cube", "ORIGINAL", "Cube", vertices, faces)


def _skin_capture(source):
    vertices = np.asarray(source.vertices)
    return SkinCapture("Root", (source,), vertices.min(0), vertices.max(0), "hash",
                       0.01, settings=SkinSolverSettings())


def _skin(offset):
    vertices = np.asarray(((offset, 0, 0), (offset + 1, 0, 0),
                           (offset + 1, 1, 0), (offset, 1, 0)), float)
    return vertices, np.asarray(((0, 1, 2), (0, 2, 3)), np.int32)


def _warm_capture(points, faces, binding, old, new):
    return SkinWarmCapture(points, faces, binding, (old,), (new,),
                           structural_signature(len(points), faces),
                           source_connectivity_signature((old,)),
                           geometry_state_hash((new,)), "settings", source_identity_signature((old,)))


def _empty_guides(count):
    from core.warm_start.model import TopologyGuideBinding
    return TopologyGuideBinding(np.full(count, -1), np.full(count, -1),
                                np.full(count, -1.0))


def _change_state(**changes):
    values = dict(source_identity="identity", source_connectivity="connectivity",
                  source_contact="contact", collagen_settings=(0.01, 0.02),
                  guide_layout="guides", guide_pairing="pairing",
                  symmetry_settings="symmetry", density_settings="density")
    values.update(changes)
    return WarmChangeState(**values)


def _guide(name, radius):
    from core.topology.model import TopologyGuide
    angles = np.linspace(0.0, 2.0 * np.pi, 8, endpoint=False)
    points = np.column_stack((radius * np.cos(angles), radius * np.sin(angles), np.zeros(8)))
    return TopologyGuide(0, name, name, "ORIGINAL", points)


def _guide_from_points(index, points):
    from core.topology.model import TopologyGuide
    return TopologyGuide(index, f"guide-{index}", f"guide-{index}", "ORIGINAL", np.asarray(points))


def _annulus():
    outer = np.asarray(((0.1, 0.1, 0), (0.9, 0.1, 0), (0.9, 0.9, 0), (0.1, 0.9, 0)))
    inner = np.asarray(((0.3, 0.3, 0), (0.7, 0.3, 0), (0.7, 0.7, 0), (0.3, 0.7, 0)))
    quads = np.asarray(((0, 1, 5, 4), (1, 2, 6, 5),
                        (2, 3, 7, 6), (3, 0, 4, 7)), np.int32)
    return np.vstack((outer, inner)), quads


class _FakeScene:
    def as_pointer(self):
        return id(self)


class _FakeProcess:
    def __init__(self):
        self.stopped = False

    def poll(self):
        return None if not self.stopped else 0

    def terminate(self):
        self.stopped = True


if __name__ == "__main__":
    unittest.main()
