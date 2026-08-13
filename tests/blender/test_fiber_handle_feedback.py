from pathlib import Path
import sys
from unittest.mock import patch

import bpy
from mathutils import Matrix

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

from _helpers import BlenderTestCase, capture_world_attachment, empty_object, mesh_object, root, scp_with_object
from anthroforge.app.use_cases.action_library_quick_fiber import QuickFiberPoint, commit_quick_fiber
from anthroforge.core.deps.runtime_intents import pop_runtime_intents
from anthroforge.core.scp_runtime.common import mark_applied_matrix
from anthroforge.core.visualization import fiber_refinement, fiber_sync_runtime, sync_runner
from anthroforge.core.visualization.fiber_sync import register_fiber_sync
from anthroforge.core.visualization.fiber_sync_helpers import mark_endpoint_handle


def _quick_point(root_obj, scp, index):
    obj = scp.geometry_object_ref
    world = obj.matrix_world @ obj.data.vertices[int(index)].co
    raw = capture_world_attachment(root_obj, scp.id, world)
    return QuickFiberPoint(scp.id, raw, world.copy(), world.copy(), scp.name)


def _quick_commit():
    root_obj = root()
    origin = scp_with_object(root_obj, "Origin", mesh_object("Origin"))
    guide = scp_with_object(root_obj, "Guide", mesh_object("Guide", (1.0, 2.0, 0.0)))
    insert = scp_with_object(root_obj, "Insert", mesh_object("Insert", (3.0, 0.0, 0.0)))
    bpy.context.view_layer.update()
    sync_runner.clear_pending_runtime(keep_timer=False)
    pop_runtime_intents(root_obj)
    points = (_quick_point(root_obj, origin, 1), _quick_point(root_obj, guide, 2), _quick_point(root_obj, insert, 1))
    return root_obj, commit_quick_fiber(bpy.context, points), points[1].visual_world


class FiberHandleFeedbackTests(BlenderTestCase):
    def test_one_handle_transform_enqueues_once(self):
        root_obj = root()
        handle = mark_endpoint_handle(empty_object("Endpoint"), root_obj, "F1", "A")
        mark_applied_matrix(handle)
        handle.matrix_world = Matrix.Translation((0.25, 0.0, 0.0))
        changed = set()
        args = register_fiber_sync(), root_obj, bpy.context.scene.collection, changed, handle
        with patch.object(fiber_sync_runtime, "enqueue_control_intent", return_value=True) as enqueue:
            fiber_sync_runtime._merge_changed_fibers(*args)
            fiber_sync_runtime._merge_changed_fibers(*args)
        self.assertEqual((enqueue.call_count, changed), (1, {"F1"}))

    def test_quick_fiber_handle_placement_does_not_restart_refinement(self):
        _root_obj, result, touch_world = _quick_commit()
        self.assertTrue(result.ok)
        fiber = result.value.fiber
        job = next(iter(fiber_refinement._JOBS.values()))
        token = int(fiber.get("af_fiber_request_token", 0))
        with patch.object(fiber_sync_runtime, "enqueue_control_intent", wraps=fiber_sync_runtime.enqueue_control_intent) as intent:
            with patch.object(fiber_sync_runtime, "_enqueue_fiber_runtime", wraps=fiber_sync_runtime._enqueue_fiber_runtime) as update:
                bpy.context.view_layer.update()
        self.assertGreater(touch_world.length, 1.0)
        self.assertEqual((intent.call_count, update.call_count), (0, 0))
        self.assertTrue(fiber_refinement.drain_fiber_refinements())
        self.assertEqual((job.session.done, int(fiber.get("af_fiber_request_token", 0))), (True, token))
        self.assertEqual((len(fiber_refinement._JOBS), len(fiber_refinement._QUEUE), len(sync_runner._PENDING)), (0, 0, 0))


if __name__ == "__main__":
    import unittest
    unittest.main(argv=[__file__])
