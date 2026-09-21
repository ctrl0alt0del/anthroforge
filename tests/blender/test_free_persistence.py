from unittest.mock import patch
import bpy
import numpy as np
from _helpers import BlenderTestCase
from test_free_fibers import fixture
from anthroforge.app.use_cases import free_fiber as service
from anthroforge.core.visualization import free_fiber_runtime as runtime
from anthroforge.core.importing.extract import root_snapshot
from anthroforge.core.importing.vcp import apply_vcp_snapshot
from anthroforge.core.vcp import free_path


def capture_and_publish(owner, ids=None):
    from anthroforge.core.visualization.fiber_node_attachment_runtime import capture_missing_fiber_node_attachments, apply_fiber_node_attachments
    capture_missing_fiber_node_attachments(owner, bpy.context.scene, ids)
    apply_fiber_node_attachments(owner, bpy.context.scene, ids)


class FreePersistenceTests(BlenderTestCase):
    def test_mixed_branch_import_preserves_shared_graph_and_actual_geometry(self):
        from _branch_fixture import create_fixture
        from anthroforge.core.visualization.muscle_numeric_runtime import _branched_request
        from anthroforge.core.vcp.branched_numeric import evaluate
        owner, muscle, _connection, fibers = create_fixture()
        capture_and_publish(owner)
        for item in (fibers[0], fibers[2]): service.configure_mode(owner, bpy.context.scene, item, 'FREE')
        before = evaluate(_branched_request(owner, bpy.context.scene, muscle), 'NATIVE')
        result = apply_vcp_snapshot(root_snapshot(owner), owner, bpy.context)
        self.assertEqual(result.fiber_count, 4)
        capture_and_publish(owner, {f.id for f in list(owner.af_vcp_system.fibers)[-4:]})
        copied = owner.af_vcp_system.muscles[-1]; after = evaluate(_branched_request(owner, bpy.context.scene, copied), 'NATIVE')
        self.assertFalse(after.error, after.error)
        np.testing.assert_allclose(before.base_vertices, after.base_vertices, atol=1e-6)
        np.testing.assert_allclose(before.inflated_vertices, after.inflated_vertices, atol=1e-6)

    def test_import_remaps_graph_samples_and_destination_coordinates_without_solver(self):
        owner, _surface, item, points = fixture(); service.configure_mode(owner, bpy.context.scene, item, 'FREE')
        snapshot = root_snapshot(owner); original = free_path.decode(item.free_path_json)
        with patch('anthroforge.core.visualization.fiber_refinement.begin_fiber_solve', side_effect=AssertionError('solver')):
            result = apply_vcp_snapshot(snapshot, owner, bpy.context)
        self.assertEqual(result.fiber_count, 1); duplicate = owner.af_vcp_system.fibers[-1]
        payload, actual = runtime.current(owner, bpy.context.scene, duplicate)
        np.testing.assert_allclose(actual, points, atol=1e-6)
        self.assertNotEqual(item.a_point_id, duplicate.a_point_id)
        self.assertNotEqual(original['samples'][0]['sample_id'], payload['samples'][0]['sample_id'])
        self.assertNotEqual(original['structural'][0]['occurrence_id'], payload['structural'][0]['occurrence_id'])

    def test_missing_import_reference_fails_before_partial_writes(self):
        owner, _surface, item, _points = fixture(); service.configure_mode(owner, bpy.context.scene, item, 'FREE')
        snapshot = root_snapshot(owner); snapshot.branching['points'][0]['parent_id'] = 'MISSING'
        before = len(owner.af_vcp_system.fibers), len(owner.af_vcp_system.authored_points)
        with self.assertRaisesRegex(ValueError, 'missing required SCP'): apply_vcp_snapshot(snapshot, owner, bpy.context)
        self.assertEqual(before, (len(owner.af_vcp_system.fibers), len(owner.af_vcp_system.authored_points)))

    def test_scp_duplicate_keeps_original_binding_and_allocates_new_graph(self):
        from anthroforge.core.scp_runtime.copy import copy_scp_subtree
        owner, _surface, item, points = fixture(); service.configure_mode(owner, bpy.context.scene, item, 'FREE')
        original = item.a_parent_id, item.a_attach_param, item.free_path_json
        copied = copy_scp_subtree(owner, bpy.context.scene, item.a_parent_id)
        self.assertTrue(copied); duplicate = owner.af_vcp_system.fibers[-1]
        self.assertEqual(original, (item.a_parent_id, item.a_attach_param, item.free_path_json))
        self.assertEqual(duplicate.a_parent_id, copied); self.assertNotEqual(item.a_point_id, duplicate.a_point_id)
        np.testing.assert_allclose(runtime.current(owner, bpy.context.scene, duplicate)[1], points, atol=1e-6)
