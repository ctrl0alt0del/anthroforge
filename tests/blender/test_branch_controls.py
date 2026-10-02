import bpy
from types import SimpleNamespace
from unittest.mock import patch
from mathutils import Vector
from _helpers import BlenderTestCase
from _branch_fixture import create_fixture
from anthroforge.core.visualization.muscle_sync import register_muscle_sync
from anthroforge.core.visualization.muscle_numeric_runtime import _branched_request, _sync_control
from anthroforge.core.visualization.branch_control import selected_part, snapped_control
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates


class BranchControlTests(BlenderTestCase):
    def test_boundary_metric_cache_reuses_shape_edits_but_not_geometry_edits(self):
        import numpy as np
        from anthroforge.core.vcp.prepared_inflation import boundary_distances, boundary_masks
        request = _branched_request(self.root, bpy.context.scene, self.muscle)
        grid, mask = request.assembly.main, boundary_masks(request.assembly)[0]
        first = boundary_distances(grid, mask)
        self.assertIs(first, boundary_distances(grid.copy(), mask.copy()))
        changed = boundary_distances(grid*2., mask)
        self.assertIsNot(first, changed)
        np.testing.assert_allclose(changed, 2*first)
        self.assertFalse(first.flags.writeable)

    def setUp(self):
        super().setUp()
        self.root, self.muscle, self.connection, _ = create_fixture()
        self.sync = register_muscle_sync()
        self.collection = bpy.data.collections.new('AF_VCP_VIS')
        bpy.context.scene.collection.children.link(self.collection)

    def _control(self):
        with suppress_vcp_prop_updates():
            self.connection.settings.inflation_mode = 'CTRL_POINT'
        request = _branched_request(self.root, bpy.context.scene, self.muscle)
        work = SimpleNamespace(muscle=self.muscle, request=request, base_obj=None)
        with patch.object(self.sync, '_selected_muscle_id', return_value=self.muscle.id):
            _sync_control(self.sync, self.collection, self.root, bpy.context.scene, self.root.af_vcp_system, work, None)
        return self.sync._find_inflation_ctrl(self.collection, self.root.name, self.muscle.id)

    def test_selected_branch_control_is_tagged_and_initialized(self):
        control = self._control()
        self.assertEqual(control['af_muscle_branch_id'], self.connection.id)
        self.assertTrue(self.connection.settings.inflation_ctrl_initialized)
        self.assertEqual(selected_part(self.root, self.muscle)[1], self.connection.id)
        target = Vector((3, .75, .4))
        point = snapped_control(self.root, bpy.context.scene, self.muscle, control, target)
        self.assertAlmostEqual(point.x, 2, places=5)
        self.assertAlmostEqual(point.z, .4, places=5)

    def test_control_edit_changes_branch_only(self):
        control = self._control()
        base, _ = self.sync._ensure_muscle_meshes(self.collection, self.root, self.muscle.id)
        before = tuple(self.muscle.inflation_ctrl_world)
        control.location = (3, .75, .4)
        dirty = set()
        with suppress_vcp_prop_updates():
            changed = self.sync._process_inflation_ctrl_update(self.root, self.collection, control, dirty)
        self.assertTrue(changed)
        self.assertEqual(dirty, {self.muscle.id})
        self.assertEqual(tuple(self.muscle.inflation_ctrl_world), before)
        self.assertAlmostEqual(self.connection.settings.inflation_ctrl_world[2], .4, places=5)

    def test_return_to_same_branch_retires_pending_input(self):
        from anthroforge.core.deps import muscle_control_intents as inputs
        from anthroforge.core.visualization.muscle_numeric_runtime import _bind_control
        from anthroforge.core.visualization import sync_runner as runner
        control = self._control(); previous = tuple(control.location)
        control.location = (3, .75, .4)
        old = inputs.reserve_input(self.root, bpy.context.scene, control)
        inputs.dispatch_input(self.root, bpy.context.scene, old, deferred=True)
        _bind_control(self.sync, self.collection, self.root, self.muscle.id, '', 'A')
        _bind_control(self.sync, self.collection, self.root, self.muscle.id, self.connection.id, 'A')
        inputs.write_control(self.root, bpy.context.scene, control, previous)
        self.assertIsNone(inputs.input_record(old))
        runner._flush_pending()
        self.assertEqual(tuple(control.location), previous)
