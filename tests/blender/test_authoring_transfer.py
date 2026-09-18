"""Read-only transfer preview, indexed bindings, safe publication and persistence."""
import copy
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import bpy
import numpy as np
from _helpers import BlenderTestCase, root
from _transfer_fixture import fixture, message, snapshot, read_preview, whole_region
from test_authoring_v04 import call
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.adapters.authoring.inventory import geometry_for
from anthroforge.app.authoring.api import execute
from anthroforge.core.authoring.schema import validate
from anthroforge.core.authoring.storage import FileStore
from anthroforge.core.authoring.transfer_meshes import world
from anthroforge.core.authoring.attachment_binding import nearest_binding
from anthroforge.core.authoring.indexed_patches import topology


class AuthoringTransferTests(BlenderTestCase):
    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.folder, self.root = folder.name, root()
        self.fixture = fixture(self.root, self.folder)

    def send(self, operation, **params):
        result = execute(message(self.root, operation, **params), self.root, bpy.context.scene, self.folder)
        validate(result, 'protocol')
        return result

    def preview(self):
        result = self.send('transfer_preview', **self.fixture['params'])
        self.assertEqual(result['status'], 'success', result)
        return result

    def publish(self, preview):
        return self.send('transfer_publish', preview_id=preview['transfer']['preview_id'])

    def test_source_capture_exposes_evaluated_geometry_and_discovery_lists_operations(self):
        source = bpy.data.objects[self.fixture['source']]
        modifier = source.modifiers.new('Evaluated example', 'TRIANGULATE')
        result = self.send('transfer_sources', source_objects=[source.name])
        data = json.loads(Path(result['assets'][0]['path']).read_text())
        self.assertEqual(len(data['meshes'][source.name]['geometry']['polygons']), 12)
        source.modifiers.remove(modifier)
        request = dict(version='0.4.0', message_type='request', request_id='discover', op='anatomy.discover', params=dict(scene_id=self.root.name))
        discovered = execute(request, self.root, bpy.context.scene, self.folder)
        self.assertIn('anatomy.transfer_preview', discovered['operations'])
        self.assertIn('skeleton_transfer.experimental.v1', discovered['capabilities'])

    def test_shared_affine_transfer_and_publication_preserve_original_scene(self):
        before = snapshot(self.root); original_objects = set(bpy.data.objects.keys())
        preview = self.preview(); record = read_preview(preview)
        self.assertEqual(set(bpy.data.objects.keys()), original_objects)
        source, target = [bpy.data.objects[self.fixture[k]] for k in ('source', 'target')]
        transform = np.array(target.matrix_world @ source.matrix_world.inverted())
        for row in record['result']['meshes']:
            vertices = world(geometry_for(bpy.data.objects[row['source_object']]))
            np.testing.assert_allclose(row['vertices'], vertices @ transform[:3, :3].T+transform[:3, 3], atol=1e-6)
        result = self.publish(preview)
        self.assertTrue(result['published'], result)
        self.assertEqual(snapshot(self.root)['revision'], before['revision'])
        self.assertEqual(len(set(bpy.data.objects.keys())-original_objects), 2)

    def test_publication_replay_reuses_objects_and_detects_edited_output(self):
        preview = self.preview()
        payload = message(self.root, 'transfer_publish', preview_id=preview['transfer']['preview_id'])
        first = execute(payload, self.root, bpy.context.scene, self.folder)
        second = execute(payload, self.root, bpy.context.scene, self.folder)
        self.assertTrue(second['replayed'], second)
        self.assertTrue(second['transfer']['reused'])
        self.assertEqual(first['transfer']['objects'], second['transfer']['objects'])
        obj = bpy.data.objects[first['transfer']['objects'][0]['name']]; obj.location.x += .1
        third = execute(payload, self.root, bpy.context.scene, self.folder)
        self.assertEqual(third['diagnostics'][0]['code'], 'TRANSFER_REVIEW_EDITED')
        self.assertAlmostEqual(obj.location.x, .1)

    def test_changed_source_invalidates_preview_replay_and_publish(self):
        payload = message(self.root, 'transfer_preview', **self.fixture['params'])
        first = execute(payload, self.root, bpy.context.scene, self.folder)
        bpy.data.objects[self.fixture['muscles'][0]].location.y += .01
        replay = execute(payload, self.root, bpy.context.scene, self.folder)
        self.assertEqual(replay['diagnostics'][0]['code'], 'STALE_TRANSFER_SOURCE')
        self.assertEqual(self.publish(first)['diagnostics'][0]['code'], 'STALE_TRANSFER_SOURCE')

    def test_changed_target_invalidates_publication(self):
        preview = self.preview()
        bpy.data.objects[self.fixture['target']].location.y += .1
        self.assertEqual(self.publish(preview)['diagnostics'][0]['code'], 'STALE_SCENE_REVISION')

    def test_changed_discovery_draft_invalidates_publication(self):
        preview = self.preview(); document = self.fixture['document']
        query = document['skeleton_profiles']['default']['regions']['origin']['query']
        result = call(self.root, self.folder, 'patch', document, patch=[dict(op='replace', path='/skeleton_profiles/default/regions/origin/query', value=query)])
        self.assertEqual(result['draft_revision'], 2, result)
        self.assertEqual(self.publish(preview)['diagnostics'][0]['code'], 'STALE_DRAFT_REVISION')

    def test_landmark_outside_selected_region_fails(self):
        document = self.fixture['document']; query = copy.deepcopy(document['skeleton_profiles']['default']['regions']['origin']['query'])
        query['patches'] = query['patches'][:1]
        result = call(self.root, self.folder, 'patch', document, patch=[dict(op='replace', path='/skeleton_profiles/default/regions/origin/query', value=query)])
        self.assertEqual(result['draft_revision'], 2, result)
        params = copy.deepcopy(self.fixture['params'])
        for row in params['correspondences']:
            row['target']['expected_draft_revision'] = 2
        result = self.send('transfer_preview', **params)
        self.assertEqual(result['diagnostics'][0]['code'], 'TRANSFER_POINT_OUTSIDE_REGION')

    def test_topology_mismatch_fails_and_coordinate_deformation_reuses_bindings(self):
        params = copy.deepcopy(self.fixture['params'])
        params['correspondences'][0]['source']['topology_digest'] = 'wrong'
        rejected = self.send('transfer_preview', **params)
        self.assertEqual(rejected['diagnostics'][0]['code'], 'TRANSFER_SOURCE_TOPOLOGY_CHANGED')
        old = self.preview()['transfer']['preview_id']
        target = bpy.data.objects[self.fixture['target']]
        for vertex in target.data.vertices:
            vertex.co.x *= 1.1
        target.data.update()
        result = self.preview()
        self.assertNotEqual(result['transfer']['preview_id'], old)
        self.assertLess(result['transfer']['landmarks']['max_error'], 1e-6)

    def test_independently_meshed_target_accepts_distinct_vertex_and_face_counts(self):
        geometry = self.replace_target_with_sphere()
        params = copy.deepcopy(self.fixture['params'])
        source, target = [bpy.data.objects[self.fixture[k]] for k in ('source', 'target')]
        matrix = np.asarray(target.matrix_world)
        for i, row in enumerate(params['correspondences']):
            local = np.array(source.data.vertices[i].co); local *= .75/np.linalg.norm(local)
            binding = nearest_binding(geometry, matrix[:3, :3] @ local+matrix[:3, 3])
            row['target'].update(expected_draft_revision=2, topology_digest=topology(geometry), surface_binding=binding)
        self.assertNotEqual(len(source.data.vertices), len(target.data.vertices))
        self.assertNotEqual(params['correspondences'][0]['source']['topology_digest'], topology(geometry))
        preview = self.send('transfer_preview', **params)
        self.assertEqual(preview['status'], 'success', preview)
        self.assertLess(preview['transfer']['landmarks']['max_error'], 1e-6)
        self.assertTrue(self.publish(preview)['published'])

    def replace_target_with_sphere(self):
        target = bpy.data.objects[self.fixture['target']]
        bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, radius=.75)
        temporary = bpy.context.object; target.data = temporary.data
        bpy.data.objects.remove(temporary, do_unlink=True)
        geometry = snapshot(self.root)['geometry'][self.fixture['owner']]
        row = dict(op='replace', path='/skeleton_profiles/default/regions/origin/query', value=whole_region(geometry))
        result = call(self.root, self.folder, 'patch', self.fixture['document'], patch=[row])
        self.assertEqual(result['draft_revision'], 2, result)
        return geometry

    def test_receipt_write_failure_rolls_back_new_review_geometry(self):
        preview = self.preview(); objects, meshes = set(bpy.data.objects.keys()), set(bpy.data.meshes.keys())
        with patch.object(FileStore, 'put', fail_receipt(FileStore.put)):
            result = self.publish(preview)
        self.assertEqual(result['status'], 'failed', result)
        self.assertEqual(set(bpy.data.objects.keys()), objects)
        self.assertEqual(set(bpy.data.meshes.keys()), meshes)
        self.assertTrue(self.publish(preview)['published'])

    def test_save_reload_retains_meshes_manifest_and_journal_replay(self):
        preview = self.preview(); result = self.publish(preview)
        expected = {r['name']: geometry_for(bpy.data.objects[r['name']]) for r in result['transfer']['objects']}
        path = Path(self.folder)/'transfer.blend'; name = self.root.name
        StaticScene(self.root, bpy.context.scene).save_debug_copy(path)
        bpy.ops.wm.open_mainfile(filepath=str(path)); self.root = bpy.data.objects[name]
        self.assertEqual(self.root['af_authoring_journal'], self.folder)
        for name, geometry in expected.items():
            obj = bpy.data.objects[name]
            self.assertEqual(geometry_for(obj), geometry)
            self.assertFalse(obj.hide_get() or obj.hide_viewport or obj.hide_render)
        manifest = json.loads(bpy.data.collections[result['transfer']['collection']]['af_transfer_manifest'])
        self.assertEqual(manifest['validation']['anatomy'], 'not_evaluated')
        self.assertTrue(self.publish(preview)['transfer']['reused'])


def fail_receipt(original):
    def write(store, category, key, value):
        if category == 'transfer_requests':
            raise OSError('Injected transfer receipt failure')
        return original(store, category, key, value)
    return write
