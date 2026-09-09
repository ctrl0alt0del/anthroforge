"""Native integration for calibrated visual inspection and stale-view rejection."""
import tempfile
from uuid import uuid4
import bpy
import numpy as np
from _helpers import BlenderTestCase, root
from test_authoring_v04 import setup
from anthroforge.app.authoring.api import execute
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.core.authoring.schema import validate
from anthroforge.core.authoring import visual_camera, visual_raster, visual_mesh


def call(r, directory, op, **params):
    payload = dict(version='0.4.0', message_type='request', request_id=str(uuid4()), op='anatomy.'+op, params=dict(scene_id=r.name, **params))
    value = execute(payload, r, bpy.context.scene, directory)
    validate(value, 'protocol')
    return value


def views(r, directory):
    setup(r, directory)
    inventory = StaticScene(r, bpy.context.scene).capture_authoring()
    owner = next(row for row in inventory['instances'] if row['has_surface'] and not row['mirror'])
    value = call(r, directory, 'views', instance_id=owner['instance_id'], expected_scene_revision=inventory['revision'], resolution=128)
    assert value['status'] == 'success', value
    return inventory, owner, value['views']


class VisualIntegrationTests(BlenderTestCase):
    def test_point_can_be_confirmed_after_context_switch(self):
        r = root()
        with tempfile.TemporaryDirectory() as directory:
            inventory, owner, rows = views(r, directory)
            hit = call(r, directory, 'pick', view_id=rows[0]['id'], points=[[.5, .5]])['hits'][0]
            context = [k for k in inventory['geometry'] if k != owner['instance_id']]
            view = call(r, directory, 'view', view_id=rows[0]['id'], point_id=hit['id'], context_ids=context)['view']
            hidden = call(r, directory, 'view', view_id=view['id'], context_ids=[])['view']
            result = call(r, directory, 'highlight', view_ids=[view['id'], hidden['id']], point_ids=[hit['id']])
            self.assertEqual(result['status'], 'success')
            self.assertEqual(result['views'][1]['projections'][0]['state'], 'visible')

    def test_inspection_keeps_scene_and_point_matches_native_bvh(self):
        from mathutils.bvhtree import BVHTree
        r = root()
        with tempfile.TemporaryDirectory() as directory:
            inventory, owner, rows = views(r, directory)
            geometry = inventory['geometry'][owner['instance_id']]
            triangle = visual_camera.vertices(geometry)[np.asarray(geometry['triangles'])]
            origin, direction, _ = visual_camera.ray(rows[0]['camera'], [.5, .5], triangle)
            tree = BVHTree.FromPolygons(visual_camera.vertices(geometry).tolist(), geometry['triangles'], all_triangles=True)
            native = tree.ray_cast(origin.tolist(), direction.tolist())[0]
            hit = call(r, directory, 'pick', view_id=rows[0]['id'], points=[[.5, .5]])['hits'][0]
            self.assertTrue(hit['hit'])
            np.testing.assert_allclose(hit['point'], native, atol=1e-5)
            self.assertEqual(inventory['revision'], StaticScene(r, bpy.context.scene).capture_authoring()['revision'])

    def test_geometry_edit_rejects_old_view(self):
        r = root()
        with tempfile.TemporaryDirectory() as directory:
            _, owner, rows = views(r, directory)
            obj = bpy.data.objects[owner['locator']]
            obj.scale.x *= 1.1
            bpy.context.view_layer.update()
            value = call(r, directory, 'pick', view_id=rows[0]['id'], points=[[.5, .5]])
            self.assertEqual(value['status'], 'unresolved')
            self.assertEqual(value['diagnostics'][0]['code'], 'STALE_VIEW')

    def test_patch_selection_background_and_revision_scope(self):
        r = root()
        with tempfile.TemporaryDirectory() as directory:
            _, _, rows = views(r, directory)
            empty = call(r, directory, 'pick', view_id=rows[0]['id'], points=[[0, 0]])
            self.assertFalse(empty['hits'][0]['hit'])
            result = call(r, directory, 'select_region', view_id=rows[0]['id'], polygon=[[.45, .45], [.55, .45], [.55, .55], [.45, .55]])
            self.assertEqual(result['status'], 'success')
            self.assertGreater(result['selection']['area'], 0)
            inspected = call(r, directory, 'inspect_selection', selection_id=result['selection']['id'], view_ids=[rows[1]['id'], rows[6]['id']])
            self.assertEqual(len(inspected['views']), 2)

    def test_focus_preserves_orientation_and_coverage_improves(self):
        r = root()
        with tempfile.TemporaryDirectory() as directory:
            _, _, rows = views(r, directory)
            first = call(r, directory, 'coverage', view_ids=[rows[0]['id']])['coverage']
            all_views = call(r, directory, 'coverage', view_ids=[v['id'] for v in rows])['coverage']
            self.assertGreater(all_views['observed_samples'], first['observed_samples'])
            hit = call(r, directory, 'pick', view_id=rows[0]['id'], points=[[.5, .5]])['hits'][0]
            zoomed = call(r, directory, 'view', view_id=rows[0]['id'], point_id=hit['id'], zoom=2)['view']
            np.testing.assert_allclose(zoomed['camera']['forward'], rows[0]['camera']['forward'], atol=1e-12)
            np.testing.assert_allclose(visual_camera.project(zoomed['camera'], hit['point'])[:2], [.5, .5], atol=1e-12)
