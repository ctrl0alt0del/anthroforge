from pathlib import Path
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

import bpy
from mathutils import Vector

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT.parent)):
    if value not in sys.path:
        sys.path.insert(0, value)

from anthroforge.core.vcp.fiber_engine import FiberTermination
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.vcp.runtime_state import fiber_recompute_status, set_fiber_recompute_status
from anthroforge.core.visualization import fiber_refinement
from anthroforge.core.visualization.fiber_sync import register_fiber_sync
from _helpers import BlenderTestCase, find_flagged, mesh_object, root, scp_with_object


def _legacy_setup():
    root_obj = root()
    origin = scp_with_object(root_obj, "Origin", mesh_object("Origin"))
    insert = scp_with_object(root_obj, "Insert", mesh_object("Insert", (2.0, 0.0, 0.0)))
    bpy.context.scene.af_new_fiber_origin_obj = origin.geometry_object_ref
    bpy.context.scene.af_new_fiber_insertion_obj = insert.geometry_object_ref
    bpy.ops.af.add_fiber_vcp()
    fiber = root_obj.af_vcp_system.fibers[0]
    with suppress_vcp_prop_updates():
        fiber.solver_version = 1
    return root_obj, fiber


def _curve_rows(proxy):
    spline = proxy.data.splines[0]
    return [tuple(float(value) for value in point.co[:3]) for point in spline.points]


def _warp_preview(root_obj, fiber, proxy):
    points = [Vector(row) + Vector((0.0, 3.0, 0.0)) for row in json.loads(proxy["af_fiber_points_world"])]
    register_fiber_sync().apply_points(root_obj, bpy.context.scene, fiber, points, commit=False)


def _begin_migration():
    root_obj, fiber = _legacy_setup()
    proxy = find_flagged("af_fiber_proxy", fiber.id, "af_fiber_id")
    set_fiber_recompute_status(fiber, "CONVERGED")
    before = (proxy["af_fiber_points_world"], int(proxy.get("af_fiber_output_generation", 0)))
    with patch.dict(os.environ, {"AF_FIBER_ENGINE": "V2"}):
        assert bpy.ops.af.recompute_fiber(fiber_id=fiber.id) == {"FINISHED"}
    job = next(iter(fiber_refinement._JOBS.values()))
    _warp_preview(root_obj, fiber, proxy)
    return root_obj, fiber, proxy, job, before


def _assert_rollback(case, fiber, proxy, before, state="CURRENT"):
    expected = json.loads(before[0])
    case.assertEqual((fiber.solver_version, fiber.get("af_pending_solver_version")), (1, None))
    case.assertEqual(proxy["af_fiber_points_world"], before[0])
    case.assertEqual(int(proxy.get("af_fiber_output_generation", 0)), before[1])
    case.assertEqual(proxy.get("af_fiber_output_state"), state)
    for actual, wanted in zip(_curve_rows(proxy), expected):
        case.assertLess((Vector(actual) - Vector(wanted)).length, 1.0e-9)


class FiberRefinementCancellationTests(BlenderTestCase):
    def test_user_cancel_rolls_back_migration_without_publish(self):
        _root, fiber, proxy, job, before = _begin_migration()
        callback = Mock()
        with patch.object(fiber_refinement, "_sync_scene", return_value=callback):
            self.assertTrue(fiber_refinement.cancel_fiber_refinement(bpy.context.scene, fiber.id))
        _assert_rollback(self, fiber, proxy, before)
        self.assertEqual((job.session.termination_reason, fiber_recompute_status(fiber)),
                         (FiberTermination.CANCELLED.value, "UNKNOWN"))
        callback.assert_not_called()

    def test_shutdown_restores_previous_status_and_shape(self):
        _root, fiber, proxy, job, before = _begin_migration()
        callback = Mock()
        with patch.object(fiber_refinement, "_sync_scene", return_value=callback):
            fiber_refinement.shutdown_fiber_refinements(mark_unknown=False)
        _assert_rollback(self, fiber, proxy, before)
        self.assertEqual((job.session.termination_reason, fiber_recompute_status(fiber)),
                         (FiberTermination.CANCELLED.value, "CONVERGED"))
        callback.assert_not_called()

    def test_stale_token_is_superseded_and_never_published(self):
        _root, fiber, proxy, job, before = _begin_migration()
        fiber["af_fiber_request_token"] = job.token + 1
        callback = Mock()
        with patch.object(fiber_refinement, "_sync_scene", return_value=callback):
            fiber_refinement.drain_fiber_refinements(max_slices=1)
        _assert_rollback(self, fiber, proxy, before, "STALE")
        self.assertEqual(job.session.termination_reason, FiberTermination.SUPERSEDED.value)
        callback.assert_not_called()

    def test_collider_invalidation_cancels_and_rolls_back(self):
        _root, fiber, proxy, job, before = _begin_migration()
        collider = job.session.oracle.colliders()[0]["obj"]
        update = SimpleNamespace(id=collider.data, is_updated_geometry=True, is_updated_transform=False)
        callback = Mock()
        with patch.object(fiber_refinement, "_sync_scene", return_value=callback):
            fiber_refinement._on_depsgraph_update(bpy.context.scene, SimpleNamespace(updates=(update,)))
        _assert_rollback(self, fiber, proxy, before, "STALE")
        self.assertEqual(job.session.termination_reason, FiberTermination.CANCELLED.value)
        callback.assert_not_called()

    def test_history_pre_clears_migration_marker(self):
        _root, fiber, proxy, job, before = _begin_migration()
        fiber_refinement._on_history_pre(None)
        _assert_rollback(self, fiber, proxy, before)
        self.assertEqual(job.session.termination_reason, FiberTermination.CANCELLED.value)

    def test_load_pre_clears_migration_marker(self):
        _root, fiber, proxy, job, before = _begin_migration()
        fiber_refinement._on_load_pre(None)
        _assert_rollback(self, fiber, proxy, before)
        self.assertEqual(job.session.termination_reason, FiberTermination.CANCELLED.value)

    def test_replacement_owns_marker_and_ignores_old_cleanup(self):
        root_obj, fiber, proxy, first, before = _begin_migration()
        with suppress_vcp_prop_updates():
            fiber.use_surface_routing = True
        second = fiber_refinement.request_fiber_refinement(root_obj, bpy.context.scene, fiber)
        self.assertEqual(first.session.termination_reason, FiberTermination.SUPERSEDED.value)
        self.assertEqual(fiber.get("af_pending_solver_token"), second.job.token)
        fiber_refinement._terminate_job(first, FiberTermination.SUPERSEDED, True)
        self.assertIs(fiber_refinement._JOBS.get(second.job.key), second.job)
        self.assertEqual(fiber.get("af_pending_solver_version"), 2)
        fiber_refinement.cancel_fiber_refinement(bpy.context.scene, fiber.id)
        _assert_rollback(self, fiber, proxy, before)


if __name__ == "__main__":
    import unittest
    unittest.main(argv=[__file__])
