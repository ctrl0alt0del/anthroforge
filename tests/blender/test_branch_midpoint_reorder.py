"""Ordinary routing guides may move without changing protected branch intervals."""
from unittest.mock import patch
import bpy
from _helpers import BlenderTestCase, select_only
from _branch_fixture import create_fixture
from anthroforge.app.use_cases import fiber_tools, muscle_branch
from anthroforge.adapters.authoring.capture import native_records
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates


def append_route(fiber, source):
    with suppress_vcp_prop_updates():
        point = fiber.mid_touches.add()
        point.parent_id, point.attach_param = source.parent_id, source.attach_param
        point.normal_offset = .04
    return point.point_id


class BranchMidpointReorderTests(BlenderTestCase):
    def setUp(self):
        super().setUp()
        self.root, self.muscle, self.connection, self.fibers = create_fixture()
        self.main = self.fibers[0]
        self.roots = [r.point_id for r in self.connection.roots]
        self.wrapper = self.muscle.fiber_surface_id
        select_only(self.root)

    def move(self, fiber, index, target):
        with patch.object(fiber_tools, '_sync_entity') as sync:
            result = fiber_tools.move_fiber_touch_point(bpy.context, fiber.id, index, target-index)
        return result, sync

    def test_routing_guide_moves_across_roots_preserving_native_branch(self):
        key = append_route(self.main, self.main.mid_touches[0]); connection = self.connection.id
        result, sync = self.move(self.main, 2, 0)
        self.assertTrue(result.ok, result.message)
        self.assertEqual([p.point_id for p in self.main.mid_touches], [key, *self.roots])
        self.assertEqual([f.a_point_id for f in self.fibers[2:]], self.roots)
        self.assertEqual([r.point_id for r in self.connection.roots], self.roots)
        self.assertEqual(self.connection.id, connection); self.assertEqual(self.muscle.fiber_surface_id, self.wrapper)
        self.assertAlmostEqual(self.main.mid_touches[0].normal_offset, .04)
        sync.assert_called_once_with(self.root, bpy.context.scene, 'FIBER', {self.main.id}, bake=False)
        self.assertIn((self.main.id, 2), muscle_branch.protected_references(self.root))
        result, _ = self.move(self.main, 0, 2)
        self.assertTrue(result.ok); self.assertEqual([p.point_id for p in self.main.mid_touches], [*self.roots, key])

    def test_protected_root_move_is_rejected_without_mutation(self):
        append_route(self.main, self.main.mid_touches[0]); before = native_records(self.root)
        result, sync = self.move(self.main, 0, 2)
        self.assertFalse(result.ok); self.assertEqual(native_records(self.root), before)
        sync.assert_not_called()

    def test_child_routing_guides_can_move_without_unlinking_start(self):
        child = self.fibers[2]; first = append_route(child, self.main.mid_touches[0])
        last = append_route(child, self.main.mid_touches[1])
        result, sync = self.move(child, 1, 0)
        self.assertTrue(result.ok, result.message)
        self.assertEqual([p.point_id for p in child.mid_touches], [last, first])
        self.assertEqual(child.a_point_id, self.roots[0]); self.assertEqual(self.muscle.fiber_surface_id, self.wrapper)
        sync.assert_called_once_with(self.root, bpy.context.scene, 'FIBER', {child.id}, bake=False)

    def test_invalid_root_order_is_not_silently_accepted(self):
        append_route(self.main, self.main.mid_touches[0])
        with suppress_vcp_prop_updates(): self.main.mid_touches.move(0, 1)
        before = native_records(self.root); result, sync = self.move(self.main, 2, 0)
        self.assertFalse(result.ok); self.assertEqual(native_records(self.root), before)
        sync.assert_not_called()

    def test_overlapping_shared_intervals_reject_routing_move(self):
        append_route(self.main, self.main.mid_touches[0])
        with suppress_vcp_prop_updates():
            wrapper = muscle_branch.muscle_surface(self.root, self.muscle); other = wrapper.branches.add()
            other.id, other.surface_id, other.boundary_fiber_id = 'OVERLAP', self.connection.surface_id, self.main.id
            for key in self.roots: other.roots.add().point_id = key
        before = native_records(self.root); result, sync = self.move(self.main, 2, 0)
        self.assertFalse(result.ok); self.assertEqual(native_records(self.root), before)
        sync.assert_not_called()

    def test_missing_shared_root_rejects_routing_move(self):
        append_route(self.main, self.main.mid_touches[0])
        with suppress_vcp_prop_updates(): self.connection.roots[0].point_id = 'MISSING'
        before = native_records(self.root); result, sync = self.move(self.main, 2, 0)
        self.assertFalse(result.ok); self.assertEqual(native_records(self.root), before)
        sync.assert_not_called()
