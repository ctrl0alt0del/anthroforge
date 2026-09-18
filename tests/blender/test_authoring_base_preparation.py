"""Boolean union is isolated; underside evidence includes noncontact spans."""
import tempfile
from unittest.mock import patch
import bpy
import numpy as np
from _helpers import BlenderTestCase, root
from _transfer_fixture import run, snapshot
from _native_base_fixture import fixture, read_asset
from anthroforge.adapters.authoring.transfer import capture
from anthroforge.core.authoring.storage import FileStore
from anthroforge.core.authoring.schema import validate


def cube(name, location):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object; obj.name = name
    row = capture(bpy.context.scene, [name])[name]
    return dict(source_object=name, topology_digest=row['topology_digest'], geometry_digest=row['geometry_digest'])


class BasePreparationTests(BlenderTestCase):
    def setUp(self):
        super().setUp(); folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.folder, self.root = folder.name, root()

    def test_exact_union_is_copy_only_and_replay_detects_edit(self):
        sources = [cube('Volume A', (3, 0, 0)), cube('Volume B', (3.4, .1, .1))]
        before = capture(bpy.context.scene, [s['source_object'] for s in sources]); objects = set(bpy.data.objects)
        result = run(self.root, self.folder, 'repair_volume', sources=sources); validate(result, 'protocol')
        self.assertTrue(result['published'], result)
        self.assertEqual(len(set(bpy.data.objects)-objects), 1)
        self.assertEqual(before, capture(bpy.context.scene, list(before)))
        repeat = run(self.root, self.folder, 'repair_volume', sources=sources)
        self.assertTrue(repeat['transfer']['reused'], repeat)
        obj = bpy.data.objects[result['transfer']['objects'][0]['name']]; obj.data.vertices[0].co.z += .2; obj.data.update()
        self.assertIn('TRANSFER_REVIEW_EDITED', str(run(self.root, self.folder, 'repair_volume', sources=sources)))

    def test_open_union_remains_unresolved_without_new_objects(self):
        _document, obj, definition = fixture(self.root, self.folder); objects = set(bpy.data.objects)
        sources = [{k: definition[k] for k in ('source_object', 'topology_digest', 'geometry_digest')}]
        result = run(self.root, self.folder, 'repair_volume', sources=sources)
        self.assertEqual(result['status'], 'unresolved', result)
        self.assertFalse(result['published']); self.assertEqual(set(bpy.data.objects), objects)

    def test_evidence_keeps_noncontact_underside_and_rejects_superficial_face(self):
        _document, _obj, _definition = fixture(self.root, self.folder)
        source = cube('Separated reference volume', (2, 0, 0)); inventory = snapshot(self.root)
        owner = next(r['instance_id'] for r in inventory['instances'] if r['label'] == 'Cube.001')
        before = set(bpy.data.objects)
        result = run(self.root, self.folder, 'base_candidates', **source, support_instances=[owner])
        self.assertEqual(result['status'], 'success', result); self.assertEqual(set(bpy.data.objects), before)
        evidence = read_asset(result); row = capture(bpy.context.scene, [source['source_object']])[source['source_object']]
        vertices = np.asarray(row['geometry']['vertices']); faces = np.asarray(row['geometry']['triangles'])
        for index in evidence['source_triangles']:
            self.assertLess(vertices[faces[index]].mean(0)[0], 0)
            self.assertGreater(evidence['faces'][index]['distance'], .5)
        self.assertEqual(len(evidence['source_triangles']), 2)
