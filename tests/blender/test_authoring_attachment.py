"""Continuous footprint coverage, safe publication and persisted reference geometry."""
import json
import tempfile
from pathlib import Path
import bpy
import numpy as np
from _helpers import BlenderTestCase, root
from _transfer_fixture import fixture, message, snapshot
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.adapters.authoring.inventory import geometry_for
from anthroforge.adapters.authoring.attachment_coverage import coverage
from anthroforge.app.authoring.api import execute
from anthroforge.core.authoring.transfer_meshes import world


def parameters(scene, owner, obj):
    geometry = scene.capture_authoring()['geometry'][owner]; v = world(geometry)
    faces = [f for f in geometry['triangles'] if np.min(v[f, 2]) > v[:, 2].max()-1e-6]
    source = scene.transfer_sources([obj.name])[obj.name]
    settings = dict(cut_value=-1., overlap_cut_value=-1.2, escape_distance=.3, tolerance=.001,
                    departure_direction=[0, 0, 1], attachment_axes=[[1, 0, 0], [0, 1, 0]],
                    retained_axes=[[1, 0, 0], [0, 1, 0]], validation_samples=64)
    return dict(source_object=obj.name, topology_digest=source['topology_digest'], geometry_digest=source['geometry_digest'],
                obstacle_instance_ids=[owner], attachment_instance_id=owner, settings=settings,
                source_cut_values=(-world(source['geometry'])[:, 2]).tolist(),
                footprint=[dict(tri_vidx=f, polygon=np.eye(3).tolist()) for f in faces])


class AttachmentTests(BlenderTestCase):
    def test_boolean_seam_roundoff_is_not_a_nonadjacent_crossing(self):
        from anthroforge.adapters.authoring.collision_geometry import quality, seam_contact
        data = json.loads((Path(__file__).parents[1]/'fixtures/attachment_boolean_seam.json').read_text())
        vertices, faces = np.asarray(data['vertices']), np.asarray(data['faces'])
        self.assertEqual(quality(vertices, faces, .001)['nonadjacent_overlap_pairs'], 0)
        self.assertTrue(seam_contact(vertices[faces[0]], vertices[faces[1]], 1e-8))
        self.assertFalse(seam_contact(vertices[faces[0]], vertices[faces[1]]+[0, 0, .01], 1e-8))

    def test_nonadjacent_crossing_remains_rejected(self):
        from anthroforge.adapters.authoring.collision_geometry import quality
        vertices = np.asarray([[-1, 0, 0], [1, 0, 0], [0, 1, 0], [0, .2, -1], [0, .2, 1], [0, -.5, 0]])
        result = quality(vertices, np.asarray([[0, 1, 2], [3, 4, 5]]), .001)
        self.assertEqual(result['nonadjacent_overlap_pairs'], 1)
        self.assertFalse(result['ready'])

    def setUp(self):
        super().setUp(); folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.folder = folder.name; self.root = root(); self.fixture = fixture(self.root, self.folder)
        self.bone = bpy.data.objects[self.fixture['target']]
        self.bone.location = (0, 0, 0); self.bone.scale = (1, 1, 1); self.bone.rotation_euler = (0, 0, 0)
        bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=12, location=(0, 0, 1.5))
        self.source = bpy.context.object; self.source.scale = (.35, .25, 1.)
        self.params = parameters(StaticScene(self.root, bpy.context.scene), self.fixture['owner'], self.source)

    def send(self, op, **params):
        return execute(message(self.root, op, **params), self.root, bpy.context.scene, self.folder)

    def test_complete_contact_and_no_input_mutation(self):
        before = snapshot(self.root); source = geometry_for(self.source); objects = set(bpy.data.objects)
        result = self.send('transfer_attachment_preview', **self.params)
        self.assertEqual(result['status'], 'success', result); row = result['transfer']
        self.assertTrue(row['ready']); self.assertGreater(row['footprint']['covered_fraction'], .9999)
        self.assertEqual(row['quality']['euler'], 2); self.assertEqual(before, snapshot(self.root))
        self.assertEqual(source, geometry_for(self.source)); self.assertEqual(set(bpy.data.objects), objects)

    def test_publish_replay_reopen_and_stale_source(self):
        preview = self.send('transfer_attachment_preview', **self.params); identity = preview['transfer']['preview_id']
        first = self.send('transfer_attachment_publish', preview_id=identity); self.assertTrue(first['published'], first)
        second = self.send('transfer_attachment_publish', preview_id=identity); self.assertTrue(second['transfer']['reused'])
        name = first['transfer']['objects'][0]['name']; geometry = geometry_for(bpy.data.objects[name]); root_name = self.root.name
        path = Path(self.folder)/'attachment.blend'; StaticScene(self.root, bpy.context.scene).save_debug_copy(path)
        bpy.ops.wm.open_mainfile(filepath=str(path)); self.root = bpy.data.objects[root_name]
        self.assertEqual(geometry, geometry_for(bpy.data.objects[name])); self.assertFalse(bpy.data.objects[name].hide_get())
        source = bpy.data.objects[self.params['source_object']]; source.location.x += .1
        result = self.send('transfer_attachment_publish', preview_id=identity)
        self.assertFalse(result['published']); self.assertEqual(result['diagnostics'][0]['code'], 'STALE_BASE_GEOMETRY')

    def test_changed_bone_blocks_publication(self):
        preview = self.send('transfer_attachment_preview', **self.params); self.bone.location.x += .01
        result = self.send('transfer_attachment_publish', preview_id=preview['transfer']['preview_id'])
        self.assertFalse(result['published']); self.assertEqual(result['diagnostics'][0]['code'], 'STALE_ATTACHMENT_GEOMETRY')

    def test_area_check_detects_interior_gap_with_boundary_vertices_on_surface(self):
        v = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [.2, .2, 0], [.6, .2, 0], [.2, .6, 0]])
        f = np.array([[0, 1, 4], [0, 4, 3], [1, 2, 5], [1, 5, 4], [2, 0, 3], [2, 3, 5]])
        measured = coverage(v, f, v[:3], np.array([[0, 1, 2]]), 1e-6)
        self.assertAlmostEqual(measured['covered_fraction'], .84)
