"""Loops, touches, shared edits and explicit mirrored rows on actual muscle geometry."""
import os
from math import sin, pi
from unittest.mock import patch
import bpy
from mathutils import Vector
from _helpers import BlenderTestCase, find_flagged
from test_muscle_parent_fibers import parent_fixture, arched_fiber
from anthroforge.core.vcp import attachment_backend as binding
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.visualization.fiber_sync import register_fiber_sync
from anthroforge.core.visualization.fiber_refinement import request_fiber_refinement, drain_fiber_refinements
from anthroforge.app.use_cases import free_fiber, fiber_attachment


def loop_fixture(free):
    owner, _muscle, surface, parent = parent_fixture(); fiber, _points = arched_fiber(owner, surface, parent)
    queries = [(1.1,.3,1), (1.55,.3,1), (1.55,.7,1), (1.1,.7,1)]; anchors = []
    with suppress_vcp_prop_updates():
        fiber.topology_mode = 'LOOP'; fiber.node_count = 32
        for query in queries:
            row = fiber.loop_anchors.add(); row.parent_id = parent
            row.attach_param = binding.capture_attachment_from_world(owner, bpy.context.scene, parent, Vector(query))
            anchors.append(binding.resolve_attachment_world(owner, bpy.context.scene, parent, row.attach_param))
    points = [a.lerp(b, i/8) + Vector((0,0,.2*sin(pi*i/8))) for a,b in zip(anchors, anchors[1:]+anchors[:1]) for i in range(8)]
    register_fiber_sync().apply_points(owner, bpy.context.scene, fiber, points, commit=True)
    if free: free_fiber.configure_mode(owner, bpy.context.scene, fiber, 'FREE')
    else: solve(owner, fiber)
    return owner, surface, fiber


def solve(owner, fiber):
    with patch.dict(os.environ, {'AF_FIBER_ENGINE': 'V3'}):
        result = request_fiber_refinement(owner, bpy.context.scene, fiber, quality='FINAL')
        assert result.ok, result.error
        drain_fiber_refinements()
    proxy = find_flagged('af_fiber_proxy', fiber.id, 'af_fiber_id')
    assert proxy.get('af_fiber_output_state') == 'CURRENT', fiber.get('_af_rt_invalid_reason')


class MuscleParentModeTests(BlenderTestCase):
    def test_free_loop_retains_closure_and_all_anchors(self):
        from anthroforge.core.visualization.free_fiber_runtime import current, anchor_points
        from anthroforge.core.vcp.free_path import tagged_indices
        owner, surface, fiber = loop_fixture(True); raw = fiber.node_attachments_json
        for vertex in surface.data.vertices: vertex.co.z += .02
        surface.data.update(); bpy.context.view_layer.update()
        payload, points = current(owner, bpy.context.scene, fiber)
        for i, p in zip(tagged_indices(payload), anchor_points(owner, bpy.context.scene, fiber)):
            self.assertLess((points[i]-p).length, 1e-5)
        self.assertEqual(raw, fiber.node_attachments_json)

    def test_controlled_loop_and_intermediate_touch_use_native_v3(self):
        owner, surface, fiber = loop_fixture(False)
        self.assertTrue(fiber.node_attachments_json)
        parent = fiber.loop_anchors[0].parent_id
        item, _points = arched_fiber(owner, surface, parent)
        with suppress_vcp_prop_updates():
            touch = item.mid_touches.add(); touch.parent_id = parent
            touch.attach_param = binding.capture_attachment_from_world(owner, bpy.context.scene, parent, Vector((1.3,.5,1)))
        solve(owner, item)
        self.assertTrue(item.node_attachments_json)

    def test_shared_free_point_assignment_updates_both_pairing_digests(self):
        from anthroforge.core.vcp.shared_point_storage import point_record
        from anthroforge.core.visualization.free_fiber_runtime import current
        owner, _muscle, surface, parent = parent_fixture(); first, points = arched_fiber(owner, surface, parent)
        first_id = first.id; second, _ = arched_fiber(owner, surface, parent)
        first = next(f for f in owner.af_vcp_system.fibers if f.id == first_id)
        with suppress_vcp_prop_updates(): second.a_point_id = first.a_point_id
        for f in (first, second): free_fiber.configure_mode(owner, bpy.context.scene, f, 'FREE')
        point = point_record(first, 'a_point_id'); previous = [f.free_path_json for f in (first, second)]
        fiber_attachment.assign(owner, bpy.context.scene, point, parent, points[0] + Vector((.02,0,0)))
        self.assertNotEqual(previous, [f.free_path_json for f in (first, second)])
        self.assertEqual(first.a_point_id, second.a_point_id)
        self.assertLess((current(owner, bpy.context.scene, first)[1][0]-current(owner, bpy.context.scene, second)[1][0]).length, 1e-5)

    def test_use_mirrored_rows_consumes_asymmetric_evaluated_points(self):
        from test_muscle_parent_instances import fixture
        from anthroforge.core.visualization.muscle_sync_runtime import collect_surface_rows
        owner, tissue, children = fixture()
        surface = next(s for s in owner.af_vcp_system.fiber_surfaces if s.id == tissue.base_source_id)
        with suppress_vcp_prop_updates(): surface.use_mirrored_rows = True
        rows = collect_surface_rows(owner, bpy.context.scene, surface, children)
        self.assertEqual(len(rows), 4)
        self.assertAlmostEqual(rows[0][0].z-rows[-1][0].z, .25, places=5)
