"""Explicit crossing policy through native capture, coordinator, authoring and reopening."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4
import bpy
import numpy as np
from _helpers import BlenderTestCase
from _explicit_stacking_fixture import crossing_fixture
from test_muscle_stacking import refresh, call
from test_muscle_pairs import finish
from test_muscle_section_profile import mesh
from anthroforge.core.muscle_relationships import service, store
from anthroforge.core.muscle_pairs import runtime


def assign(root, under, cover):
    state = refresh(root); pair = [[m.id, 'source', 'A'] for m in (under, cover)]
    change = dict(relationships=[dict(pair=pair, cover=pair[1], mode='explicit')])
    service.configure((bpy.context.scene, root), change, state['relationship_revision']); finish()
    return runtime.inspect(bpy.context.scene, root)


def protect(root, point, journal):
    from anthroforge.app.authoring.api import execute
    from anthroforge.adapters.authoring.inventory import capture
    return execute(dict(dsl='anthroforge.authoring.protocol', version='0.4.0', message_type='request', request_id=str(uuid4()),
        op='points.edit', params=dict(scene_id=root.name, point_id=point.id, stacking_fixed=True, protected_crease=True,
        expected_scene_revision=capture(root, bpy.context.scene)['revision'])), root, bpy.context.scene, journal)


class ExplicitBlenderTests(BlenderTestCase):
    def test_protection_edit_preserves_paths_and_persists(self):
        root, _, _ = crossing_fixture(); name = root.name; point = root.af_vcp_system.authored_points[0]; identity = point.id
        before = [f.free_path_json for f in root.af_vcp_system.fibers]
        with TemporaryDirectory() as folder:
            with patch('anthroforge.app.use_cases.free_point_edit.graph_action', side_effect=AssertionError('Unexpected fiber reroute')):
                result = protect(root, point, folder)
            self.assertEqual(result['status'], 'success', result)
            self.assertTrue(point.stacking_fixed and point.protected_crease)
            self.assertEqual(before, [f.free_path_json for f in root.af_vcp_system.fibers])
            path = str(Path(folder)/'protection.blend'); bpy.ops.wm.save_as_mainfile(filepath=path); bpy.ops.wm.open_mainfile(filepath=path)
            root = bpy.data.objects[name]; point = next(p for p in root.af_vcp_system.authored_points if p.id == identity)
            self.assertTrue(point.stacking_fixed and point.protected_crease)

    def test_explicit_keeps_bindings_and_intrinsic_geometry(self):
        root, under, cover = crossing_fixture(); base = mesh(root, cover, 'BASE').copy(); own = mesh(root, cover).copy()
        paths = [f.free_path_json for f in root.af_vcp_system.fibers]; state = assign(root, under, cover)
        self.assertEqual(state['stacking']['status'], 'complete', state)
        self.assertTrue(any(p['order']['status'] == 'intersecting_bases' for p in state['pairs']))
        self.assertGreater(np.max(np.linalg.norm(mesh(root, cover)-own, axis=1)), .01)
        np.testing.assert_array_equal(mesh(root, cover, 'BASE'), base)
        self.assertEqual(paths, [f.free_path_json for f in root.af_vcp_system.fibers])
        before = mesh(root, cover).copy(); refresh(root); np.testing.assert_array_equal(mesh(root, cover), before)
        root.af_pair_settings.stacking = False; finish(); np.testing.assert_array_equal(mesh(root, cover), own)

    def test_explicit_save_reopen_and_schema(self):
        from anthroforge.adapters.authoring.scene import StaticScene
        root, under, cover = crossing_fixture(); state = assign(root, under, cover)
        self.assertEqual(state['stacking']['status'], 'complete', state)
        name, mid = root.name, cover.id; before = mesh(root, cover).copy()
        with TemporaryDirectory() as folder:
            path = str(Path(folder)/'explicit.blend'); StaticScene(root, bpy.context.scene).save_debug_copy(path)
            bpy.ops.wm.open_mainfile(filepath=path); root = bpy.data.objects[name]
            cover = next(m for m in root.af_vcp_system.muscles if m.id == mid); state = refresh(root)
            self.assertEqual(state['stacking']['status'], 'complete', state)
            np.testing.assert_allclose(mesh(root, cover), before, atol=2e-6)
            self.assertEqual(store.read(root)['schema'], 2)
            self.assertTrue(any(r['intent'].get('mode') == 'explicit' for r in state['relationships']))
            self.assertTrue(all(not o.hide_get() and o.display_type != 'WIRE' for o in bpy.context.scene.objects if o.get('af_fiber_proxy')))

    def test_authoring_pair_assignment_and_clear(self):
        root, under, cover = crossing_fixture(); state = refresh(root)
        pair = [[m.id, 'source', 'A'] for m in (under, cover)]
        with TemporaryDirectory() as journal:
            report = call(root, journal, 'stacking_inspect')
            result = call(root, journal, 'stacking_configure', configuration=dict(relationships=[dict(pair=pair, cover=pair[1], mode='explicit')]),
                expected_scene_revision=report['scene_revision'], expected_configuration_revision=state['configuration_revision'],
                expected_relationship_revision=state['relationship_revision'])
            self.assertEqual(result['status'], 'success', result); finish()
            state = runtime.inspect(bpy.context.scene, root); self.assertEqual(state['stacking']['status'], 'complete', state)
            row = next(r for r in state['relationships'] if r['intent'].get('mode') == 'explicit')
            service.configure((bpy.context.scene, root), dict(relationships=[dict(id=row['id'], cover=None, mode='automatic')]), state['relationship_revision'])
            finish(); self.assertEqual(runtime.inspect(bpy.context.scene, root)['stacking']['status'], 'incomplete')
