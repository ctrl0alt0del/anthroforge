"""Collision correction through the public protocol, including failure and replay."""
import copy
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import bpy
import numpy as np
from _helpers import BlenderTestCase, root
from _transfer_fixture import fixture, message, snapshot
from anthroforge.adapters.authoring.inventory import geometry_for
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.app.authoring.api import execute
from anthroforge.core.authoring.schema import validate
from anthroforge.core.authoring.storage import FileStore
from anthroforge.core.authoring.attachment_binding import nearest_binding
from anthroforge.core.authoring.transfer_meshes import world
from anthroforge.adapters.authoring.collision_geometry import tree, precise_distance
from anthroforge.adapters.authoring.collision_checks import collision_failure


class CollisionCorrectionTests(BlenderTestCase):
    def test_detached_humerus_union_remains_valid_after_world_translation(self):
        from anthroforge.adapters.authoring.collision_correction import obstacles
        path = Path(__file__).parents[1]/'fixtures/fcu_humerus_collision.json'
        fixture = json.loads(path.read_text(encoding='utf-8'))
        original = np.asarray(fixture['vertices']); scene_objects = set(bpy.data.objects); bounds = None
        for offset in (np.zeros(3), np.array([1000., -2000., 500.])):
            geometry = dict(vertices=(original+offset).tolist(), triangles=fixture['triangles'], matrix=np.eye(4).tolist())
            result, checks = obstacles(bpy.context.scene, {'humerus': geometry}, 1e-4)
            self.assertTrue(checks['humerus']['evaluated']['ready'])
            actual = np.vstack((result[0].vertices.min(0), result[0].vertices.max(0)))-offset
            if bounds is None: bounds = actual
            np.testing.assert_allclose(actual, bounds, atol=2e-5, rtol=0)
        self.assertEqual(set(bpy.data.objects), scene_objects)

    def setUp(self):
        super().setUp(); folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.folder, self.root = folder.name, root(); f = fixture(self.root, self.folder)
        target = bpy.data.objects[f['target']]; target.location = (0, 0, 0); target.rotation_euler = (0, 0, 0); target.scale = (1, 1, 1)
        for v in target.data.vertices: v.co = tuple(1 if x > 0 else -1 for x in v.co)
        target.data.update(); bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=8, radius=.4, location=(1.2, 0, 0))
        self.source = bpy.context.object; self.source.name = 'Collision reference'; self.owner = f['owner']
        response = self.send('transfer_sources', source_objects=[self.source.name]); row = response['transfer']['meshes'][0]
        self.params = dict(source_object=self.source.name, topology_digest=row['topology_digest'], geometry_digest=row['geometry_digest'],
                           obstacle_instance_ids=[self.owner], settings=dict(tolerance=1e-4, influence_radius=2., max_displacement=.7, max_volume_change=.9, centers=8, validation_samples=512))

    def send(self, op, **params):
        result = execute(message(self.root, op, **params), self.root, bpy.context.scene, self.folder)
        validate(result, 'protocol'); return result

    def preview(self, **changes):
        params = copy.deepcopy(self.params); params.update(changes)
        return self.send('transfer_correct_preview', **params)

    def test_report_detects_penetration_without_scene_mutation(self):
        params = dict(self.params, settings=dict(tolerance=1e-4, validation_samples=256)); before = set(bpy.data.objects)
        result = self.send('transfer_collisions', **params)
        self.assertEqual(result['status'], 'success', result)
        self.assertGreater(result['transfer']['collisions'][0]['max_penetration'], .15)
        self.assertEqual(set(bpy.data.objects), before)

    def test_preview_clears_bone_and_publication_replays_without_duplicates(self):
        original = geometry_for(self.source); objects = set(bpy.data.objects); meshes = set(bpy.data.meshes); result = self.preview()
        self.assertEqual(result['status'], 'success', result)
        self.assertEqual(geometry_for(self.source), original); self.assertEqual(set(bpy.data.objects), objects); self.assertEqual(set(bpy.data.meshes), meshes)
        params = dict(preview_id=result['transfer']['preview_id']); first = self.send('transfer_correct_publish', **params)
        self.assertTrue(first['published'], first); second = self.send('transfer_correct_publish', **params)
        self.assertEqual(first['transfer']['objects'], second['transfer']['objects'])
        self.assertTrue(second['transfer']['reused'])
        obj = bpy.data.objects[first['transfer']['objects'][0]['name']]; obj.location.z += .01
        self.assertEqual(self.send('transfer_correct_publish', **params)['diagnostics'][0]['code'], 'TRANSFER_REVIEW_EDITED')

    def test_impossible_fixed_band_is_unresolved_and_cannot_publish(self):
        result = self.preview(protected_bands=[dict(id='entire_surface', vertex_indices=list(range(len(self.source.data.vertices))))], settings=dict(self.params['settings'], cleanup='none', max_iterations=2))
        self.assertEqual(result['status'], 'unresolved', result)
        published = self.send('transfer_correct_publish', preview_id=result['transfer']['preview_id'])
        self.assertEqual(published['diagnostics'][0]['code'], 'CORRECTION_NOT_READY')
        self.assertFalse(published['published'])

    def test_geometry_edit_invalidates_publish(self):
        result = self.preview(); self.source.location.y += .01
        published = self.send('transfer_correct_publish', preview_id=result['transfer']['preview_id'])
        self.assertEqual(published['diagnostics'][0]['code'], 'STALE_BASE_GEOMETRY')

    def test_out_of_range_band_and_unknown_obstacle_rejected(self):
        result = self.preview(protected_bands=[dict(id='bad', vertex_indices=[999999])])
        self.assertEqual(result['diagnostics'][0]['code'], 'CORRECTION_PROTECTION_INDEX')
        result = self.preview(obstacle_instance_ids=['unknown'])
        self.assertEqual(result['diagnostics'][0]['code'], 'COLLISION_UNKNOWN_OBSTACLE')

    def test_receipt_failure_rolls_back_output(self):
        result = self.preview(); original = set(bpy.data.objects); put = FileStore.put
        def fail(store, category, key, value):
            if category == 'transfer_requests': raise OSError('Injected receipt failure')
            return put(store, category, key, value)
        with patch.object(FileStore, 'put', fail):
            response = self.send('transfer_correct_publish', preview_id=result['transfer']['preview_id'])
        self.assertEqual(response['status'], 'failed'); self.assertEqual(set(bpy.data.objects), original)

    def test_saved_copy_retains_corrected_reference_and_manifest(self):
        result = self.preview(); published = self.send('transfer_correct_publish', preview_id=result['transfer']['preview_id'])
        name = published['transfer']['objects'][0]['name']; geometry = geometry_for(bpy.data.objects[name]); root_name = self.root.name
        path = Path(self.folder)/'corrected.blend'; StaticScene(self.root, bpy.context.scene).save_debug_copy(path)
        bpy.ops.wm.open_mainfile(filepath=str(path)); self.root = bpy.data.objects[root_name]
        self.assertEqual(geometry_for(bpy.data.objects[name]), geometry)
        manifest = json.loads(bpy.data.collections[published['transfer']['collection']]['af_transfer_manifest'])
        self.assertEqual(manifest['version'], 'transfer_correction.v1')
        self.assertEqual(manifest['validation']['anatomical_review'], 'required')

    def test_protected_band_and_bone_contact_survive_cleanup(self):
        geometry = geometry_for(self.source); vertices = world(geometry); point = vertices[np.argmin(vertices[:, 0])]
        bone = snapshot(self.root)['geometry'][self.owner]
        contact = dict(id='attachment', source_binding=nearest_binding(geometry, point), obstacle_instance_id=self.owner,
                       target_binding=nearest_binding(bone, [1., point[1], point[2]]))
        band = dict(id='outer_band', vertex_indices=np.flatnonzero(vertices[:, 0] > 1.5).tolist())
        result = self.preview(contacts=[contact], protected_bands=[band])
        self.assertEqual(result['status'], 'success', result)
        self.assertLessEqual(result['transfer']['preservation']['protected_max_distance'], 1e-4)
        self.assertGreater(result['transfer']['preservation']['protected_sample_count'], len(band['vertex_indices']))

    def test_same_request_replays_and_live_source_edit_still_rejects(self):
        payload = message(self.root, 'transfer_correct_preview', **self.params)
        first = execute(payload, self.root, bpy.context.scene, self.folder); second = execute(payload, self.root, bpy.context.scene, self.folder)
        self.assertTrue(second['replayed'], second); self.assertEqual(first['transfer'], second['transfer'])
        self.source.location.y += .001; third = execute(payload, self.root, bpy.context.scene, self.folder)
        self.assertEqual(third['diagnostics'][0]['code'], 'STALE_BASE_GEOMETRY')

    def test_displacement_limit_and_protection_conflict_fail_safely(self):
        result = self.preview(settings=dict(self.params['settings'], max_displacement=.00001, cleanup='none', max_iterations=1))
        self.assertEqual(result['status'], 'unresolved', result)
        geometry = geometry_for(self.source); bone = snapshot(self.root)['geometry'][self.owner]
        contact = dict(id='conflicting', source_binding=nearest_binding(geometry, [.8, 0, 0]), obstacle_instance_id=self.owner, target_binding=nearest_binding(bone, [1., 0, 0]))
        band = dict(id='fixed', vertex_indices=list(range(len(self.source.data.vertices))))
        result = self.preview(protected_bands=[band], contacts=[contact])
        self.assertEqual(result['diagnostics'][0]['code'], 'CORRECTION_CONSTRAINT_CONFLICT')

    def test_guard_cannot_duplicate_target_and_settings_schema_is_closed(self):
        result = self.preview(guard_instance_ids=[self.owner])
        self.assertEqual(result['diagnostics'][0]['code'], 'COLLISION_UNKNOWN_OBSTACLE')
        result = self.preview(settings=dict(self.params['settings'], undocumented=True))
        self.assertEqual(result['diagnostics'][0]['code'], 'SCHEMA_UNKNOWN_FIELD', result)

    def test_skinny_triangle_protection_uses_double_precision_fallback(self):
        vertices = np.array([[-.5794560313, -9.50518608, -3.430170298], [-.4337556064, -9.329497337, -3.321197748], [-.4392281771, -9.336559296, -3.325667858]])
        faces = np.array([[0, 1, 2]]); point = vertices.mean(axis=0)
        distance = precise_distance(tree(vertices, faces), vertices, faces, point, 1e-4)
        self.assertLess(distance, 1e-8)

    def test_enclosed_bone_detected_without_surface_crossings(self):
        self.source.location = (0, 0, 0); self.source.scale = (10, 10, 10)
        row = self.send('transfer_sources', source_objects=[self.source.name])['transfer']['meshes'][0]
        params = dict(self.params, geometry_digest=row['geometry_digest'], settings=dict(tolerance=1e-4, validation_samples=64))
        result = self.send('transfer_collisions', **params); report = result['transfer']['collisions'][0]
        self.assertEqual(report['inside_vertices'], 0); self.assertEqual(report['triangle_overlap_pairs'], 0)
        self.assertGreater(report['reverse_containment']['contained_samples'], 0)

    def test_guard_accepts_existing_collision_but_rejects_worsening(self):
        before = dict(obstacle='guard', ambiguous_samples=0, max_penetration=.2, centroid_inside_area=.3, reverse_containment=dict(max_depth=.1))
        settings = dict(guard_instance_ids=['guard'], tolerance=.0001)
        self.assertFalse(collision_failure(before, before, settings))
        self.assertTrue(collision_failure(dict(before, max_penetration=.21), before, settings))
        self.assertTrue(collision_failure(dict(before, centroid_inside_area=.31), before, settings))
        self.assertTrue(collision_failure(dict(before, reverse_containment=dict(max_depth=.11)), before, settings))

    def test_already_clear_reference_is_unchanged(self):
        self.source.location.x = 4.
        row = self.send('transfer_sources', source_objects=[self.source.name])['transfer']['meshes'][0]
        result = self.preview(geometry_digest=row['geometry_digest']); self.assertEqual(result['status'], 'success', result)
        record = json.loads(Path(result['assets'][0]['path']).read_text()); mesh = record['result']['meshes'][0]
        np.testing.assert_array_equal(mesh['vertices'], world(geometry_for(self.source)))
        self.assertEqual(result['transfer']['fitting']['stop_reason'], 'already_clear')
