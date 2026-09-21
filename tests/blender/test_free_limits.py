from unittest.mock import patch
import bpy
import numpy as np
from mathutils import Vector
from _helpers import BlenderTestCase
from test_free_fibers import fixture
from anthroforge.app.use_cases import free_fiber as service
from anthroforge.core.visualization import free_fiber_runtime as runtime
from anthroforge.app.use_cases.fiber_surface_create import _new_surface, _assign_refs
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates


class FreeLimitsTests(BlenderTestCase):
    def test_preallocation_budget_failure_preserves_committed_path(self):
        from test_free_shared import shared_fixture
        owner, first, second, _controlled, points = shared_fixture()
        with suppress_vcp_prop_updates():
            surface = _new_surface(owner.af_vcp_system, 'Budget', 'LOFT', False, False)
            _assign_refs(surface, [first.id, second.id])
        payload, rows = runtime.current(owner, bpy.context.scene, first); before = first.free_path_json
        changed = list(rows); changed[1] = changed[1] + Vector((0, 0, .2))
        with patch('anthroforge.core.vcp.free_surface.MAX_VERTICES', 2):
            with self.assertRaisesRegex(ValueError, 'FREE_OUTPUT_BUDGET'): service.commit(owner, bpy.context.scene, first, payload, changed)
        self.assertEqual(first.free_path_json, before)

    def test_oversized_loop_patch_rejects_before_triangle_allocation(self):
        from anthroforge.core.vcp.fiber_surface import FiberSurfaceSpec, evaluate_fiber_surface
        theta = np.linspace(0, 2*np.pi, 512, endpoint=False)
        row = np.column_stack((np.cos(theta), np.sin(theta), np.zeros_like(theta)))
        with patch('anthroforge.core.vcp.fiber_surface._triangulated_patch', side_effect=AssertionError('allocation')):
            with self.assertRaisesRegex(ValueError, 'FREE_OUTPUT_BUDGET'):
                evaluate_fiber_surface([row], FiberSurfaceSpec('LOOP_PATCH', patch_resolution=64, exact_samples=True))
