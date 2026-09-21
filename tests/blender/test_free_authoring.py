import tempfile
from pathlib import Path
from unittest.mock import patch
import bpy
import copy
import numpy as np
from _helpers import BlenderTestCase
from test_free_fibers import fixture
from anthroforge.app.authoring.api import execute
from anthroforge.adapters.authoring.inventory import capture
from anthroforge.app.use_cases import free_fiber as service
from anthroforge.core.visualization import free_fiber_runtime as runtime


def request(owner, operation, **params):
    return dict(version='0.4.0', message_type='request', request_id='request-' + operation,
                op=operation, params=dict(scene_id=owner.name, **params))


def creation(owner, item, points):
    payload = service.payload_for_points(owner, bpy.context.scene, item, points)
    value = dict(representation='POLY', space='WORLD', samples=payload['samples'], structural=payload['structural'])
    return request(owner, 'fibers.create_free', expected_scene_revision=capture(owner, bpy.context.scene)['revision'],
                   attachments=[dict(point_id=row['point_id']) for row in payload['structural']], path=value)


class FreeAuthoringTests(BlenderTestCase):
    def test_journal_failure_restores_native_records_and_live_generated_geometry(self):
        from anthroforge.core.authoring.storage import FileStore
        owner, _surface, item, points = fixture(); value = creation(owner, item, points)
        before = capture(owner, bpy.context.scene)['revision']
        original = FileStore.put
        def fail_receipt(store, category, key, row):
            if category == 'free_path_requests': raise OSError('Injected final journal write failure')
            return original(store, category, key, row)
        with tempfile.TemporaryDirectory() as folder, patch.object(FileStore, 'put', new=fail_receipt):
            result = execute(value, owner, bpy.context.scene, folder)
        self.assertNotEqual(result['status'], 'success'); self.assertEqual(capture(owner, bpy.context.scene)['revision'], before)
        self.assertEqual(len(owner.af_vcp_system.fibers), 1)
        self.assertFalse(owner.get('af_free_receipts')); self.assertFalse(owner.get('af_authoring_journal'))

    def test_guarded_update_and_stale_receipt_preserve_live_path(self):
        owner, surface, item, points = fixture(); service.configure_mode(owner, bpy.context.scene, item, 'FREE')
        path = copy.deepcopy(runtime.current(owner, bpy.context.scene, item)[0]); path['samples'][1]['co'][2] += .2
        value = request(owner, 'fibers.path_update', fiber_id=item.id, expected_path_revision=item.free_path_revision,
                        expected_scene_revision=capture(owner, bpy.context.scene)['revision'],
                        path=dict(representation='POLY', space='ROOT_LOCAL', samples=path['samples'], structural=path['structural']))
        with tempfile.TemporaryDirectory() as folder, patch('anthroforge.core.visualization.fiber_refinement.begin_fiber_solve', side_effect=AssertionError('solver')):
            result = execute(value, owner, bpy.context.scene, folder); self.assertEqual(result['status'], 'success', result)
            self.assertTrue(execute(value, owner, bpy.context.scene, folder)['replayed'])
            self.assertAlmostEqual(runtime.current(owner, bpy.context.scene, item)[1][1].z, .5, places=5)
            surface.location.z = .3; bpy.context.view_layer.update(); before = item.free_path_json
            stale = execute(value, owner, bpy.context.scene, folder)
            self.assertIn('STALE_FREE_PATH_RECEIPT', str(stale)); self.assertEqual(before, item.free_path_json)

    def test_bezier_authoring_retains_structural_tags_and_independent_sample_count(self):
        owner, _surface, item, points = fixture(); value = creation(owner, item, points)
        path = value['params']['path']; rows = path.pop('samples')
        path.update(representation='BEZIER', resolution=32,
                    knots=[dict(sample_id=r['sample_id'], co=r['co'], handle_left=r['co'], handle_right=r['co']) for r in rows])
        with tempfile.TemporaryDirectory() as folder: result = execute(value, owner, bpy.context.scene, folder)
        self.assertEqual(result['status'], 'success', result); created = owner.af_vcp_system.fibers[-1]
        payload, actual = runtime.current(owner, bpy.context.scene, created)
        self.assertEqual(len(actual), 32); self.assertEqual(created.node_count, 64)
        self.assertEqual(payload['structural'], path['structural'])
        np.testing.assert_allclose([actual[0], actual[-1]], [points[0], points[-1]], atol=1e-6)

    def test_request_id_conflict_and_changed_structural_tags_reject_atomically(self):
        owner, _surface, item, points = fixture(); value = creation(owner, item, points)
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(execute(value, owner, bpy.context.scene, folder)['status'], 'success')
            before = capture(owner, bpy.context.scene)['revision']; value['params']['name'] = 'Reused ID'
            self.assertIn('REQUEST_ID_REUSED', str(execute(value, owner, bpy.context.scene, folder)))
            self.assertEqual(capture(owner, bpy.context.scene)['revision'], before)

    def test_direct_creation_update_and_replay_no_solver(self):
        owner, _surface, item, points = fixture(); value = creation(owner, item, points)
        with tempfile.TemporaryDirectory() as folder, patch('anthroforge.core.visualization.fiber_refinement.begin_fiber_solve', side_effect=AssertionError('solver')):
            result = execute(value, owner, bpy.context.scene, folder)
            self.assertEqual(result['status'], 'success', result)
            self.assertTrue(execute(value, owner, bpy.context.scene, folder)['replayed'])
            created = owner.af_vcp_system.fibers[-1]; self.assertEqual(created.behavior_mode, 'FREE')
            self.assertEqual(len(runtime.current(owner, bpy.context.scene, created)[1]), 4)
            self.assertTrue(list(Path(folder).rglob('*.json')))

    def test_invalid_creation_rolls_back_all_records(self):
        owner, _surface, item, points = fixture(); value = creation(owner, item, points)
        value['params']['path']['samples'][1]['co'] = value['params']['path']['samples'][0]['co']
        before = capture(owner, bpy.context.scene)['revision']
        with tempfile.TemporaryDirectory() as folder: result = execute(value, owner, bpy.context.scene, folder)
        self.assertEqual(result['status'], 'unresolved', result)
        self.assertEqual(len(owner.af_vcp_system.fibers), 1)
        self.assertEqual(capture(owner, bpy.context.scene)['revision'], before)
