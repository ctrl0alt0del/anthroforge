import bpy
import numpy as np
from unittest.mock import patch
from _helpers import BlenderTestCase
from _branch_fixture import create_fixture
from anthroforge.app.use_cases import free_fiber as service
from anthroforge.core.visualization import branched_surface_capture as capture
from anthroforge.core.visualization.muscle_numeric_runtime import _branched_request
from anthroforge.core.vcp.branched_numeric import evaluate


class FreeConsumerTests(BlenderTestCase):
    def test_explicit_branch_link_retags_free_children_without_nearest_sampling(self):
        from anthroforge.app.use_cases import muscle_branch
        root, muscle, connection, fibers = create_fixture()
        source, boundary = connection.surface_id, connection.boundary_fiber_id
        roots = [r.point_id for r in connection.roots]; muscle_branch.remove_branch(root, muscle.id, connection.id)
        for child in fibers[2:]: muscle_branch.detach_point(root, child.id, 0)
        for fiber in fibers: service.configure_mode(root, bpy.context.scene, fiber, 'FREE')
        connection = muscle_branch.add_branch(root, muscle.id, source, boundary, roots)
        request = _branched_request(root, bpy.context.scene, muscle)
        self.assertFalse(evaluate(request, 'NATIVE').error)
        self.assertEqual([f.a_point_id for f in fibers[2:]], roots)

    def test_ordinary_free_numeric_preserves_grid_for_both_backends(self):
        from dataclasses import replace
        from test_muscle_numeric_backends import _grid, _spec
        from anthroforge.core.vcp.muscle_numeric import make_muscle_request, execute_muscle_batch
        grid = _grid(); grid[1, 3, 2] += .13
        for mode in ('DISTRIBUTED', 'CTRL_POINT'):
            request = make_muscle_request('Free', grid, replace(_spec(mode), preserve_samples=True, densify=False))
            outputs = [execute_muscle_batch([request], kind).results[0] for kind in ('PYTHON', 'NATIVE')]
            self.assertFalse(outputs[0].error); self.assertFalse(outputs[1].error)
            for result in outputs: np.testing.assert_array_equal(result.base_vertices, grid.reshape(-1, 3))
            np.testing.assert_allclose(outputs[0].inflated_vertices, outputs[1].inflated_vertices, atol=1e-6)

    def test_mixed_branch_uses_exact_tagged_root_samples_and_native_inflation(self):
        root, muscle, connection, fibers = create_fixture()
        for fiber in (fibers[0], fibers[2]): service.configure_mode(root, bpy.context.scene, fiber, 'FREE')
        with patch('anthroforge.core.vcp.fiber_node_attachment._open_pin_indices', side_effect=AssertionError('nearest root')):
            request = _branched_request(root, bpy.context.scene, muscle)
        result = evaluate(request, 'NATIVE')
        self.assertFalse(result.error)
        self.assertGreater(len(result.base_vertices), 50); self.assertTrue(np.isfinite(result.inflated_vertices).all())
        self.assertEqual(tuple(r.point_id for r in connection.roots), tuple(f.a_point_id for f in fibers[2:]))
        self.assertEqual(request.assembly.branches[0].connection.roots, (32, 48))
