"""AI discovery lists root-scoped saved profiles and paginated region metadata."""
import tempfile
from uuid import uuid4
import bpy
from _helpers import BlenderTestCase, root
from test_authoring_v04 import setup, call, request
from anthroforge.app.authoring.api import execute
from anthroforge.core.authoring.schema import validate


class CatalogTests(BlenderTestCase):
    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder, self.root = folder.name, root()
        self.value = setup(self.root, self.folder)
        call(self.root, self.folder, 'draft', self.value, 0, document=self.value)

    def query(self, operation, **params):
        payload = request(self.root, operation, **params)
        payload['request_id'] = str(uuid4())
        result = execute(payload, self.root, bpy.context.scene, self.folder)
        validate(result, 'protocol')
        self.assertEqual(result['status'], 'success', result)
        return result

    def test_discover_lists_saved_profiles_and_sampling_readiness(self):
        result = self.query('discover')
        self.assertIn('anatomy.catalog', result['operations'])
        self.assertEqual(result['catalog']['region_count'], 3)
        row = result['catalog']['profiles'][0]
        self.assertEqual(row['document_id'], self.value['document_id'])
        self.assertEqual(row['sampling_count'], 3)

    def test_catalog_pages_and_filters_by_owner_and_text(self):
        first = self.query('catalog', limit=1)
        self.assertEqual(first['catalog']['total'], 3)
        second = self.query('catalog', limit=1, offset=first['catalog']['next_offset'])
        self.assertNotEqual(first['matches'][0]['reference'], second['matches'][0]['reference'])
        owner = self.value['skeleton_profiles']['default']['bindings']['origin']['instance_id']
        result = self.query('catalog', instance_id=owner, text='origin')
        self.assertEqual(len(result['matches']), 1)
        self.assertTrue(result['matches'][0]['binding_available'])
        self.assertTrue(result['matches'][0]['sampling_available'])

    def test_catalog_excludes_drafts_from_other_roots(self):
        self.root['af_authoring_id'] = str(uuid4())
        self.assertEqual(self.query('catalog')['matches'], [])

    def test_upgrade_legacy_regions_commits_indexed_bindings(self):
        from anthroforge.adapters.authoring.scene import StaticScene
        from anthroforge.core.authoring.visual_mesh import topology
        inventory = StaticScene(self.root, bpy.context.scene).capture_authoring()
        owner = self.value['skeleton_profiles']['default']['bindings']['origin']['instance_id']
        query = dict(kind='surface_patch', topology_digest=topology(inventory['geometry'][owner]), patches=[dict(triangle=0, polygon=[[1, 0, 0], [0, 1, 0], [0, 0, 1]])])
        call(self.root, self.folder, 'patch', self.value, patch=[dict(op='replace', path='/skeleton_profiles/default/regions/origin/query', value=query)])
        result = self.query('upgrade_regions', document_id=self.value['document_id'], expected_draft_revision=2, expected_scene_revision=inventory['revision'])
        self.assertEqual(result['draft_revision'], 3)
        exported = self.query('export', document_id=self.value['document_id'])['document']
        upgraded = exported['skeleton_profiles']['default']['regions']['origin']['query']
        self.assertTrue(upgraded['topology_digest'].startswith('vertices-v2:'))
        self.assertIn('face_vidx', upgraded['patches'][0])
        self.assertNotIn('triangle', upgraded['patches'][0])
