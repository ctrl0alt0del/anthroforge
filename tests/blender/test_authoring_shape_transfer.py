"""Production shape transfer through preview, publication, replay and persistence."""
import copy
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import bpy
import numpy as np
from _helpers import BlenderTestCase, root
from _transfer_fixture import fixture, message, read_preview, snapshot
from anthroforge.app.authoring.api import execute
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.adapters.authoring.inventory import geometry_for
from anthroforge.core.authoring.schema import validate
from anthroforge.core.authoring.storage import FileStore


class ShapeTransferTests(BlenderTestCase):
    def setUp(self):
        super().setUp(); folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.folder, self.root = folder.name, root(); self.fixture = fixture(self.root, self.folder)
        self.params = copy.deepcopy(self.fixture['params'])
        sources = self.send('transfer_sources', source_objects=self.params['source_objects'])['transfer']['meshes']
        bands = [dict(source_object=r['object'], topology_digest=r['topology_digest'], geometry_digest=r['geometry_digest'], vertex_indices=[0, 1]) for r in sources]
        self.params['shape_preservation'] = dict(family_id='synthetic_two_heads', protected_bands=bands,
            obstacle_instance_ids=[self.fixture['owner']], tolerance=1e-4, validation_samples=64, settings=dict(max_iterations=4))

    def send(self, operation, **params):
        result = execute(message(self.root, operation, **params), self.root, bpy.context.scene, self.folder)
        validate(result, 'protocol'); return result

    def preview(self, params=None):
        result = self.send('transfer_preview', **(self.params if params is None else params))
        self.assertIn(result['status'], ('success', 'unresolved'), result)
        return result

    def test_joint_fit_reports_final_quality_and_keeps_bands(self):
        before = snapshot(self.root); objects = set(bpy.data.objects); result = self.preview(); record = read_preview(result)['result']
        self.assertEqual(record['method'], 'shared_cubic_rbf_shape_clearance.v1')
        self.assertEqual(record['shape_preservation']['protected_max_displacement'], 0.)
        self.assertEqual(len(record['meshes']), 2); self.assertEqual(set(bpy.data.objects), objects)
        self.assertEqual(before, snapshot(self.root)); self.assertFalse(record['shape_preservation']['clearance_certificate'])
        for row in record['meshes']:
            self.assertNotIn('min_normalized_jacobian', row['quality'])
            self.assertIn('min_normalized_jacobian', row['initial_field_quality'])
        self.assertEqual(record['field_role'], 'initial_skeletal_guide_only')

    def test_replay_save_reopen_and_edited_output_detection(self):
        preview = self.preview(); params = dict(preview_id=preview['transfer']['preview_id'])
        first = self.send('transfer_publish', **params); second = self.send('transfer_publish', **params)
        self.assertTrue(first['published'], first); self.assertTrue(second['transfer']['reused'], second)
        name = first['transfer']['objects'][0]['name']; original = geometry_for(bpy.data.objects[name]); root_name = self.root.name
        path = Path(self.folder)/'shape.blend'; StaticScene(self.root, bpy.context.scene).save_debug_copy(path)
        bpy.ops.wm.open_mainfile(filepath=str(path)); self.root = bpy.data.objects[root_name]
        self.assertEqual(geometry_for(bpy.data.objects[name]), original)
        obj = bpy.data.objects[name]; self.assertFalse(obj.hide_get()); self.assertEqual(obj.display_type, 'TEXTURED')
        collection = bpy.data.collections[first['transfer']['collection']]; manifest = json.loads(collection['af_transfer_manifest'])
        self.assertEqual(manifest['shape_preservation']['family_id'], 'synthetic_two_heads')
        obj.location.z += .01
        self.assertEqual(self.send('transfer_publish', **params)['diagnostics'][0]['code'], 'TRANSFER_REVIEW_EDITED')

    def test_stale_bands_bad_indices_missing_parts_and_settings_rejected(self):
        for key, value, expected in [('geometry_digest', 'stale', 'STALE_TRANSFER_SOURCE'),
                                    ('vertex_indices', [999999], 'TRANSFER_SHAPE_INDEX')]:
            params = copy.deepcopy(self.params); params['shape_preservation']['protected_bands'][0][key] = value
            self.assertEqual(self.send('transfer_preview', **params)['diagnostics'][0]['code'], expected)
        params = copy.deepcopy(self.params); params['shape_preservation']['protected_bands'].pop()
        self.assertEqual(self.send('transfer_preview', **params)['diagnostics'][0]['code'], 'TRANSFER_SHAPE_MISSING_PART_BAND')
        params = copy.deepcopy(self.params); params['shape_preservation']['settings']['guess'] = True
        self.assertEqual(self.send('transfer_preview', **params)['diagnostics'][0]['code'], 'SCHEMA_UNKNOWN_FIELD')

    def test_changed_obstacle_blocks_publication(self):
        preview = self.preview(); bpy.data.objects[self.fixture['target']].location.x += .01
        result = self.send('transfer_publish', preview_id=preview['transfer']['preview_id'])
        self.assertEqual(result['diagnostics'][0]['code'], 'STALE_SCENE_REVISION')

    def test_publication_failure_rolls_back(self):
        preview = self.preview(); objects = set(bpy.data.objects); put = FileStore.put
        def fail(store, category, key, value):
            if category == 'transfer_requests': raise OSError('Injected write failure')
            return put(store, category, key, value)
        with patch.object(FileStore, 'put', fail):
            result = self.send('transfer_publish', preview_id=preview['transfer']['preview_id'])
        self.assertEqual(result['status'], 'failed'); self.assertEqual(set(bpy.data.objects), objects)

    def test_preview_replays_without_recalculating(self):
        payload = message(self.root, 'transfer_preview', **self.params)
        first = execute(payload, self.root, bpy.context.scene, self.folder)
        with patch.object(StaticScene, 'shape_transfer', side_effect=AssertionError('Recalculated')):
            second = execute(payload, self.root, bpy.context.scene, self.folder)
        self.assertTrue(second['replayed']); self.assertEqual(first['transfer'], second['transfer'])

    def test_json_integral_numbers_follow_integer_schema_semantics(self):
        params = copy.deepcopy(self.params); spec = params['shape_preservation']
        spec['validation_samples'] = 64.0; spec['settings']['max_iterations'] = 1.0
        for band in spec['protected_bands']: band['vertex_indices'] = [0.0, 1.0]
        result = self.preview(params)
        self.assertEqual(result['transfer']['shape_preservation']['fitting']['iterations'], 1)
