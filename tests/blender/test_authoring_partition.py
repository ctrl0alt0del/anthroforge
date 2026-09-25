"""Public API, guarded automatic repair, actual native output and persistence."""
import json
import numpy as np
import bpy
from pathlib import Path
from unittest.mock import patch
from test_authoring_smooth_base import SmoothBaseTests
from anthroforge.adapters.authoring.transfer import capture
from anthroforge.adapters.authoring.smooth_publication import verify_geometry
from anthroforge.adapters.authoring.scene import StaticScene


def limits():
    return dict(along_axis=[0, 1, 0], across_axis=[1, 0, 0], blend_distance=.25,
        max_displacement=.25, max_depth_gap=.1, max_outline_error=1e-5)


class PartitionTests(SmoothBaseTests):
    def test_biceps_actual_branch_assembly(self):
        params = json.loads((Path(__file__).parents[1]/'fixtures/biceps_border_overlap.json').read_text()); params.pop('provenance')
        result = self.send('partition_base_surfaces', 'biceps-fixture', **params)
        self.assertEqual(result['status'], 'success', result)
        data = json.loads(Path(result['assets'][0]['path']).read_text())
        self.assertEqual(data['quality']['spatial']['crossing_pairs'], 0)
        self.assertEqual(data['quality']['spatial']['degenerate_triangles'], 0)
        self.assertEqual(sum(map(len, data['paths'])), 4)
        for before, after in zip(params['paths'], data['paths']):
            np.testing.assert_array_equal(np.asarray(before)[:, [0, -1]], np.asarray(after)[:, [0, -1]])

    def overlap(self):
        for i, vertex in enumerate(self.source.data.vertices):
            patch_index, local = divmod(i, 91); row, col = divmod(local, 13)
            offset = .2*np.sin(np.pi*col/12)
            vertex.co.x += offset*(row/6 if patch_index == 0 else -(1-row/6))
        self.source.data.update(); row = capture(bpy.context.scene, [self.source.name])[self.source.name]
        self.params.update(topology_digest=row['topology_digest'], geometry_digest=row['geometry_digest'], seams=[])
        self.params['settings'].update(max_shape_error=.3)
        self.params['overlap_repairs'] = [dict(patch_ids=['0', '1'], sides=[1, 0], settings=limits())]

    def test_explicit_repair_preview_is_readonly(self):
        self.overlap(); values = np.array([v.co[:] for v in self.source.data.vertices]).reshape(2, 7, 13, 3)[:, [0, -1]]
        before = set(bpy.data.objects)
        result = self.send('partition_base_surfaces', 'explicit', paths=values.tolist(), sides=[1, 0], settings=limits())
        self.assertEqual(result['status'], 'success', result); self.assertEqual(before, set(bpy.data.objects))
        self.assertEqual(result['partition']['quality']['spatial']['crossing_pairs'], 0)

    def test_automatic_repair_publishes_native_and_reopens(self):
        self.overlap(); preview = self.send('smooth_base_preview', 'auto-preview', **self.params)
        self.assertEqual(preview['status'], 'success', preview)
        with patch('anthroforge.adapters.authoring.solver.NativeFiberSolver.solve', side_effect=AssertionError('solver')):
            output = self.send('smooth_base_publish', 'auto-publish', preview_id=preview['base_surface']['id'])
        self.assertEqual(output['status'], 'success', output); self.assertEqual(len(self.root.af_vcp_system.fibers), 6)
        replay = self.send('smooth_base_publish', 'auto-replay', preview_id=preview['base_surface']['id']); self.assertTrue(replay['replayed'])
        record = json.loads(open(preview['assets'][0]['path']).read()); name = self.root.name
        StaticScene(self.root, bpy.context.scene).save_debug_copy(self.folder+'/partition.blend')
        bpy.ops.wm.open_mainfile(filepath=self.folder+'/partition.blend', load_ui=False); self.root = bpy.data.objects[name]
        verify_geometry(self.root, bpy.context.scene, record, output['native_ids'])
        fibers = [o for o in bpy.context.scene.objects if o.get('af_fiber_proxy')]
        self.assertTrue(fibers); self.assertTrue(all(not o.hide_get() and o.display_type == 'TEXTURED' for o in fibers))

    def test_automatic_repair_is_explicit_not_inferred(self):
        self.overlap(); self.params.pop('overlap_repairs')
        result = self.send('smooth_base_preview', 'no-repair', **self.params)
        self.assertEqual(result['status'], 'unresolved', result)

    def test_repair_refuses_ambiguous_shared_ownership(self):
        self.overlap(); self.params['seams'] = [dict(id='same', first=dict(patch_id='0', side=1), second=dict(patch_id='1', side=0))]
        result = self.send('smooth_base_preview', 'ambiguous', **self.params)
        self.assertIn('PARTITION_SHARED_FIBER_CONFLICT', str(result))

    def test_stale_standalone_request_does_not_replay(self):
        self.overlap(); values = np.array([v.co[:] for v in self.source.data.vertices]).reshape(2, 7, 13, 3)[:, [0, -1]]
        first = self.send('partition_base_surfaces', 'stale', paths=values.tolist(), sides=[1, 0], settings=limits())
        self.assertEqual(first['status'], 'success', first)
        from anthroforge.app.authoring.api import execute
        request = dict(version='0.4.0', message_type='request', request_id='stale', op='anatomy.partition_base_surfaces',
            params=dict(scene_id=self.root.name, expected_scene_revision='old', paths=values.tolist(), sides=[1, 0], settings=limits()))
        result = execute(request, self.root, bpy.context.scene, self.folder)
        self.assertEqual(result['status'], 'unresolved')
