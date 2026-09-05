from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import bpy
from mathutils import Vector

ADDON_ROOT = Path(__file__).resolve().parents[2]
BLENDER_TEST_ROOT = Path(__file__).resolve().parent
for value in (str(BLENDER_TEST_ROOT), str(ADDON_ROOT), str(ADDON_ROOT.parent)):
    if value not in sys.path:
        sys.path.insert(0, value)

from anthroforge.core.visualization import fiber_refinement
from anthroforge.core.visualization.fiber_sync import register_fiber_sync
from anthroforge.core.visualization.fiber_sync_helpers import cached_fiber_points
from _helpers import BlenderTestCase, capture_mesh_attachment, fiber, mesh_object, root, scp_with_object


def _setup():
    root_obj = root()
    first = scp_with_object(root_obj, "First", mesh_object("First"))
    second = scp_with_object(root_obj, "Second", mesh_object("Second", (3.0, 0.0, 0.0)))
    item = fiber(root_obj, first.id, second.id)
    item.a_attach_param = capture_mesh_attachment(root_obj, first, 0)
    item.b_attach_param = capture_mesh_attachment(root_obj, second, 0)
    item.node_count = 8
    return root_obj, item


def _points(y):
    return [Vector((3.0 * index / 7.0, y, 0.0)) for index in range(8)]


def _job(root_obj, item, session):
    scene = bpy.context.scene
    return fiber_refinement.FiberRefinementJob(
        fiber_refinement._job_key(scene, root_obj, item.id), scene.name, root_obj.name,
        fiber_refinement._id_uid(scene), fiber_refinement._id_uid(root_obj),
        fiber_refinement._id_pointer(item), item.id, (), (), session)


def _displayed(proxy):
    return [proxy.matrix_world @ point.co.xyz for point in proxy.data.splines[0].points]


class FiberFailedPreviewTests(BlenderTestCase):
    def test_interactive_failure_keeps_attempt_visible_without_publishing(self):
        root_obj, item = _setup()
        proxy = register_fiber_sync().apply_points(root_obj, bpy.context.scene, item, _points(0.0))
        persisted = str(proxy["af_fiber_points_world"])
        session = SimpleNamespace(quality="INTERACTIVE", params={"node_count": 8}, telemetry=None)
        result = SimpleNamespace(points=_points(1.0), invalid_reason="")
        with patch.object(fiber_refinement, "_commit_allowed", return_value=False):
            fiber_refinement._finish_refined_job(_job(root_obj, item, session), result)
        self.assertTrue(all(abs(point.y - 1.0) < 1.0e-9 for point in _displayed(proxy)))
        self.assertEqual((proxy["af_fiber_points_world"], proxy["af_fiber_output_state"]), (persisted, "STALE"))
        self.assertEqual(proxy["af_fiber_display_mode"], "FAILED_PREVIEW")
        self.assertIsNone(cached_fiber_points(bpy.context.scene, root_obj.name, item.id))


if __name__ == "__main__":
    import unittest
    unittest.main(argv=[__file__])
