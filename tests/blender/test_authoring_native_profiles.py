"""Live guards, preview immutability, typed replay and journal rollback."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import bpy
from _helpers import BlenderTestCase
from _profile_fixture import surface_only as _surface_only
from anthroforge.app.authoring.api import execute
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.adapters.authoring.records import record
from anthroforge.core.authoring.schema import validate
from anthroforge.core.authoring.profile_config import wire
from anthroforge.core.vcp.muscle_section_profile import reset_profile
from anthroforge.core.authoring.storage import FileStore


def request(owner, operation, identity, **params):
    return dict(dsl='anthroforge.authoring.protocol', version='0.4.0', message_type='request', request_id=identity,
                op='muscles.'+operation, params=dict(scene_id=owner.name, **params))


def call(owner, directory, payload):
    result = execute(payload, owner, bpy.context.scene, directory)
    validate(result, 'protocol')
    return result


def inspect(owner, directory, target, identity='inspect'):
    result = call(owner, directory, request(owner, 'profile_inspect', identity, target=target))
    assert result['status'] == 'success', result
    return result, dict(expected_scene_revision=result['scene_revision'], expected_base_revision=result['entities'][0]['base_revision'])


def create(owner, surface, directory, identity='create'):
    _, guards = inspect(owner, directory, dict(fiber_surface_id=surface.id))
    payload = request(owner, 'create_from_surface', identity, surface_id=surface.id, initial_configuration=wire(reset_profile(.2)), **guards)
    result = call(owner, directory, payload)
    assert result['published'], result
    return result, payload


def configure(owner, directory, muscle_id, identity='configure'):
    _, guards = inspect(owner, directory, dict(muscle_id=muscle_id), identity+'-inspect')
    payload = request(owner, 'profile_configure', identity, muscle_id=muscle_id, configuration=wire(reset_profile(.3)), **guards)
    return call(owner, directory, payload), payload


def base_fingerprint(owner, surface):
    from anthroforge.adapters.authoring.base_native import fingerprint
    ids = dict(part=dict(surface=surface.id, fibers=[ref.fiber_id for ref in surface.fiber_refs]))
    return fingerprint(owner, bpy.context.scene, ids)


class NativeProfileTests(BlenderTestCase):
    def test_preview_is_read_only_and_requires_live_revisions(self):
        owner, surface = _surface_only()
        with TemporaryDirectory() as directory:
            before = StaticScene(owner, bpy.context.scene).capture_authoring()
            _, guards = inspect(owner, directory, dict(fiber_surface_id=surface.id))
            payload = request(owner, 'profile_preview', 'preview', target=dict(fiber_surface_id=surface.id),
                configuration=wire(reset_profile(.3)), include_geometry=True, **guards)
            result = call(owner, directory, payload)
            self.assertEqual(result['status'], 'success', result)
            self.assertFalse(result['published']); self.assertTrue(Path(result['assets'][0]['path']).is_file())
            self.assertEqual(before['revision'], StaticScene(owner, bpy.context.scene).capture_authoring()['revision'])
            surface.name = 'Native edit'
            self.assertEqual(call(owner, directory, payload)['diagnostics'][0]['code'], 'STALE_SCENE_REVISION')

    def test_creation_retries_return_same_identity_after_shape_edits(self):
        owner, surface = _surface_only()
        sources = record(surface), [record(item) for item in owner.af_vcp_system.fibers], base_fingerprint(owner, surface)
        with TemporaryDirectory() as directory:
            created, payload = create(owner, surface, directory)
            muscle = owner.af_vcp_system.muscles[0]
            configured, configure_payload = configure(owner, directory, muscle.id)
            self.assertTrue(configured['published'], configured)
            self.assertTrue(call(owner, directory, configure_payload)['replayed'])
            retry = call(owner, directory, payload)
            self.assertTrue(retry['replayed']); self.assertEqual(len(owner.af_vcp_system.muscles), 1)
            self.assertEqual(retry['entities'][0]['configuration'], configured['entities'][0]['configuration'])
            self.assertEqual(sources, (record(surface), [record(item) for item in owner.af_vcp_system.fibers], base_fingerprint(owner, surface)))

    def test_manual_changes_stale_configure_receipt_and_id_reuse(self):
        owner, surface = _surface_only()
        with TemporaryDirectory() as directory:
            create(owner, surface, directory)
            muscle = owner.af_vcp_system.muscles[0]
            _, payload = configure(owner, directory, muscle.id)
            muscle.section_roundness = 2
            self.assertEqual(call(owner, directory, payload)['diagnostics'][0]['code'], 'STALE_PROFILE_RECEIPT')
            reused = request(owner, 'profile_inspect', payload['request_id'], target=dict(muscle_id=muscle.id))
            self.assertEqual(call(owner, directory, reused)['diagnostics'][0]['code'], 'REQUEST_ID_REUSED')

    def test_journal_failure_rolls_back_creation_and_preserves_sources(self):
        owner, surface = _surface_only()
        before = record(surface), [record(item) for item in owner.af_vcp_system.fibers]
        with TemporaryDirectory() as directory:
            _, guards = inspect(owner, directory, dict(fiber_surface_id=surface.id))
            payload = request(owner, 'create_from_surface', 'fail', surface_id=surface.id, **guards)
            original = FileStore.put
            with patch.object(FileStore, 'put', fail_response(original)):
                self.assertEqual(call(owner, directory, payload)['status'], 'failed')
            self.assertEqual(len(owner.af_vcp_system.muscles), 0)
            self.assertEqual(before, (record(surface), [record(item) for item in owner.af_vcp_system.fibers]))
            self.assertFalse(any(obj.get('af_muscle_id') for obj in bpy.context.scene.objects))
            self.assertNotIn('af_authoring_journal', owner)
            self.assertTrue(call(owner, directory, payload)['published'])

    def test_recovered_marker_rejects_cross_operation_id_reuse(self):
        owner, surface = _surface_only()
        with TemporaryDirectory() as directory:
            _, payload = create(owner, surface, directory)
            store = FileStore(directory); key = [owner.name, payload['request_id']]
            store.path('v04_profile_receipts', key).unlink(); store.path('v04_requests', key).unlink()
            reused = request(owner, 'profile_inspect', payload['request_id'], target=dict(fiber_surface_id=surface.id))
            self.assertEqual(call(owner, directory, reused)['diagnostics'][0]['code'], 'REQUEST_ID_REUSED')

    def test_changed_base_never_replays_creation(self):
        import json
        owner, surface = _surface_only()
        with TemporaryDirectory() as directory:
            _, payload = create(owner, surface, directory)
            proxy = next(obj for obj in bpy.context.scene.objects if obj.get('af_fiber_proxy'))
            points = json.loads(proxy['af_fiber_points_world']); points[len(points)//2][2] += .1
            proxy['af_fiber_points_world'] = json.dumps(points)
            from anthroforge.core.visualization.fiber_cache_lifecycle import invalidate_fiber_caches
            invalidate_fiber_caches(root=owner)
            self.assertEqual(call(owner, directory, payload)['diagnostics'][0]['code'], 'STALE_CREATION_RECEIPT')
            self.assertEqual(len(owner.af_vcp_system.muscles), 1)

    def test_marker_recovers_missing_journal_and_deletion_never_recreates(self):
        owner, surface = _surface_only()
        with TemporaryDirectory() as directory:
            created, payload = create(owner, surface, directory)
            store = FileStore(directory); key = [owner.name, payload['request_id']]
            store.path('v04_profile_receipts', key).unlink()
            store.path('v04_requests', key).unlink()
            self.assertTrue(call(owner, directory, payload)['replayed'])
            owner.af_vcp_system.muscles.remove(0)
            retry = call(owner, directory, payload)
            self.assertEqual(retry['diagnostics'][0]['code'], 'STALE_CREATION_RECEIPT')
            self.assertEqual(len(owner.af_vcp_system.muscles), 0)


def fail_response(original):
    def write(store, category, key, value):
        if category == 'v04_requests':
            raise OSError('Injected journal failure')
        return original(store, category, key, value)
    return write
