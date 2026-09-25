"""Real native publication, shared ownership, replay, and rejected fits."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import bpy
import numpy as np
from _helpers import BlenderTestCase, root, scp_with_object
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.adapters.authoring.transfer import capture
from anthroforge.app.authoring.api import execute
from anthroforge.core.authoring.smooth_native import coordinates, faces


def cube(root_obj, y):
    bpy.ops.mesh.primitive_cube_add(size=2, location=(0, y, 0))
    obj = bpy.context.object; obj.scale = (2, .25, 1)
    scp_with_object(root_obj, 'support'+str(y), obj)
    from anthroforge.adapters.authoring.inventory import initialize
    initialize(root_obj, bpy.context.scene)
    return 'AFI_'+obj['af_authoring_id']


def fixture(root_obj):
    start, end = cube(root_obj, 0), cube(root_obj, 4); uv = coordinates(7, 13); vertices, triangles, patches = [], [], []
    for index, (left, right) in enumerate(((-1., 0.), (0., 1.))):
        points = np.c_[left+(right-left)*uv[:, 0], 4*uv[:, 1], 1+.15*np.sin(np.pi*uv[:, 1])]
        offset = len(vertices); vertices.extend(points.tolist()); triangles.extend((faces(7, 13)+offset).tolist())
        endpoints = [dict(start=dict(instance_id=start, position=[x, 0, 1], max_distance=.1),
                          end=dict(instance_id=end, position=[x, 4, 1], max_distance=.1)) for x in np.linspace(left, right, 3)]
        patches.append(dict(id=str(index), head_ids=[str(index)], grid_vertex_ids=(np.arange(91).reshape(7, 13)+offset).tolist(), endpoints=endpoints))
    mesh = bpy.data.meshes.new('underside'); mesh.from_pydata(vertices, [], triangles); mesh.update()
    obj = bpy.data.objects.new('underside', mesh); bpy.context.scene.collection.objects.link(obj)
    return obj, patches


class SmoothBaseTests(BlenderTestCase):
    def setUp(self):
        super().setUp(); self.root = root(); folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup); self.folder = folder.name
        self.source, patches = fixture(self.root); row = capture(bpy.context.scene, [self.source.name])[self.source.name]
        self.params = dict(source_object=self.source.name, topology_digest=row['topology_digest'], geometry_digest=row['geometry_digest'],
            family='Test', heads=[dict(id=str(i), label=str(i)) for i in range(2)], patches=patches,
            seams=[dict(id='shared', first=dict(patch_id='0', side=1), second=dict(patch_id='1', side=0))],
            settings=dict(max_shape_error=.2, max_native_error=.05), anatomical_note='Synthetic shared head fixture')

    def send(self, op, identity, **params):
        inventory = StaticScene(self.root, bpy.context.scene).capture_authoring()
        request = dict(version='0.4.0', message_type='request', request_id=identity, op=op if '.' in op else 'anatomy.'+op,
            params=dict(scene_id=self.root.name, expected_scene_revision=inventory['revision'], **params))
        result = execute(request, self.root, bpy.context.scene, self.folder)
        return result

    def test_readonly_preview_shared_free_publication_and_replay(self):
        before = set(bpy.data.objects); preview = self.send('smooth_base_preview', 'preview', **self.params)
        self.assertEqual(preview['status'], 'success', preview); self.assertEqual(set(bpy.data.objects), before)
        with patch('anthroforge.adapters.authoring.solver.NativeFiberSolver.solve', side_effect=AssertionError('solver')):
            output = self.send('smooth_base_publish', 'publish', preview_id=preview['base_surface']['id'])
        self.assertEqual(output['status'], 'success', output); self.assertEqual(len(self.root.af_vcp_system.fibers), 5)
        self.assertTrue(all(f.behavior_mode == 'FREE' for f in self.root.af_vcp_system.fibers))
        a, b = output['native_ids'].values(); self.assertEqual(a['fibers'][-1], b['fibers'][0])
        replay = self.send('smooth_base_publish', 'replay', preview_id=preview['base_surface']['id'])
        self.assertTrue(replay.get('replayed'), replay); self.assertEqual(len(self.root.af_vcp_system.muscles), 2)

    def test_source_edit_invalidates_preview(self):
        preview = self.send('smooth_base_preview', 'preview', **self.params); self.assertEqual(preview['status'], 'success', preview)
        self.source.data.vertices[0].co.x += .1; self.source.data.update()
        result = self.send('smooth_base_publish', 'publish', preview_id=preview['base_surface']['id'])
        self.assertEqual(result['status'], 'unresolved'); self.assertIn('STALE_BASE_GEOMETRY', str(result))

    def test_retained_attachment_extensions_are_part_of_expected_surface(self):
        for vertex in self.source.data.vertices: vertex.co.y = .5 + .75*vertex.co.y
        self.source.data.update()
        row = capture(bpy.context.scene, [self.source.name])[self.source.name]
        self.params.update(topology_digest=row['topology_digest'], geometry_digest=row['geometry_digest'])
        for part in self.params['patches']:
            for pair in part['endpoints']:
                for pin in pair.values(): pin['mode'] = 'extend'
        preview = self.send('smooth_base_preview', 'extended-preview', **self.params)
        self.assertEqual(preview['status'], 'success', preview)
        output = self.send('smooth_base_publish', 'extended-publish', preview_id=preview['base_surface']['id'])
        self.assertEqual(output['status'], 'success', output)

    def test_failed_fit_cannot_publish(self):
        self.params['settings']['max_shape_error'] = 1e-10
        preview = self.send('smooth_base_preview', 'preview', **self.params); self.assertEqual(preview['status'], 'unresolved', preview)
        result = self.send('smooth_base_publish', 'publish', preview_id=preview['base_surface']['id'])
        self.assertIn('BASE_PREVIEW_UNRESOLVED', str(result)); self.assertEqual(len(self.root.af_vcp_system.fibers), 0)

    def test_publication_rolls_back_on_geometry_failure(self):
        preview = self.send('smooth_base_preview', 'preview', **self.params); self.assertEqual(preview['status'], 'success', preview)
        with patch('anthroforge.adapters.authoring.smooth_publication.verify_geometry', side_effect=ValueError('forced')):
            result = self.send('smooth_base_publish', 'publish', preview_id=preview['base_surface']['id'])
        self.assertNotEqual(result['status'], 'success'); self.assertEqual(len(self.root.af_vcp_system.fibers), 0)
        self.assertEqual(len(self.root.af_vcp_system.muscles), 0); self.assertEqual(len(self.root.af_vcp_system.authored_points), 0)

    def test_seam_pin_conflict_is_not_silently_ignored(self):
        self.params['patches'][1]['endpoints'][0]['end']['position'][0] += .01
        result = self.send('smooth_base_preview', 'conflict', **self.params)
        self.assertIn('BASE_SEAM_PIN_CONFLICT', str(result)); self.assertEqual(len(self.root.af_vcp_system.fibers), 0)

    def test_editor_commit_and_resampling_update_shared_lofts(self):
        from anthroforge.adapters import free_fiber_editor as editor
        from anthroforge.core.visualization.fiber_surface_sync import evaluate_surface_record
        preview = self.send('smooth_base_preview', 'preview', **self.params)
        result = self.send('smooth_base_publish', 'publish', preview_id=preview['base_surface']['id'])
        shared = result['native_ids']['0']['fibers'][-1]; fiber = next(f for f in self.root.af_vcp_system.fibers if f.id == shared)
        surfaces = list(self.root.af_vcp_system.fiber_surfaces)
        before = [np.asarray(evaluate_surface_record(self.root, bpy.context.scene, s).vertices) for s in surfaces]
        objects = editor.open_edit(self.root, bpy.context.scene, fiber); editor.convert_bezier(self.root, fiber)
        objects[0].data.splines[0].bezier_points[15].co.z += .05; fiber.free_sampling_resolution = 65
        with patch('anthroforge.adapters.authoring.solver.NativeFiberSolver.solve', side_effect=AssertionError('solver')):
            editor.apply(self.root, bpy.context.scene, fiber)
        after = [np.asarray(evaluate_surface_record(self.root, bpy.context.scene, s).vertices) for s in surfaces]
        for a, b in zip(before, after): self.assertTrue(a.shape != b.shape or np.max(np.abs(a-b)) > .001)

    def test_support_edit_invalidates_preview(self):
        preview = self.send('smooth_base_preview', 'preview', **self.params)
        support = next(o for o in bpy.context.scene.objects if o.type == 'MESH' and o != self.source)
        support.location.z += .1; bpy.context.view_layer.update()
        result = self.send('smooth_base_publish', 'publish', preview_id=preview['base_surface']['id'])
        self.assertIn('STALE_BASE_SUPPORTS', str(result))

    def test_journal_failure_restores_scene_and_retry_can_publish(self):
        from anthroforge.core.authoring.storage import FileStore
        preview = self.send('smooth_base_preview', 'preview', **self.params); original = FileStore.put
        def fail(store, category, key, value):
            if category == 'smooth_base_receipts': raise OSError('forced receipt failure')
            return original(store, category, key, value)
        with patch.object(FileStore, 'put', fail):
            result = self.send('smooth_base_publish', 'publish', preview_id=preview['base_surface']['id'])
        self.assertNotEqual(result['status'], 'success'); self.assertFalse(self.root.af_vcp_system.fibers)
        result = self.send('smooth_base_publish', 'retry', preview_id=preview['base_surface']['id'])
        self.assertEqual(result['status'], 'success', result); self.assertEqual(len(self.root.af_vcp_system.fibers), 5)

    def test_failed_edit_restores_material_stations(self):
        from anthroforge.adapters import free_fiber_editor as editor
        from anthroforge.core.vcp.free_surface_stations import KEY
        preview = self.send('smooth_base_preview', 'preview', **self.params)
        self.send('smooth_base_publish', 'publish', preview_id=preview['base_surface']['id'])
        fiber = self.root.af_vcp_system.fibers[0]; identity = fiber.id
        before = [s[KEY] for s in self.root.af_vcp_system.fiber_surfaces]
        objects = editor.open_edit(self.root, bpy.context.scene, fiber); objects[0].data.splines[0].points[15].co.z += .05
        with patch('anthroforge.app.use_cases.free_fiber.rebuild', side_effect=ValueError('forced rebuild failure')):
            with self.assertRaises(ValueError): editor.apply(self.root, bpy.context.scene, fiber)
        self.assertEqual([s[KEY] for s in self.root.af_vcp_system.fiber_surfaces], before)
        editor.cancel(self.root, next(f for f in self.root.af_vcp_system.fibers if f.id == identity))

    def test_support_deformation_updates_both_heads_without_solver(self):
        from anthroforge.core.visualization.fiber_surface_sync import evaluate_surface_record
        preview = self.send('smooth_base_preview', 'preview', **self.params)
        self.send('smooth_base_publish', 'publish', preview_id=preview['base_surface']['id'])
        surfaces = list(self.root.af_vcp_system.fiber_surfaces)
        before = [np.asarray(evaluate_surface_record(self.root, bpy.context.scene, s).vertices) for s in surfaces]
        support = next(o for o in bpy.context.scene.objects if o.type == 'MESH' and o != self.source and o.location.y > 3)
        for vertex in support.data.vertices: vertex.co.z *= 1.05
        support.data.update(); bpy.context.view_layer.update()
        with patch('anthroforge.core.vcp.fiber_progressive.begin_fiber_solve', side_effect=AssertionError('solver')):
            result = self.send('fibers.recompute', 'deformed', fiber_ids=[f.id for f in self.root.af_vcp_system.fibers])
        self.assertEqual(result['status'], 'success', result)
        for s, old in zip(surfaces, before):
            new = np.asarray(evaluate_surface_record(self.root, bpy.context.scene, s).vertices)
            self.assertTrue(old.shape != new.shape or np.max(np.abs(old-new)) > .01)
