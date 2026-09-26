"""Attachment bands bind to regions rather than freezing an RBF guess."""
import copy
import numpy as np
from test_authoring_shape_transfer import ShapeTransferTests
from _transfer_fixture import read_preview, message
from anthroforge.app.authoring.api import execute
import bpy


class TransferBandTests(ShapeTransferTests):
    def setUp(self):
        super().setUp(); spec = self.params['shape_preservation']
        target = copy.deepcopy(self.params['correspondences'][0]['target']); binding = target.pop('surface_binding')
        band = spec['protected_bands'].pop(0)
        band.update(id='origin', target=target, target_bindings=[binding, binding])
        spec['attachment_bands'] = [band]

    def test_target_band_replaces_initial_field_position(self):
        result = read_preview(self.preview())['result']; band = result['shape_preservation']['attachment_bands'][0]
        self.assertEqual(band['vertex_count'], 2); self.assertGreater(band['max_initial_target_error'], .01)
        self.assertEqual(band['max_final_target_error'], 0.)
        row = next(r for r in result['meshes'] if r['source_object'] == band['source_object'])
        np.testing.assert_allclose(np.array(row['vertices'])[band['vertex_indices']], band['targets'])

    def test_conflicts_and_count_rejected(self):
        params = copy.deepcopy(self.params); spec = params['shape_preservation']
        spec['attachment_bands'].append(dict(spec['attachment_bands'][0], id='overlap'))
        self.assertEqual(self.send('transfer_preview', **params)['diagnostics'][0]['code'], 'TRANSFER_BAND_OVERLAP')
        params = copy.deepcopy(self.params); params['shape_preservation']['attachment_bands'][0]['target_bindings'].pop()
        self.assertEqual(self.send('transfer_preview', **params)['diagnostics'][0]['code'], 'TRANSFER_BAND_TARGET_COUNT')

    def test_target_topology_and_region_checked(self):
        params = copy.deepcopy(self.params); params['shape_preservation']['attachment_bands'][0]['target']['topology_digest'] = 'stale'
        self.assertEqual(self.send('transfer_preview', **params)['diagnostics'][0]['code'], 'TRANSFER_TARGET_TOPOLOGY_CHANGED')

    def test_collapsed_target_face_reported_before_fitting(self):
        from anthroforge.adapters.authoring.inventory import geometry_for
        band = self.params['shape_preservation']['attachment_bands'][0]
        band['vertex_indices'] = geometry_for(bpy.data.objects[band['source_object']])['triangles'][0]
        band['target_bindings'] = [band['target_bindings'][0]]*3
        result = read_preview(self.preview())['result']
        self.assertIn(0, result['shape_preservation']['attachment_bands'][0]['target_collapsed_triangle_indices'])
        self.assertEqual(result['status'], 'unresolved')

    def test_frame_mapping_via_authoring(self):
        band = self.params['shape_preservation']['attachment_bands'][0]; band.pop('target_bindings')
        band['mapping'] = dict(source_frame=[[5, 0, 0], [6, 0, 0], [5, 1, 0]],
                               target_frame=[[0, 0, 0], [1, 0, 0], [0, 1, 0]], max_distance=10.)
        report = read_preview(self.preview())['result']['shape_preservation']['attachment_bands'][0]
        self.assertEqual(report['method'], 'bone_frame_nearest_region.v1')
        self.assertEqual(report['max_final_target_error'], 0.)

    def test_attachment_only_draft_change_blocks_replay_and_publish(self):
        document = copy.deepcopy(self.fixture['document']); document['document_id'] = 'attachment_only'
        self.assertEqual(self.send('draft', document_id=document['document_id'], expected_draft_revision=0, document=document)['status'], 'success')
        self.params['shape_preservation']['attachment_bands'][0]['target']['document_id'] = document['document_id']
        payload = message(self.root, 'transfer_preview', **self.params)
        first = execute(payload, self.root, bpy.context.scene, self.folder)
        self.assertEqual(self.send('draft', document_id=document['document_id'], expected_draft_revision=1, document=document)['status'], 'success')
        replay = execute(payload, self.root, bpy.context.scene, self.folder)
        self.assertEqual(replay['diagnostics'][0]['code'], 'STALE_DRAFT_REVISION')
        result = self.send('transfer_publish', preview_id=first['transfer']['preview_id'])
        self.assertEqual(result['diagnostics'][0]['code'], 'STALE_DRAFT_REVISION')
