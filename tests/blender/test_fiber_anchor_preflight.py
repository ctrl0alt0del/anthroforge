from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ADDON_ROOT = Path(__file__).resolve().parents[2]
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

import bpy

from _helpers import BlenderTestCase, capture_mesh_attachment, root, scp_with_object
from core.scp_runtime.prop_update_guard import set_parent_id_raw
from core.vcp import fiber_anchor_preflight as anchors
from core.vcp.prop_update_guard import suppress_vcp_prop_updates
from core.visualization import fiber_refinement
from core.visualization.fiber_sync import register_fiber_sync


def _cube_scp(root_obj, name, size, location=(0.0, 0.0, 0.0)):
    bpy.ops.mesh.primitive_cube_add(size=size, location=location)
    return scp_with_object(root_obj, name, bpy.context.active_object), bpy.context.active_object


def _fiber_with_touch(root_obj, owner, insertion):
    fiber = root_obj.af_vcp_system.fibers.add()
    with suppress_vcp_prop_updates():
        fiber.id, fiber.name = "FIBER_PREFLIGHT", "Fiber Preflight"
        fiber.a_parent_id, fiber.b_parent_id = owner.id, insertion.id
        fiber.a_attach_param = capture_mesh_attachment(root_obj, owner, 0)
        fiber.b_attach_param = capture_mesh_attachment(root_obj, insertion, 0)
        touch = fiber.mid_touches.add()
        touch.parent_id, touch.attach_param = owner.id, capture_mesh_attachment(root_obj, owner, 1)
    return fiber


def _preflight(root_obj, fiber):
    scene = bpy.context.scene
    solver = register_fiber_sync()._solver
    return anchors.preflight_fiber_hard_anchors(
        root_obj, scene, fiber, solver, bpy.context.view_layer.depsgraph)


def _scene_fixture():
    root_obj = root()
    blocker, blocker_obj = _cube_scp(root_obj, "Blocker", 4.0)
    owner, _owner_obj = _cube_scp(root_obj, "Owner", 1.0)
    insertion, _insert_obj = _cube_scp(root_obj, "Insertion", 1.0, (6.0, 0.0, 0.0))
    set_parent_id_raw(owner, blocker.id)
    return root_obj, blocker_obj, owner, _fiber_with_touch(root_obj, owner, insertion)


class FiberAnchorPreflightBlenderTests(BlenderTestCase):
    def test_ancestor_containment_blocks_all_invalid_open_anchors_and_cache_hits(self):
        root_obj, blocker_obj, owner, fiber = _scene_fixture()
        request = fiber_refinement.request_fiber_refinement(root_obj, bpy.context.scene, fiber)
        result = anchors.current_fiber_anchor_preflight(bpy.context.scene, root_obj, fiber)
        self.assertFalse(request.ok); self.assertEqual(len(result.violations), 2)
        self.assertEqual({row.relation for row in result.violations}, {"ANCESTOR"})
        self.assertNotIn(owner.id, {row.blocker_id for row in result.violations})
        with patch.object(anchors.CollisionOracle, "colliders", side_effect=AssertionError("cache miss")):
            self.assertFalse(fiber_refinement.request_fiber_refinement(root_obj, bpy.context.scene, fiber).ok)
        blocker_obj.location = (10.0, 0.0, 0.0); bpy.context.view_layer.update()
        anchors.invalidate_fiber_anchor_preflight(bpy.context.scene, root_obj, {fiber.id})
        self.assertTrue(_preflight(root_obj, fiber).valid)


if __name__ == "__main__":
    unittest.main()
