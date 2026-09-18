"""Experimental base preparation is journaled, head-aware and scene-read-only."""
import json
import tempfile
from pathlib import Path
import bpy
from _helpers import BlenderTestCase, root
from tests.unit._base_structure_fixture import example
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.adapters.authoring.transfer import capture
from anthroforge.app.authoring.api import execute
from anthroforge.core.authoring.schema import validate


class AuthoringBaseTests(BlenderTestCase):
    def setUp(self):
        super().setUp(); folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.folder, self.root = folder.name, root(); definition = example()
        mesh = bpy.data.meshes.new('Underside samples'); mesh.from_pydata(definition.pop('vertices'), [], definition.pop('triangles')); mesh.update()
        self.source = bpy.data.objects.new('Underside samples', mesh); bpy.context.scene.collection.objects.link(self.source)
        row = capture(bpy.context.scene, [self.source.name])[self.source.name]; inventory = StaticScene(self.root, bpy.context.scene).capture_authoring()
        params = dict(scene_id=self.root.name, expected_scene_revision=inventory['revision'], source_object=self.source.name,
                      topology_digest=row['topology_digest'], geometry_digest=row['geometry_digest'], **definition)
        self.request = dict(version='0.4.0', message_type='request', request_id='base', op='anatomy.prepare_base', params=params)

    def send(self):
        result = execute(self.request, self.root, bpy.context.scene, self.folder); validate(result, 'protocol')
        return result

    def test_preview_preserves_scene_and_shared_head_topology(self):
        objects = set(bpy.data.objects); before = StaticScene(self.root, bpy.context.scene).capture_authoring()['revision']
        result = self.send(); self.assertEqual(result['status'], 'success', result)
        saved = json.loads(Path(result['assets'][0]['path']).read_text())
        self.assertEqual(len(saved['heads']), 2); self.assertEqual(len(saved['connections']), 2)
        self.assertEqual(saved['topology']['euler'], 1)
        self.assertEqual(set(bpy.data.objects), objects)
        self.assertEqual(StaticScene(self.root, bpy.context.scene).capture_authoring()['revision'], before)
        self.assertEqual(len(self.root.af_vcp_system.fibers), 0)

    def test_same_request_rechecks_reference_geometry(self):
        self.assertEqual(self.send()['status'], 'success')
        self.source.data.vertices[0].co.x += .1; self.source.data.update()
        result = self.send(); self.assertEqual(result['status'], 'unresolved', result)
        self.assertIn('STALE_BASE_GEOMETRY', str(result))
