"""Pass-local indexing, unchanged publication, and worker lifecycle regressions."""
from types import SimpleNamespace
from unittest.mock import patch
import bpy
import time
from _helpers import BlenderTestCase, root
from test_muscle_section_profile import fixture
from test_warning_repository import drain
from test_fiber_anchor_preflight import _scene_fixture
from anthroforge.core.visualization import warning_pipeline as pipeline, warning_runtime as runtime
from anthroforge.core.visualization import muscle_sync_helpers as helpers
from anthroforge.core.visualization.muscle_sync import register_muscle_sync
from anthroforge.core.visualization.vcp_object_index import build_muscle_object_index
from anthroforge.core.visualization.delete_reconcile import DeleteReconcileRuntime, _owner_keys
from anthroforge.core.warnings import session


def run_to_submission():
    deadline = time.perf_counter()+5
    while time.perf_counter() < deadline:
        session.COORDINATOR.tick(max_steps=1)
        if pipeline.executor().job is not None: return
        time.sleep(.001)
    raise AssertionError('Warning snapshot not submitted')


class RebuildOptimizationTests(BlenderTestCase):
    def test_rescan_changes_overlay_cache_revision(self):
        from anthroforge.core.warnings.anchors import current
        owner, _blocker, _scp, fiber = _scene_fixture()
        runtime.schedule_root(bpy.context.scene, owner); drain()
        before = current(bpy.context.scene, owner, fiber).cache_key
        runtime.schedule_root(bpy.context.scene, owner); drain()
        self.assertNotEqual(current(bpy.context.scene, owner, fiber).cache_key, before)

    def test_free_control_initialization_preserves_vector_rounding(self):
        import numpy as np
        from mathutils import Vector
        from anthroforge.core.vcp import free_muscle_numeric as numeric
        from anthroforge.core.vcp.muscle_numeric import make_muscle_request
        from test_muscle_numeric_backends import _spec
        from dataclasses import replace
        grid = np.asarray([[(j+.123456789, i+.987654321, .123456789) for j in range(3)] for i in range(2)])
        request = make_muscle_request('M', grid, replace(_spec('CTRL_POINT'), initialize_control=True, preserve_samples=True))
        with patch.object(numeric, '_native', return_value=grid.copy()) as inflate:
            numeric._evaluate(request, 'NATIVE')
        self.assertEqual(inflate.call_args.args[1].control_world, tuple(Vector(grid[1, 1])))

    def test_control_absence_creation_and_removal_share_one_index(self):
        owner = root(); sync = register_muscle_sync(); collection = sync._get_vis_collection(bpy.context.scene)
        sync._object_index = build_muscle_object_index(bpy.context.scene, owner.name)
        try:
            with patch.object(helpers, '_find_inflation_ctrl_global', side_effect=AssertionError('global rescan')):
                self.assertIsNone(sync._find_inflation_ctrl(collection, owner.name, 'M'))
                control = sync._create_inflation_ctrl(collection, owner, 'M')
                self.assertEqual(sync._find_inflation_ctrl(collection, owner.name, 'M'), control)
                sync._remove_ctrl_obj(control)
                self.assertIsNone(sync._find_inflation_ctrl(collection, owner.name, 'M'))
        finally: sync._object_index = None

    def test_unchanged_profile_does_not_rewrite_mesh(self):
        from anthroforge.core.visualization import fiber_sync_helpers as fiber_helpers
        owner, _surface, muscle = fixture(); sync = register_muscle_sync()
        with patch.object(sync, '_update_mesh', side_effect=AssertionError('unchanged publication')), \
             patch.object(fiber_helpers, '_fiber_proxy', side_effect=AssertionError('source scene rescan')):
            sync.sync_root_to_scene(owner, bpy.context.scene, {muscle.id})

    def test_same_count_object_replacement_updates_owner_index(self):
        owner = root(); scene = bpy.context.scene; cache = DeleteReconcileRuntime(); key = (1, 2)
        old = bpy.data.objects.new('old', None); scene.collection.objects.link(old)
        old['af_root_name'], old['af_fiber_proxy'], old['af_fiber_id'] = owner.name, True, 'A'
        cache._indexed_owners(scene, owner, key, None); bpy.data.objects.remove(old, do_unlink=True)
        new = bpy.data.objects.new('new', None); scene.collection.objects.link(new)
        new['af_root_name'], new['af_fiber_proxy'], new['af_fiber_id'] = owner.name, True, 'B'
        self.assertEqual(cache._indexed_owners(scene, owner, key, SimpleNamespace(updates=())), _owner_keys(scene, owner.name))

    def test_epoch_reset_cancels_submitted_snapshot_and_cannot_publish(self):
        owner, _blocker, _scp, fiber = _scene_fixture()
        runtime.schedule_root(bpy.context.scene, owner); run_to_submission()
        epoch = session.EPOCH; runtime.before_change(None)
        self.assertNotEqual(epoch, session.EPOCH); self.assertFalse(session.REPOSITORY.records)
        runtime.schedule_root(bpy.context.scene, owner); drain()
        self.assertTrue(session.REPOSITORY.records)
        self.assertTrue(all(row.entity.epoch == session.EPOCH for row in session.REPOSITORY.records.values()))

    def test_newer_edit_cancels_submitted_warning_without_publication(self):
        owner, blocker, _scp, fiber = _scene_fixture()
        runtime.schedule_root(bpy.context.scene, owner); run_to_submission()
        blocker.location.x = 10; bpy.context.view_layer.update()
        runtime.schedule_root(bpy.context.scene, owner); drain()
        self.assertFalse(session.REPOSITORY.records)
        self.assertFalse(pipeline.reap())

    def test_rename_during_worker_keeps_attachment_identity(self):
        owner, _blocker, _scp, fiber = _scene_fixture()
        runtime.schedule_root(bpy.context.scene, owner); run_to_submission()
        fiber.name = 'Renamed'; drain()
        self.assertTrue(session.REPOSITORY.records)
        self.assertTrue(all(row.entity.label == 'Renamed' for row in session.REPOSITORY.records.values()))
