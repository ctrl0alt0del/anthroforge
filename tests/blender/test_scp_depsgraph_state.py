"""Regression coverage for dirty notifications that do not change attachment inputs."""
from types import SimpleNamespace
from unittest.mock import patch

import bpy

from _helpers import BlenderTestCase, add_shortcut, empty_object, mesh_object, root, scp_with_object
from anthroforge.core.deps.runtime_trace import clear_request_telemetry, request_telemetry, set_request_telemetry
from anthroforge.core.scp_runtime import depsgraph_state as state, sync_runtime as runtime
from anthroforge.core.visualization.sync import register_sync
from anthroforge.core.visualization import sync_runner
from test_shortcut_workflows import _attached_empty_pair, _geometry_nodes_setup


class ScpDepsgraphStateTests(BlenderTestCase):
    def setUp(self):
        super().setUp()
        guard = patch.object(register_sync(), '_syncing', True)
        guard.start(); self.addCleanup(guard.stop)
        self.addCleanup(sync_runner.clear_pending_runtime, keep_timer=False)
        self.root = root()
        self.obj = mesh_object('Source')
        self.scp = scp_with_object(self.root, 'Source', self.obj)
        bpy.context.view_layer.update()
        state.clear_scp_states()

    def observe(self, obj=None, root_obj=None, graph=None):
        bpy.context.view_layer.update()
        return state.observe_scp_state(root_obj or self.root, obj or self.obj,
                                       graph or bpy.context.view_layer.depsgraph)

    def changed_ids(self, obj=None, transform=False, geometry=True):
        bpy.context.view_layer.update()
        update = SimpleNamespace(id=obj or self.obj, is_updated_transform=transform, is_updated_geometry=geometry)
        changed, transformed, shaped = set(), set(), set()
        runtime._collect_update(self.root, bpy.context.view_layer.depsgraph, update, changed, transformed, shaped)
        return changed, transformed, shaped

    def test_repeated_geometry_flags_and_color_changes_do_not_propagate(self):
        self.assertEqual(self.changed_ids(), ({self.scp.id}, set(), {self.scp.id}))
        for _index in range(5):
            self.obj.update_tag(refresh={'DATA'})
            self.assertEqual(self.changed_ids(), (set(), set(), set()))
        self.obj.color = (0.1, 0.2, 0.3, 1)
        self.assertEqual(self.changed_ids(), (set(), set(), set()))

    def test_same_count_vertex_edit_propagates_once(self):
        self.observe()
        self.obj.data.vertices[1].co.x += 0.001
        self.obj.data.update()
        self.assertEqual(self.changed_ids(), ({self.scp.id}, set(), {self.scp.id}))
        self.assertEqual(self.changed_ids(), (set(), set(), set()))

    def test_same_count_topology_change_is_detected(self):
        self.observe()
        self.obj.data.flip_normals()
        self.obj.data.update()
        self.assertEqual(self.observe(), (False, True))
        self.assertEqual(self.observe(), (False, False))

    def test_identical_replacement_mesh_is_detected(self):
        self.observe()
        self.obj.data = self.obj.data.copy()
        self.assertEqual(self.observe(), (False, True))

    def test_evaluated_modifier_change_is_detected(self):
        modifier, key = _geometry_nodes_setup(self.obj)
        self.observe()
        modifier[key] = 0.2
        self.obj.update_tag(refresh={'OBJECT', 'DATA'})
        self.assertEqual(self.observe(), (False, True))
        self.assertAlmostEqual(self.obj.evaluated_get(bpy.context.view_layer.depsgraph).data.vertices[0].co.x, 0.2)
        self.assertEqual(self.observe(), (False, False))

    def test_tiny_real_transform_is_not_rounded_away(self):
        self.observe()
        self.obj.location.x += 1e-7
        self.assertEqual(self.changed_ids(transform=True), ({self.scp.id}, {self.scp.id}, {self.scp.id}))
        self.assertEqual(self.changed_ids(transform=True), (set(), set(), set()))

    def test_transform_only_object_does_not_require_mesh(self):
        obj = empty_object('Control')
        scp = scp_with_object(self.root, 'Control', obj, with_geometry=False)
        self.observe(obj)
        obj.location.z = 2.0
        self.assertEqual(self.changed_ids(obj, transform=True), ({scp.id}, {scp.id}, set()))
        self.assertEqual(self.changed_ids(obj, transform=True), (set(), set(), set()))

    def test_acknowledged_output_does_not_swallow_next_edit(self):
        state.remember_applied_scp_states(self.root, bpy.context.scene, {self.scp.id})
        self.assertEqual(self.changed_ids(transform=True), (set(), set(), set()))
        self.obj.location.x += 0.1
        self.assertEqual(self.changed_ids(transform=True), ({self.scp.id}, {self.scp.id}, {self.scp.id}))

    def test_acknowledgement_does_not_absorb_unrelated_edit(self):
        other = mesh_object('Unrelated')
        scp_with_object(self.root, 'Unrelated', other)
        self.observe(other)
        other.data.vertices[0].co.z = 1.0
        other.data.update(); bpy.context.view_layer.update()
        state.remember_applied_scp_states(self.root, bpy.context.scene, {self.scp.id})
        self.assertEqual(self.observe(other), (False, True))

    def test_state_is_scoped_to_root_object_and_view_layer(self):
        self.observe()
        other_root = empty_object('OtherRoot')
        self.assertEqual(self.observe(root_obj=other_root), (True, True))
        other = self.obj.copy(); bpy.context.scene.collection.objects.link(other)
        self.assertEqual(self.observe(other), (True, True))
        layer = bpy.context.scene.view_layers.new('OtherView')
        layer.update()
        self.assertEqual(self.observe(graph=layer.depsgraph), (True, True))
        self.assertEqual(self.observe(), (False, False))

    def test_unknown_or_unreadable_state_is_never_suppressed(self):
        self.observe()
        with patch.object(state, '_geometry_digest', side_effect=RuntimeError('evaluation unavailable')):
            self.assertEqual(self.observe(), (True, True))
            self.assertEqual(self.observe(), (True, True))
        self.assertEqual(self.observe(), (True, True))
        self.assertEqual(self.observe(), (False, False))

    def test_history_and_load_handlers_reset_state_and_unregister_cleanly(self):
        state.register_scp_states(); state.register_scp_states()
        for name in state._EVENTS:
            self.observe()
            self.assertEqual(list(getattr(bpy.app.handlers, name)).count(state.clear_scp_states), 1)
            state.clear_scp_states(None)
            self.assertEqual(self.observe(), (True, True))
        state.unregister_scp_states()
        self.assertFalse(state._STATES)
        self.assertTrue(all(state.clear_scp_states not in getattr(bpy.app.handlers, name) for name in state._EVENTS))
        state.register_scp_states()

    def test_evicted_state_is_rechecked(self):
        with patch.object(state, '_MAX_STATES', 1):
            self.observe()
            self.observe(root_obj=empty_object('OtherRoot'))
            self.assertEqual(len(state._STATES), 1)
            self.assertEqual(self.observe(), (True, True))


