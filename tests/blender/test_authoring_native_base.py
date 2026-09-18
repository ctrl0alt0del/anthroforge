"""Native base fitting, stale data, atomic publication and ordinary file reload."""
import tempfile
from pathlib import Path
from unittest.mock import patch
import bpy
from _helpers import BlenderTestCase, root
from _transfer_fixture import run, message, snapshot
from _native_base_fixture import fixture, planned, plan_params, read_asset, prepared_square
from anthroforge.app.authoring.api import execute
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.core.authoring.storage import FileStore
from anthroforge.core.authoring.schema import validate


class NativeBaseTests(BlenderTestCase):
    def setUp(self):
        super().setUp(); folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.folder, self.root = folder.name, root()

    def test_plan_is_read_only_and_pins_are_surface_bound(self):
        result, _params, _obj = planned(self.root, self.folder); validate(result, 'protocol')
        self.assertEqual(len(self.root.af_vcp_system.fibers), 0)
        part = read_asset(result)['parts'][0]
        self.assertEqual(part['fiber_count'], 2); self.assertEqual(part['middle_point_count'], 0)
        self.assertTrue(part['native_solver_validated']); self.assertEqual(part['topology']['euler'], 1)
        for fiber in part['fibers']:
            self.assertLessEqual(fiber['route_max_error'], .08)
            for point in fiber['points']:
                self.assertEqual(point['anchor']['offset'], 0)
                self.assertAlmostEqual(point['point'][0], .5, places=5)
                self.assertEqual(len(point['anchor']['surface_binding']['tri_vidx']), 3)

    def test_publication_replay_and_external_edit(self):
        result, _params, _obj = planned(self.root, self.folder)
        payload = message(self.root, 'publish_base_fibers', plan_id=result['plan']['id'])
        first = execute(payload, self.root, bpy.context.scene, self.folder); validate(first, 'protocol')
        self.assertTrue(first['published'], first); self.assertEqual(len(self.root.af_vcp_system.muscles), 0)
        self.assertTrue(execute(payload, self.root, bpy.context.scene, self.folder)['replayed'])
        self.assertEqual(len(self.root.af_vcp_system.fibers), 2)
        self.root.af_vcp_system.fibers[0].name = 'Manual change'
        replay = execute(payload, self.root, bpy.context.scene, self.folder)
        self.assertIn('BASE_EXTERNAL_EDIT', str(replay))

    def test_receipt_failure_rolls_back_objects_and_native_records(self):
        result, _params, _obj = planned(self.root, self.folder); objects = set(bpy.data.objects)
        original = FileStore.put
        with patch.object(FileStore, 'put', fail_receipt(original)):
            reply = run(self.root, self.folder, 'publish_base_fibers', plan_id=result['plan']['id'])
        self.assertEqual(reply['status'], 'failed', reply)
        self.assertEqual(set(bpy.data.objects), objects); self.assertEqual(len(self.root.af_vcp_system.fibers), 0)
        self.assertEqual(len(self.root.af_vcp_system.fiber_surfaces), 0)
        self.assertTrue(run(self.root, self.folder, 'publish_base_fibers', plan_id=result['plan']['id'])['published'])

    def test_source_edit_rejects_plan_and_publish(self):
        result, params, obj = planned(self.root, self.folder)
        obj.data.vertices[0].co.y += .1; obj.data.update()
        for op, values in [('plan_base_fibers', params), ('publish_base_fibers', dict(plan_id=result['plan']['id']))]:
            self.assertIn('STALE_BASE_GEOMETRY', str(run(self.root, self.folder, op, **values)))
        self.assertEqual(len(self.root.af_vcp_system.fibers), 0)

    def test_wrong_side_cannot_publish(self):
        document, _obj, definition = fixture(self.root, self.folder)
        base = run(self.root, self.folder, 'define_base', **definition)
        params = plan_params(document, base['base_surface']['id'])
        for binding in params['parts'][0]['bindings']:
            binding['facing'] = [-1, 0, 0]
        result = run(self.root, self.folder, 'plan_base_fibers', **params)
        self.assertEqual(result['status'], 'unresolved', result)
        self.assertIn('BASE_WRONG_SIDE', str(read_asset(result)))
        self.assertIn('BASE_PLAN_UNRESOLVED', str(run(self.root, self.folder, 'publish_base_fibers', plan_id=result['plan']['id'])))

    def test_identical_preview_revalidates_without_another_solve(self):
        from anthroforge.adapters.authoring.solver import NativeFiberSolver
        document, _obj, definition = fixture(self.root, self.folder)
        base = run(self.root, self.folder, 'define_base', **definition)
        payload = message(self.root, 'plan_base_fibers', **plan_params(document, base['base_surface']['id']))
        first = execute(payload, self.root, bpy.context.scene, self.folder); self.assertEqual(first['status'], 'success', first)
        with patch.object(NativeFiberSolver, 'solve', side_effect=AssertionError('Repeated solve')):
            second = execute(payload, self.root, bpy.context.scene, self.folder)
        self.assertTrue(second.get('replayed'), second); self.assertEqual(first['plan']['id'], second['plan']['id'])

    def test_topology_preserving_support_edit_requires_new_plan(self):
        result, _params, _obj = planned(self.root, self.folder)
        scp = self.root.af_scp_system.scps[0]; scp.geometry_object_ref.data.vertices[0].co.x += .01
        scp.geometry_object_ref.data.update()
        reply = run(self.root, self.folder, 'publish_base_fibers', plan_id=result['plan']['id'])
        self.assertIn('STALE_BASE_SUPPORTS', str(reply))

    def test_ready_completion_feeds_indexed_definition_and_native_plan(self):
        import numpy as np
        document, obj, definition = fixture(self.root, self.folder)
        preview, asset = prepared_square(self.root, self.folder, definition)
        corners = [int(np.linalg.norm(np.asarray(asset['vertices'])-v.co, axis=1).argmin()) for v in obj.data.vertices]
        selected = dict(id='main', head_ids=['main'], source_triangles=list(range(len(asset['triangles']))), boundary_vertex_ids=corners)
        base = run(self.root, self.folder, 'define_base', prepared_base_id=preview['base_surface']['id'],
                   heads=definition['heads'], anatomical_note=definition['anatomical_note'], patches=[selected])
        self.assertEqual(base['status'], 'success', base)
        result = run(self.root, self.folder, 'plan_base_fibers', **plan_params(document, base['base_surface']['id']))
        self.assertEqual(result['status'], 'success', result)

    def test_second_publication_preserves_existing_native_edits(self):
        from anthroforge.adapters.authoring.base_native import fingerprint
        result, params, _obj = planned(self.root, self.folder)
        first = run(self.root, self.folder, 'publish_base_fibers', plan_id=result['plan']['id'])
        self.root.af_vcp_system.fibers[0].name = 'Existing manually configured fiber'
        expected = fingerprint(self.root, bpy.context.scene, first['native_ids'])
        second = run(self.root, self.folder, 'plan_base_fibers', **params)
        self.assertEqual(second['status'], 'success', second)
        self.assertTrue(run(self.root, self.folder, 'publish_base_fibers', plan_id=second['plan']['id'])['published'])
        self.assertEqual(fingerprint(self.root, bpy.context.scene, first['native_ids']), expected)
        self.assertEqual(len(self.root.af_vcp_system.fibers), 4)

    def test_save_reload_retains_visible_native_curves(self):
        result, _params, _obj = planned(self.root, self.folder)
        self.assertTrue(run(self.root, self.folder, 'publish_base_fibers', plan_id=result['plan']['id'])['published'])
        name = self.root.name; path = Path(self.folder)/'base.blend'
        StaticScene(self.root, bpy.context.scene).save_debug_copy(path)
        bpy.ops.wm.open_mainfile(filepath=str(path)); self.root = bpy.data.objects[name]
        fibers = [o for o in bpy.context.scene.objects if o.get('af_fiber_proxy')]
        self.assertEqual(len(fibers), 2); self.assertTrue(all(o.type == 'CURVE' and not o.hide_get() and o.display_type != 'WIRE' for o in fibers))
        reply = run(self.root, self.folder, 'publish_base_fibers', plan_id=result['plan']['id'])
        self.assertTrue(reply.get('replayed'), reply)


def fail_receipt(original):
    def write(store, category, key, value):
        if category == 'native_base_receipts':
            raise OSError('Injected publication receipt failure')
        return original(store, category, key, value)
    return write
