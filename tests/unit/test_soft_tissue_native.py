import unittest
from unittest.mock import patch
import numpy as np

from core.vcp import soft_tissue_static_envelope as envelope
from core.vcp import soft_tissue_native as native
from core.vcp.soft_tissue_static_pouch import mesh_volume, triangulate_faces, StaticPouchSettings, solve_static_tissue
from core.vcp.soft_tissue_surface_inflation import SurfaceLayerProfile, inflate_surface_layer
from test_soft_tissue_static_pouch import cube_fixture
from test_soft_tissue_static_envelope import envelope_fixture
import soft_tissue_reference as reference


class NativeTissueTests(unittest.TestCase):
    def test_fixed_goals_do_not_claim_convergence_with_impossible_volume(self):
        vertices, faces = cube_fixture()
        goals = {4: (-1, -1, 2)}
        result = solve_static_tissue(vertices, faces, range(8), StaticPouchSettings(iterations=5), fixed_goals=goals)
        self.assertEqual(result.vertices[4], goals[4])
        self.assertEqual(result.report["status"], "ITERATION_LIMIT")
        self.assertEqual(result.iterations, 5)

    def test_hole_boundary_closes_with_consistent_volume(self):
        points = ((-2,-2,0),(2,-2,0),(2,2,0),(-2,2,0),(-1,-1,0),(1,-1,0),(1,1,0),(-1,1,0))
        faces = ((0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7))
        mesh = inflate_surface_layer(points, ((0,0,1),)*8, faces, (), (1,)*8, SurfaceLayerProfile(.2,.2))
        self.assertAlmostEqual(mesh_volume(mesh.vertices, triangulate_faces(mesh.faces)), 2.4)
        reverse = inflate_surface_layer(points, ((0,0,-1),)*8, tuple(f[::-1] for f in faces), (), (1,)*8, SurfaceLayerProfile(.2,.2))
        self.assertAlmostEqual(mesh_volume(reverse.vertices, triangulate_faces(reverse.faces)), 2.4)

    def test_closed_source_retains_opposite_cavity_orientation(self):
        points, faces = cube_fixture()
        normals = tuple(tuple(np.asarray(p)-(.0,.0,.5)) for p in points)
        mesh = inflate_surface_layer(points, normals, faces, (), (1,)*8, SurfaceLayerProfile())
        front = mesh_volume(mesh.vertices, triangulate_faces(mesh.faces[:6]))
        backing = mesh_volume(mesh.vertices, triangulate_faces(mesh.faces[6:]))
        self.assertGreater(front, 0)
        self.assertLess(backing, 0)
        self.assertAlmostEqual(mesh_volume(mesh.vertices, triangulate_faces(mesh.faces)), front+backing)

    def test_native_matches_reference_envelope(self):
        mesh, fixed = envelope_fixture(0.8)
        settings = envelope.StaticEnvelopeSettings()
        state = reference._create_state(mesh.vertices, mesh.faces, fixed, mesh.base_vertex_count, settings)
        reference._solve(state, settings, (), 1.e-5)
        reference._finalize_volume(state, settings)
        actual = envelope.solve_static_envelope(mesh.vertices, mesh.faces, fixed, mesh.base_vertex_count, settings)
        self.assertLess(np.max(np.abs(np.asarray(actual.vertices) - state.points)), 1.e-10)

    def test_volume_and_native_solution_are_translation_invariant(self):
        mesh, fixed = envelope_fixture(0.8)
        delta = np.asarray((100., -200., 300.))
        moved = np.asarray(mesh.vertices) + delta
        triangles = triangulate_faces(mesh.faces)
        self.assertAlmostEqual(mesh_volume(mesh.vertices, triangles), mesh_volume(moved, triangles), places=10)
        args = (mesh.faces, fixed, mesh.base_vertex_count, envelope.StaticEnvelopeSettings())
        before = envelope.solve_static_envelope(mesh.vertices, *args)
        after = envelope.solve_static_envelope(moved, *args)
        self.assertLess(np.max(np.abs(np.asarray(after.vertices) - delta - before.vertices)), 1.e-8)

    def test_iteration_limit_is_reported(self):
        mesh, fixed = envelope_fixture(0.8)
        result = envelope.solve_static_envelope(mesh.vertices, mesh.faces, fixed, mesh.base_vertex_count,
                                                envelope.StaticEnvelopeSettings(iterations=1))
        self.assertEqual(result.report["status"], "ITERATION_LIMIT")
        self.assertFalse(result.converged)
        self.assertEqual(result.report["max_fixed_error"], 0)

    def test_missing_native_has_no_python_fallback(self):
        mesh, fixed = envelope_fixture(0.8)
        with patch.object(native, "library", side_effect=RuntimeError("NATIVE_UNAVAILABLE")):
            with self.assertRaisesRegex(RuntimeError, "NATIVE_UNAVAILABLE"):
                envelope.solve_static_envelope(mesh.vertices, mesh.faces, fixed, mesh.base_vertex_count,
                                                envelope.StaticEnvelopeSettings())

    def test_shell_edges_have_opposite_directions(self):
        mesh, _fixed = envelope_fixture(0.8)
        edges = {}
        for face in mesh.faces:
            for a, b in zip(face, face[1:] + face[:1]):
                edges.setdefault(tuple(sorted((a, b))), []).append((a, b))
        for uses in edges.values():
            self.assertEqual(len(uses), 2)
            self.assertEqual(uses[0], uses[1][::-1])
