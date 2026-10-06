"""Real publication, identity, authoring and visual region lifecycle."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from time import sleep
from unittest.mock import patch
import bpy
import numpy as np
from _helpers import BlenderTestCase
from _stacking_fixture import fixture
from test_muscle_stacking import refresh, call
from test_muscle_pairs import finish, response_failure
from test_muscle_section_profile import mesh
from anthroforge.core.muscle_pairs import runtime, configuration
from anthroforge.core.muscle_relationships import store, service, blender_identity
from anthroforge.adapters import relationship_region_editor as editor


def first(state):
    return next(r for r in state['relationships'] if r['status'] == 'supported')


def configure(root, state, **change):
    service.configure((bpy.context.scene, root), dict(relationships=[dict(id=first(state)['id'], **change)]), state['relationship_revision'])
    finish(); return runtime.inspect(bpy.context.scene, root)


@contextmanager
def fail_after_assignment(root, document, expected):
    with ORIGINAL_TRANSACTION(root, document, expected): raise ValueError('relationship write failed')
    yield


ORIGINAL_TRANSACTION = store.transaction


class RelationshipBlenderTests(BlenderTestCase):
    def test_preview_preserves_journal_and_uninitialized_identity(self):
        root, _, _ = fixture(); before = (root.get(store.KEY), root.get(store.NAMESPACE))
        with TemporaryDirectory() as journal:
            result = call(root, journal, 'stacking_preview', configuration=dict(stacking=False))
            self.assertEqual(result['status'], 'success', result)
            self.assertEqual(result['entities'][-1]['kind'], 'muscle_stacking_preview')
            self.assertFalse([p for p in Path(journal).rglob('*') if p.is_file()])
            self.assertEqual((root.get(store.KEY), root.get(store.NAMESPACE)), before)

    def test_region_source_faces_select_together(self):
        import bmesh
        root, _, _ = fixture(); state = refresh(root)
        draft = editor.begin(root, bpy.context.scene, first(state)['id']); bm = bmesh.from_edit_mesh(draft.objects[0].data)
        bm.faces.ensure_lookup_table(); bm.faces[0].select_set(True); editor.synchronize_faces(draft)
        source = int(draft.domain.sources[0]); part = int(draft.domain.parts[0])
        group = [i for i, key in enumerate(zip(draft.domain.parts, draft.domain.sources)) if key == (part, source)]
        self.assertGreater(len(group), 1); self.assertTrue(all(bm.faces[i].select for i in group))
        bm.faces[0].select_set(False); editor.synchronize_faces(draft)
        self.assertFalse(any(bm.faces[i].select for i in group)); editor.cancel(root)

    def test_partial_mesh_publication_failure_rolls_back(self):
        from anthroforge.core.muscle_stacking import publication
        root, _, cover = fixture(); own = mesh(root, cover).copy(); refresh(root); blob = root[store.KEY]
        original = publication.write; calls = []
        def fail_once(obj, points):
            calls.append(obj)
            original(obj, points)
            if len(calls) == 4: raise ValueError('injected mesh publication failure')
        with patch.object(publication, 'write', fail_once): result = refresh(root)
        self.assertEqual(result['stacking']['publication'], 'failed'); self.assertEqual(root[store.KEY], blob)
        np.testing.assert_array_equal(mesh(root, cover), own)

    def test_authoring_and_ui_revision_agree_and_preview_is_readonly(self):
        root, _, cover = fixture(); state = refresh(root); before = mesh(root, cover).copy(); blob = root[store.KEY]
        with TemporaryDirectory() as journal:
            report = call(root, journal, 'stacking_inspect'); current = report['entities'][0]['detection']
            self.assertEqual(current['relationship_revision'], state['relationship_revision'])
            change = dict(relationships=[dict(id=first(state)['id'], excluded=True)])
            result = call(root, journal, 'stacking_preview', configuration=change)
            self.assertEqual(result['status'], 'success', result); self.assertEqual(root[store.KEY], blob)
            np.testing.assert_array_equal(mesh(root, cover), before); self.assertEqual(result['entities'][-1]['kind'], 'muscle_stacking_preview')
            result = call(root, journal, 'stacking_configure', configuration=change, expected_scene_revision=report['scene_revision'],
                expected_configuration_revision=current['configuration_revision'], expected_relationship_revision=state['relationship_revision'])
            self.assertEqual(result['status'], 'success', result); finish()
            self.assertEqual(first(runtime.inspect(bpy.context.scene, root))['state'], 'excluded')

    def test_raw_order_survives_manual_conflict(self):
        root, _, _ = fixture(); state = refresh(root); row = first(state)
        result = configure(root, state, cover=row['underlying'])
        self.assertEqual(result['stacking']['status'], 'incomplete')
        self.assertEqual(first(result)['status'], 'supported')
        self.assertEqual(first(result)['state'], 'manual_order_conflict')
        result = configure(root, result, cover=None); self.assertEqual(result['stacking']['status'], 'complete')

    def test_document_assignment_failure_restores_own_and_records(self):
        root, _, cover = fixture(); own = mesh(root, cover).copy(); refresh(root); blob = root[store.KEY]
        with patch.object(store, 'transaction', fail_after_assignment): result = refresh(root)
        self.assertEqual(result['stacking']['publication'], 'failed'); self.assertEqual(root[store.KEY], blob)
        np.testing.assert_array_equal(mesh(root, cover), own)
        self.assertEqual(refresh(root)['stacking']['publication'], 'published')

    def test_downstream_failure_rolls_back_both(self):
        root, _, cover = fixture(); own = mesh(root, cover).copy(); refresh(root); blob = root[store.KEY]
        with patch('anthroforge.core.muscle_stacking.downstream.refresh', side_effect=ValueError('failure')): result = refresh(root)
        self.assertEqual(root[store.KEY], blob); np.testing.assert_array_equal(mesh(root, cover), own)
        self.assertFalse(result['relationships'][0]['current'])

    def test_journal_failure_rolls_back_intent(self):
        from anthroforge.core.authoring.storage import FileStore
        root, _, _ = fixture(); state = refresh(root); before = root[store.KEY]
        with TemporaryDirectory() as journal:
            report = call(root, journal, 'stacking_inspect')
            with patch.object(FileStore, 'put', response_failure(FileStore.put)):
                result = call(root, journal, 'stacking_configure', configuration=dict(relationships=[dict(id=first(state)['id'], excluded=True)]),
                    expected_scene_revision=report['scene_revision'], expected_configuration_revision=state['configuration_revision'],
                    expected_relationship_revision=state['relationship_revision'])
            self.assertNotEqual(result['status'], 'success'); self.assertEqual(root[store.KEY], before)

    def test_stable_identity_reopen_and_stale_guards(self):
        root, _, _ = fixture(); state = refresh(root); identity = first(state)['id']; name = root.name
        configure(root, state, excluded=True)
        with TemporaryDirectory() as folder:
            path = str(Path(folder)/'relationships.blend'); bpy.ops.wm.save_as_mainfile(filepath=path); bpy.ops.wm.open_mainfile(filepath=path)
            root = bpy.data.objects[name]; finish(); result = runtime.inspect(bpy.context.scene, root)
            self.assertEqual(first(result)['id'], identity); self.assertEqual(first(result)['state'], 'excluded')
            with self.assertRaises(ValueError): service.configure((bpy.context.scene, root), dict(relationships=[dict(id=identity, excluded=False)]), 0)

    def test_region_editor_apply_cancel_and_geometry_rejection(self):
        root, _, _ = fixture(); state = refresh(root); identity = first(state)['id']; blob = root[store.KEY]
        draft = editor.begin(root, bpy.context.scene, identity); bpy.ops.mesh.select_all(action='SELECT')
        editor.apply(root); finish(); row = first(runtime.inspect(bpy.context.scene, root))
        self.assertTrue(row['intent']['region']['faces']); self.assertFalse(editor.SESSIONS)
        before = root[store.KEY]; draft = editor.begin(root, bpy.context.scene, identity)
        bpy.ops.transform.translate(value=(1, 0, 0))
        with self.assertRaises(ValueError): editor.apply(root)
        editor.cancel(root); self.assertEqual(root[store.KEY], before)

    def test_region_editor_stale_and_save_does_not_apply(self):
        root, _, _ = fixture(); state = refresh(root); identity = first(state)['id']; name = root.name
        draft = editor.begin(root, bpy.context.scene, identity); bpy.ops.mesh.select_all(action='SELECT')
        before = root[store.KEY]
        with TemporaryDirectory() as folder:
            path = str(Path(folder)/'draft.blend'); bpy.ops.wm.save_as_mainfile(filepath=path)
            self.assertEqual(root[store.KEY], before); self.assertTrue(draft.objects)
            bpy.ops.wm.open_mainfile(filepath=path); root = bpy.data.objects[name]; finish()
            self.assertFalse(editor.SESSIONS); self.assertFalse(any(o.get(editor.TAG) for o in bpy.data.objects))
        editor.begin(root, bpy.context.scene, identity); bpy.ops.mesh.select_all(action='SELECT'); refresh(root)
        with self.assertRaises(ValueError): editor.apply(root)
        editor.cancel(root)

    def test_undo_redo_restores_intent(self):
        root, _, _ = fixture(); state = refresh(root); name = root.name
        bpy.ops.ed.undo_push(message='Relationships before'); configure(root, state, excluded=True)
        bpy.ops.ed.undo_push(message='Relationships excluded'); bpy.ops.ed.undo(); root = bpy.data.objects[name]; sleep(.16); finish()
        self.assertFalse(first(runtime.inspect(bpy.context.scene, root))['intent'].get('excluded'))
        bpy.ops.ed.redo(); root = bpy.data.objects[name]; sleep(.16); finish()
        self.assertTrue(first(runtime.inspect(bpy.context.scene, root))['intent']['excluded'])

    def test_duplicate_root_rekeys_and_unknown_collision_reports(self):
        root, _, _ = fixture(); refresh(root); blender_identity.reset(); old = store.read(root)['namespace']
        duplicate = root.copy(); bpy.context.scene.collection.objects.link(duplicate); blender_identity.discover(duplicate)
        self.assertNotEqual(store.read(duplicate)['namespace'], old)
        duplicate[store.NAMESPACE] = old; duplicate[store.KEY] = root[store.KEY]; blender_identity.reset()
        with self.assertRaises(ValueError): blender_identity.ensure_unique(root)
        blender_identity.rekey(duplicate); blender_identity.ensure_unique(root)

    def test_corrupt_document_preserved_and_no_current_stacking(self):
        root, _, _ = fixture(); refresh(root); root[store.KEY] = '{broken'
        result = refresh(root)
        self.assertEqual(root[store.KEY], '{broken'); self.assertEqual(result['status'], 'failed')
        self.assertIn('RELATIONSHIP_DOCUMENT', result['relationship_error'])

    def test_display_and_selection_do_not_evaluate(self):
        root, _, _ = fixture(); state = refresh(root); revision = state['result_revision']
        draft = editor.begin(root, bpy.context.scene, first(state)['id']); bpy.ops.mesh.select_all(action='SELECT')
        draft.objects[0].color = (.7, .2, .4, 1); bpy.context.view_layer.update()
        self.assertEqual(runtime.inspect(bpy.context.scene, root)['result_revision'], revision); editor.cancel(root)