def drain_requests():
    for _index in range(5):
        bpy.context.view_layer.update()
        for item in sync_runner._PENDING: item.due_at = 0
        sync_runner._flush_pending()


class ScpDepsgraphPropagationTests(BlenderTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(set_request_telemetry, False)
        self.addCleanup(clear_request_telemetry)
        self.addCleanup(sync_runner.clear_pending_runtime, keep_timer=False)
        self.root = root()
        self.parent, self.child = _attached_empty_pair(self.root)
        obj = self.parent.transform_object_ref
        self.shortcut = add_shortcut(self.root, 'Parent X', 'SCP', self.parent.id,
                                    f'bpy.data.objects["{obj.name}"].location[0]')
        register_sync().sync_root_to_scene(self.root, bpy.context.scene)
        drain_requests()
        set_request_telemetry(True); clear_request_telemetry()

    def test_shortcut_output_settles_and_next_direct_transform_still_propagates(self):
        self.shortcut.proxy_float = 2.0
        drain_requests()
        self.assertAlmostEqual(self.child.transform_object_ref.location.x, 3.0)
        self.assertEqual([entry['source'] for entry in request_telemetry()], ['shortcut'])
        self.parent.transform_object_ref.location.x = 4.0
        drain_requests()
        self.assertAlmostEqual(self.child.transform_object_ref.location.x, 5.0)
        self.assertEqual([entry['source'] for entry in request_telemetry()], ['shortcut', 'depsgraph'])
        self.assertFalse(sync_runner._PENDING or sync_runner._TAIL_PENDING)

    def test_repeated_transform_tags_after_propagation_remain_idle(self):
        self.shortcut.proxy_float = 2.0
        drain_requests()
        clear_request_telemetry()
        for _index in range(3):
            self.parent.transform_object_ref.update_tag(refresh={'OBJECT'})
            self.child.transform_object_ref.update_tag(refresh={'OBJECT'})
            drain_requests()
        self.assertFalse(request_telemetry())
        self.assertAlmostEqual(self.child.transform_object_ref.location.x, 3.0)
        self.assertFalse(sync_runner._PENDING or sync_runner._TAIL_PENDING)
