import unittest

from core.vcp.soft_tissue_model import SolverMode
from core.vcp.soft_tissue_static_pouch import StaticPouchSettings
from core.vcp.soft_tissue_surface_inflation import SurfaceLayerProfile
from core.vcp.soft_tissue_surface_pipeline import (
    GeometricRelaxationSpec,
    SurfaceTissuePipelineSpec,
    run_surface_tissue_pipeline,
    surface_fixed_indices,
)


class SoftTissueSurfacePipelineTests(unittest.TestCase):
    def setUp(self):
        self.points = ((0.0, 0.0, 0.0), (-1.0, -1.0, 0.0), (1.0, -1.0, 0.0),
                       (1.0, 1.0, 0.0), (-1.0, 1.0, 0.0))
        self.normals = ((0.0, 0.0, 1.0),) * 5
        self.faces = ((0, 1, 2), (0, 2, 3), (0, 3, 4), (0, 4, 1))
        self.boundary = ((1, 2), (2, 3), (3, 4), (4, 1))
        self.weights = (1.0, 0.0, 0.0, 0.0, 0.0)

    def run_mode(self, mode, geometric=None, static=None):
        profile = SurfaceLayerProfile(max_thickness=0.2, min_thickness=0.01)
        fixed = surface_fixed_indices(len(self.points), self.boundary)
        spec = SurfaceTissuePipelineSpec(mode, profile, geometric or GeometricRelaxationSpec(),
                                         static or StaticPouchSettings(), fixed)
        return run_surface_tissue_pipeline(self.points, self.normals, self.faces,
                                           self.boundary, self.weights, spec)

    def test_none_stops_after_inflation(self):
        result = self.run_mode(SolverMode.NONE)
        self.assertEqual(result.final_vertices, result.rest.vertices)

    def test_geometric_relaxation_moves_only_weighted_front(self):
        geometric = GeometricRelaxationSpec(0.5, (0.0, -1.0, 0.0), 0.2)
        result = self.run_mode(SolverMode.GEOMETRIC, geometric)
        self.assertAlmostEqual(result.final_vertices[0][1], -0.1)
        self.assertEqual(result.final_vertices[1], result.rest.vertices[1])
        self.assertEqual(result.final_vertices[5:], result.rest.vertices[5:])

    def test_static_pbd_uses_same_inflated_rest_mesh(self):
        static = StaticPouchSettings(2, 1, 0.001, 0.5, 0.8, (0.0, -1.0, 0.0))
        result = self.run_mode(SolverMode.STATIC_PBD, static=static)
        self.assertEqual(len(result.final_vertices), len(result.rest.vertices))
        self.assertEqual(result.final_vertices[5:], result.rest.vertices[5:])

    def test_public_solver_modes_are_static_only(self):
        self.assertEqual({item.value for item in SolverMode}, {"NONE", "GEOMETRIC", "STATIC_PBD"})

    def test_fixed_indices_include_backing_and_both_perimeters(self):
        fixed = surface_fixed_indices(len(self.points), self.boundary)
        self.assertEqual(fixed, (1, 2, 3, 4, 5, 6, 7, 8, 9))


if __name__ == "__main__":
    unittest.main()
