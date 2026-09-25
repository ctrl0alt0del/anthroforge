"""The muscle action must reverse displacement, not only mesh winding."""
import numpy as np
import bpy
from _helpers import BlenderTestCase, select_only
from test_muscle_vcp_workflows import _muscle_setup
from anthroforge.app.use_cases.muscle_profile import configure, inspect, preview
from anthroforge.core.visualization.muscle_sync_helpers import find_muscle_proxy


def _mesh_vertices(root, muscle):
    obj = find_muscle_proxy(bpy.data.collections['AF_VCP_VIS'], root.name, muscle.id, 'INFL')
    return np.array([obj.matrix_world @ vertex.co for vertex in obj.data.vertices])


class MuscleInflationSideTests(BlenderTestCase):
    def test_ui_matches_authoring_direction_for_control_and_distributed(self):
        root, first, second = _muscle_setup()
        select_only(first); second.select_set(True); bpy.ops.af.add_muscle_vcp()
        muscle = root.af_vcp_system.muscles[0]
        for mode in ('control_point', 'distributed'):
            with self.subTest(mode=mode):
                self._assert_direction(root, muscle, mode)

    def _assert_direction(self, root, muscle, mode):
        configure(root, bpy.context.scene, muscle.id, dict(mode=mode, native=dict(flip_normals=False, inflation_max_value=.2)))
        before = _mesh_vertices(root, muscle)
        target, _ = inspect(root, bpy.context.scene, muscle.id)
        _, _, expected = preview(target, dict(mode=mode, native=dict(flip_normals=True)))
        bpy.ops.af.flip_muscle_normals(muscle_id=muscle.id)
        after = _mesh_vertices(root, muscle)
        np.testing.assert_allclose(after, expected.results[0].inflated_vertices, atol=1e-5)
        self.assertGreater(float(np.linalg.norm(after-before, axis=1).max()), 1e-5)
        self.assertFalse(root.af_vcp_system.fiber_surfaces[0].flip_normals)
        bpy.ops.af.flip_muscle_normals(muscle_id=muscle.id)
        np.testing.assert_allclose(_mesh_vertices(root, muscle), before, atol=1e-5)
