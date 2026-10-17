"""Public preview and ordinary path commit, including stale inputs and rollback."""
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch, Mock
from copy import deepcopy
import bpy
from _helpers import BlenderTestCase
from test_free_fibers import fixture
from anthroforge.app.use_cases import free_fiber as service
from anthroforge.app.authoring.api import execute
from anthroforge.adapters.authoring.inventory import capture
from anthroforge.core.visualization import free_fiber_runtime as runtime
from anthroforge.core.authoring.storage import FileStore
from anthroforge.core.vcp.free_path import decode


def setup_free():
    owner, surface, fiber, _ = fixture()
    service.configure_mode(owner, bpy.context.scene, fiber, 'FREE')
    return owner, surface, fiber


def request(owner, fiber, **extra):
    params = dict(scene_id=owner.name, fiber_id=fiber.id, expected_scene_revision=capture(owner, bpy.context.scene)['revision'],
                  expected_path_revision=fiber.free_path_revision, max_displacement=.01)
    return dict(dsl='anthroforge.authoring.protocol', version='0.4.0', message_type='request',
                request_id=str(uuid4()), op='fibers.tighten_preview', params=dict(params, **extra))


def call(owner, payload):
    return execute(payload, owner, bpy.context.scene, str(Path(__file__).parent))


def memory_store():
    rows = {}; store = Mock(directory=Path(__file__).parent)
    store.get.side_effect = lambda category, key: deepcopy(rows.get((category, tuple(key))))
    store.put.side_effect = lambda category, key, value: rows.update({(category, tuple(key)): deepcopy(value)})
    return store


def apply_preview(owner, fiber, path):
    payload = request(owner, fiber); payload['op'] = 'fibers.path_update'
    payload['params'].pop('max_displacement'); payload['params']['path'] = path
    with patch('anthroforge.app.authoring.api.FileStore', return_value=memory_store()):
        result = call(owner, payload); replay = call(owner, payload)
    return result, replay


class FiberTighteningTests(BlenderTestCase):
    def test_preview_apply_and_replay_with_real_disk_journal(self):
        from tempfile import TemporaryDirectory
        owner, _, fiber = setup_free(); preview_request = request(owner, fiber)
        with TemporaryDirectory() as folder:
            preview = execute(preview_request, owner, bpy.context.scene, folder)
            self.assertEqual(preview['status'], 'success', preview)
            payload = request(owner, fiber); payload['op'] = 'fibers.path_update'
            payload['params'].pop('max_displacement'); payload['params']['path'] = preview['entities'][0]['path']
            applied = execute(payload, owner, bpy.context.scene, folder)
            self.assertEqual(applied['status'], 'success', applied)
            revision = fiber.free_path_revision
            replay = execute(payload, owner, bpy.context.scene, folder)
            self.assertTrue(replay.get('replayed'), replay)
            self.assertEqual(fiber.free_path_revision, revision)
            self.assertTrue(list(Path(folder).rglob('*.json')))

    def test_public_preview_is_readonly_and_preserves_tags(self):
        owner, _, fiber = setup_free(); before = fiber.free_path_json; revision = fiber.free_path_revision
        payload = request(owner, fiber)
        with patch.object(FileStore, 'put', side_effect=AssertionError('Preview journal write')):
            result = call(owner, payload)
        self.assertEqual(result['status'], 'success', result); self.assertFalse(result['published'])
        entity = result['entities'][0]; self.assertGreater(entity['tightening']['length_reduction'], 0)
        self.assertLessEqual(entity['tightening']['max_displacement'], .010000001)
        self.assertEqual(entity['path']['structural'], decode(before)['structural'])
        self.assertEqual((before, revision, 'FREE'), (fiber.free_path_json, fiber.free_path_revision, fiber.behavior_mode))
        self.assertEqual(result['scene_revision'], payload['params']['expected_scene_revision'])

    def test_preview_can_commit_and_attachments_still_follow(self):
        owner, surface, fiber = setup_free(); before = runtime.bindings(fiber)
        result = call(owner, request(owner, fiber)); self.assertEqual(result['status'], 'success', result)
        applied, replay = apply_preview(owner, fiber, result['entities'][0]['path'])
        self.assertEqual(applied['status'], 'success', applied); self.assertTrue(applied['published'])
        self.assertTrue(replay.get('replayed'), replay)
        self.assertEqual(runtime.bindings(fiber), before); self.assertEqual(fiber.behavior_mode, 'FREE')
        points = runtime.current(owner, bpy.context.scene, fiber)[1]
        surface.location.z += .2; bpy.context.view_layer.update()
        moved = runtime.current(owner, bpy.context.scene, fiber)[1]
        self.assertLess(max(abs((b-a).z-.2) for a, b in zip(points, moved)), 1e-5)

    def test_stale_inputs_and_bad_options_fail_without_mutation(self):
        owner, _, fiber = setup_free(); before = fiber.free_path_json
        for options in (dict(expected_scene_revision='old'), dict(expected_path_revision=0),
                        dict(max_displacement=-1), dict(accepted_steps=0)):
            result = call(owner, request(owner, fiber, **options))
            self.assertEqual(result['status'], 'unresolved', result); self.assertEqual(before, fiber.free_path_json)

    def test_controlled_and_open_path_editor_are_rejected(self):
        owner, _, fiber, _ = fixture()
        self.assertEqual(call(owner, request(owner, fiber))['diagnostics'][0]['code'], 'FIBER_NOT_FREE')
        service.configure_mode(owner, bpy.context.scene, fiber, 'FREE'); owner['af_free_edit_' + fiber.id] = True
        self.assertEqual(call(owner, request(owner, fiber))['diagnostics'][0]['code'], 'EDIT_IN_PROGRESS')

    def test_solver_failure_cannot_publish_a_partial_edit(self):
        owner, _, fiber = setup_free(); before = fiber.free_path_json
        with patch('anthroforge.adapters.authoring.fiber_tightening.tighten', side_effect=RuntimeError('native unavailable')):
            result = call(owner, request(owner, fiber))
        self.assertEqual(result['status'], 'unresolved'); self.assertFalse(result['published'])
        self.assertEqual(before, fiber.free_path_json)
