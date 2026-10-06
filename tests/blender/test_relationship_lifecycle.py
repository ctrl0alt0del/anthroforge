"""Stale jobs, replay, deletion and guarded footprint access in Blender."""
from tempfile import TemporaryDirectory
from uuid import uuid4
from unittest.mock import patch
import bpy
from _helpers import BlenderTestCase
from _stacking_fixture import fixture
from test_muscle_stacking import refresh, call
from test_muscle_relationships import first
from test_muscle_pairs import finish
from anthroforge.core.muscle_pairs import runtime
from anthroforge.core.muscle_relationships import store
from anthroforge.app.authoring.api import execute


class RelationshipLifecycle(BlenderTestCase):
    def test_missing_native_policy_restores_own_and_reports_unavailable(self):
        import numpy as np
        from test_muscle_section_profile import mesh
        root, _, cover = fixture(); own = mesh(root, cover).copy(); refresh(root)
        runtime.COORDINATOR.remove(runtime.key(bpy.context.scene, root))
        with patch.object(runtime.COORDINATOR, 'factory', side_effect=RuntimeError('RELATIONSHIP_NATIVE_UNAVAILABLE')):
            result = refresh(root)
        self.assertEqual(result['status'], 'unavailable'); np.testing.assert_array_equal(mesh(root, cover), own)

    def test_authoring_intent_evaluates_with_automatic_refresh_off(self):
        root, _, _ = fixture(); root.af_pair_settings.automatic = False; state = refresh(root)
        with TemporaryDirectory() as journal:
            report = call(root, journal, 'stacking_inspect')
            result = call(root, journal, 'stacking_configure', configuration=dict(relationships=[dict(id=first(state)['id'], excluded=True)]),
                expected_scene_revision=report['scene_revision'], expected_configuration_revision=state['configuration_revision'],
                expected_relationship_revision=state['relationship_revision'])
            self.assertEqual(result['status'], 'success', result); finish()
            state = runtime.inspect(bpy.context.scene, root); self.assertEqual(state['status'], 'complete')
            self.assertEqual(first(state)['state'], 'excluded')

    def test_rapid_edits_publish_latest_and_deletion_keeps_record(self):
        root, _, _ = fixture(); state = refresh(root); before = set(store.read(root)['records'])
        for i in range(12): root.af_pair_settings.radius = .2 + i*.001
        finish(); state = runtime.inspect(bpy.context.scene, root)
        self.assertEqual(state['status'], 'complete'); self.assertAlmostEqual(root.af_pair_settings.radius, .211)
        root.af_vcp_system.muscles.remove(0); runtime.refresh(bpy.context.scene, root, True); finish()
        self.assertTrue(before <= set(store.read(root)['records']))
        self.assertEqual(next(iter(store.read(root)['records'].values()))['state'], 'missing_reference')

    def test_replay_after_automatic_evidence_refresh(self):
        root, _, _ = fixture(); state = refresh(root)
        with TemporaryDirectory() as journal:
            report = call(root, journal, 'stacking_inspect')
            params = dict(scene_id=root.name, configuration=dict(relationships=[dict(id=first(state)['id'], excluded=True)]),
                expected_scene_revision=report['scene_revision'], expected_configuration_revision=state['configuration_revision'],
                expected_relationship_revision=state['relationship_revision'])
            request = dict(dsl='anthroforge.authoring.protocol', version='0.4.0', message_type='request', request_id=str(uuid4()), op='muscles.stacking_configure', params=params)
            self.assertEqual(execute(request, root, bpy.context.scene, journal)['status'], 'success'); finish()
            refresh(root); revision = store.read(root)['revision']
            result = execute(request, root, bpy.context.scene, journal)
            self.assertEqual(result['status'], 'success', result); self.assertTrue(result['replayed'])
            self.assertEqual(store.read(root)['revision'], revision)

    def test_stable_footprint_target_and_clearing_through_authoring(self):
        root, _, _ = fixture(); state = refresh(root)
        with TemporaryDirectory() as journal:
            result = call(root, journal, 'pairs_order_footprint', relationship_id=first(state)['id'], expected_result_revision=state['result_revision'])
            self.assertEqual(result['status'], 'success', result)
            report = call(root, journal, 'stacking_inspect')
            result = call(root, journal, 'stacking_configure', configuration=dict(relationships=[dict(id=first(state)['id'], cover=None, region=None)]),
                expected_scene_revision=report['scene_revision'], expected_configuration_revision=state['configuration_revision'],
                expected_relationship_revision=state['relationship_revision'])
            self.assertEqual(result['status'], 'success', result)

    def test_changed_document_rejects_running_result(self):
        root, _, _ = fixture(); refresh(root); original = store.read(root)
        runtime.refresh(bpy.context.scene, root, True); runtime.COORDINATOR.tick()
        with store.transaction(root, original, original['revision']): pass
        revision = store.read(root)['revision']; finish(); result = runtime.inspect(bpy.context.scene, root)
        self.assertEqual(result['stacking']['publication'], 'failed')
        self.assertEqual(store.read(root)['revision'], revision)

    def test_shutdown_cleans_region_draft_and_restarts(self):
        from anthroforge.ui import muscle_pairs
        from anthroforge.adapters import relationship_region_editor as editor
        root, _, _ = fixture(); state = refresh(root); editor.begin(root, bpy.context.scene, first(state)['id'])
        muscle_pairs.unregister(); self.assertFalse(editor.SESSIONS)
        self.assertFalse(any(o.get(editor.TAG) for o in bpy.data.objects))
        muscle_pairs.register(); finish(); self.assertEqual(runtime.inspect(bpy.context.scene, root)['status'], 'complete')
