"""Native 0.4 authoring loop, instance identity and save/reload contracts."""
import json
import tempfile
from pathlib import Path
import bpy
from unittest.mock import patch
from _helpers import BlenderTestCase, root
from test_authoring_dsl import fixture
from anthroforge.app.authoring.api import execute
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.core.authoring.migration import migrate
from anthroforge.core.vcp.attachment_backend import resolve_attachment_world
from anthroforge.core.authoring.schema import validate


def request(r, op, **params):
    revision = StaticScene(r, bpy.context.scene).capture_authoring()['revision']
    mutation = op in ('draft', 'patch', 'compile', 'resume', 'publish', 'checkpoint', 'adopt_binding', 'propose_binding', 'revise_candidate', 'reconcile')
    if mutation or op == 'initialize':
        params['expected_scene_revision'] = revision
    return dict(version='0.4.0', message_type='request', request_id=op+'_'+str(params.get('expected_draft_revision', 0)), op='anatomy.'+op, params=dict(scene_id=r.name, **params))


def setup(r, directory):
    old = fixture(r)
    result = execute(request(r, 'initialize'), r, bpy.context.scene, directory)
    assert result['status'] == 'success', result
    inventory = StaticScene(r, bpy.context.scene).capture_authoring()
    bindings = {v['scp_id']: v['instance_id'] for v in inventory['instances']}
    return migrate(old, bindings)


def call(r, directory, op, authored, revision=1, **params):
    result = execute(request(r, op, document_id=authored['document_id'], expected_draft_revision=revision, **params), r, bpy.context.scene, directory)
    validate(result, 'protocol')
    return result


class AuthoringV04Tests(BlenderTestCase):
    def test_interrupted_recovery_resumes_without_overwrite(self):
        from anthroforge.app.authoring import persistence
        r = root()
        with tempfile.TemporaryDirectory() as folder:
            value = setup(r, folder)
            call(r, folder, 'draft', value, 0, document=value)
            checkpoint = call(r, folder, 'checkpoint', value)
            path = Path(folder)/'resumed.blend'
            payload = request(r, 'recover', generation_id=checkpoint['generation']['id'], output_path=str(path))
            with patch.object(persistence.os, 'rename', interrupt_recovery(persistence.os.rename)):
                self.assertEqual(execute(payload, r, bpy.context.scene, folder)['status'], 'failed')
            self.assertFalse(path.exists())
            self.assertTrue(path.with_suffix('.authoring').exists())
            self.assertEqual(execute(payload, r, bpy.context.scene, folder)['status'], 'success')
            self.assertTrue(path.exists())

    def test_interrupted_checkpoint_keeps_previous_generation(self):
        from anthroforge.core.authoring.storage import FileStore
        from anthroforge.app.authoring.persistence import verify
        r = root()
        with tempfile.TemporaryDirectory() as folder:
            value = setup(r, folder)
            call(r, folder, 'draft', value, 0, document=value)
            first = call(r, folder, 'checkpoint', value)
            payload = request(r, 'checkpoint', document_id=value['document_id'], expected_draft_revision=1)
            payload['request_id'] = 'interrupted_checkpoint'
            with patch.object(FileStore, 'put', fail_complete_generation(FileStore.put)):
                self.assertEqual(execute(payload, r, bpy.context.scene, folder)['status'], 'failed')
            verify(first['generation'])
            verify_incomplete(self, r, folder, payload)

    def test_cancelled_compilation_resumes_without_publication(self):
        r = root()
        with tempfile.TemporaryDirectory() as folder:
            value = setup(r, folder)
            call(r, folder, 'draft', value, 0, document=value)
            payload = request(r, 'compile', document_id=value['document_id'], expected_draft_revision=1)
            cancellation = request(r, 'cancel', document_id=value['document_id'], compilation_request_id=payload['request_id'])
            execute(cancellation, r, bpy.context.scene, folder)
            cancelled = execute(payload, r, bpy.context.scene, folder)
            self.assertEqual(cancelled['diagnostics'][0]['code'], 'CANCELLED', cancelled)
            self.assertEqual(len(r.af_vcp_system.muscles), 0)
            resumed = call(r, folder, 'resume', value)
            self.assertEqual(resumed['status'], 'success', resumed)

    def test_fiber_budget_is_independent_of_surface_budget(self):
        r = root()
        with tempfile.TemporaryDirectory() as folder:
            value = setup(r, folder)
            value['limits'] = dict(max_fibers=2, max_surface_vertices=100000)
            call(r, folder, 'draft', value, 0, document=value)
            result = call(r, folder, 'compile', value)
            self.assertEqual(result['diagnostics'][0]['code'], 'FIBER_BUDGET_EXHAUSTED', result)
            self.assertEqual(len(r.af_vcp_system.muscles), 0)

    def test_loop_strategy_uses_native_loop_anchors(self):
        from _authoring_loop_fixture import fixture as loop_fixture
        r = root()
        with tempfile.TemporaryDirectory() as folder:
            old = loop_fixture(r)
            execute(request(r, 'initialize'), r, bpy.context.scene, folder)
            data = StaticScene(r, bpy.context.scene).capture_authoring()
            value = migrate(old, {v['scp_id']: v['instance_id'] for v in data['instances'] if v['has_surface']})
            self.assertEqual(call(r, folder, 'draft', value, 0, document=value)['status'], 'success')
            self.assertEqual(call(r, folder, 'compile', value)['status'], 'success')
            published = call(r, folder, 'publish', value)
            self.assertTrue(published['published'], published)
            self.assertTrue(all(f.topology_mode == 'LOOP' and len(f.loop_anchors) == 4 for f in r.af_vcp_system.fibers))

    def test_interrupted_evaluation_retains_single_draft_mutation(self):
        from anthroforge.app.authoring import queries
        r = root()
        with tempfile.TemporaryDirectory() as folder:
            value = setup(r, folder)
            payload = request(r, 'draft', document_id=value['document_id'], expected_draft_revision=0, document=value)
            with patch.object(queries, 'evaluation', side_effect=RuntimeError('Injected interruption after commit')):
                self.assertEqual(execute(payload, r, bpy.context.scene, folder)['status'], 'failed')
            resumed = execute(payload, r, bpy.context.scene, folder)
            self.assertEqual(resumed['status'], 'success', resumed)
            self.assertEqual(resumed['draft_revision'], 1)

    def test_published_receipt_recovers_missing_response_cache(self):
        from anthroforge.core.authoring.storage import FileStore
        r = root()
        with tempfile.TemporaryDirectory() as folder:
            value = setup(r, folder)
            call(r, folder, 'draft', value, 0, document=value)
            call(r, folder, 'compile', value)
            payload = request(r, 'publish', document_id=value['document_id'], expected_draft_revision=1)
            with patch.object(FileStore, 'put', fail_response_cache(FileStore.put)):
                self.assertEqual(execute(payload, r, bpy.context.scene, folder)['status'], 'failed')
            recovered = execute(payload, r, bpy.context.scene, folder)
            self.assertTrue(recovered['published'], recovered)
            self.assertEqual(len(r.af_vcp_system.muscles), 1)

    def test_manual_inflation_adoption_survives_regeneration(self):
        r = root()
        with tempfile.TemporaryDirectory() as folder:
            value = setup(r, folder)
            call(r, folder, 'draft', value, 0, document=value)
            self.assertEqual(call(r, folder, 'compile', value)['status'], 'success')
            self.assertTrue(call(r, folder, 'publish', value)['published'])
            muscle = r.af_vcp_system.muscles[0]
            expected = muscle.inflation_max_value*1.1
            muscle.inflation_max_value = expected
            adopted = call(r, folder, 'reconcile', value, mode='adopt')
            self.assertEqual(adopted['status'], 'success', adopted)
            self.assertEqual(call(r, folder, 'compile', value, 2)['status'], 'success')
            self.assertTrue(call(r, folder, 'publish', value, 2)['published'])
            self.assertAlmostEqual(r.af_vcp_system.muscles[0].inflation_max_value, expected, places=6)

    def test_scoped_mirror_attachment_resolves_actual_instance(self):
        from anthroforge.core.vcp.attachment_backend import capture_attachment_from_world
        from mathutils import Vector
        r = root()
        with tempfile.TemporaryDirectory() as folder:
            setup(r, folder)
            source = next(o for o in bpy.context.scene.objects if o.get('af_scp_geometry'))
            mirror = make_mirror(source)
            data = StaticScene(r, bpy.context.scene).initialize()
            row = next(v for v in data['instances'] if v['label'] == mirror.name)
            point = mirror.matrix_world @ Vector((.5, 0, 0))
            parameter = capture_attachment_from_world(r, bpy.context.scene, row['instance_id'], point)
            actual = resolve_attachment_world(r, bpy.context.scene, row['instance_id'], parameter)
            self.assertLess((actual-point).length, 1e-5)

    def test_rename_preserves_instance_and_revision(self):
        r = root()
        with tempfile.TemporaryDirectory() as folder:
            setup(r, folder)
            before = StaticScene(r, bpy.context.scene).capture_authoring()
            source = next(o for o in bpy.context.scene.objects if o.get('af_scp_geometry'))
            source.name = 'Renamed surface'
            after = StaticScene(r, bpy.context.scene).capture_authoring()
            self.assertEqual(before['revision'], after['revision'])

    def test_root_rename_preserves_scoped_discovery(self):
        r = root()
        with tempfile.TemporaryDirectory() as folder:
            value = setup(r, folder)
            before = StaticScene(r, bpy.context.scene).capture_authoring()
            r.name = 'Renamed avatar'
            after = StaticScene(r, bpy.context.scene).capture_authoring()
            self.assertEqual(before['revision'], after['revision'])
            self.assertEqual(before['instances'], after['instances'])
            self.assertEqual(call(r, folder, 'draft', value, 0, document=value)['status'], 'success')
            self.assertEqual(call(r, folder, 'compile', value)['status'], 'success')
            self.assertTrue(call(r, folder, 'publish', value)['published'])

    def test_manual_attachment_adoption_survives_regeneration(self):
        r = root()
        with tempfile.TemporaryDirectory() as folder:
            value = setup(r, folder)
            call(r, folder, 'draft', value, 0, document=value)
            call(r, folder, 'compile', value)
            call(r, folder, 'publish', value)
            expected = move_attachment(r)
            adopted = call(r, folder, 'reconcile', value, mode='adopt')
            self.assertEqual(adopted['status'], 'success', adopted)
            self.assertTrue((compiled := call(r, folder, 'compile', value, 2))['status'] == 'success', compiled)
            result = call(r, folder, 'publish', value, 2)
            self.assertTrue(result.get('published'), result)
            fiber = r.af_vcp_system.fibers[0]
            self.assertLess((resolve_attachment_world(r, bpy.context.scene, fiber.a_parent_id, fiber.a_attach_param)-expected).length, 1e-5)

    def test_region_draft_roundtrip_and_replay(self):
        r = root()
        with tempfile.TemporaryDirectory() as folder:
            value = setup(r, folder)
            value['instances'] = {}
            payload = request(r, 'draft', document_id=value['document_id'], expected_draft_revision=0, document=value)
            result = execute(payload, r, bpy.context.scene, folder)
            self.assertEqual(result['status'], 'success', result)
            self.assertEqual(execute(payload, r, bpy.context.scene, folder)['draft_revision'], 1)
            inspected = execute(request(r, 'inspect', document_id=value['document_id']), r, bpy.context.scene, folder)
            self.assertEqual(len(inspected['assets']), 6, inspected)

    def test_native_compile_publish_checkpoint(self):
        r = root()
        with tempfile.TemporaryDirectory() as folder:
            value = setup(r, folder)
            self.assertEqual(call(r, folder, 'draft', value, 0, document=value)['status'], 'success')
            compiled = call(r, folder, 'compile', value)
            self.assertEqual(compiled['status'], 'success', compiled)
            published = call(r, folder, 'publish', value)
            self.assertTrue(published['published'], published)
            self.assertTrue(all(f.a_parent_id.startswith('AFI_') for f in r.af_vcp_system.fibers))
            self.assertTrue(all(f.node_attachments_json for f in r.af_vcp_system.fibers))
            checkpoint = call(r, folder, 'checkpoint', value)
            self.assertTrue(checkpoint['generation']['complete'], checkpoint)
            verify_reload(self, r, checkpoint['generation']['scene']['path'])

    def test_checkpoint_recovers_scene_and_draft_into_copy(self):
        r = root()
        with tempfile.TemporaryDirectory() as folder:
            value = setup(r, folder)
            call(r, folder, 'draft', value, 0, document=value)
            checkpoint = call(r, folder, 'checkpoint', value)
            path = str(Path(folder)/'recovered.blend')
            payload = request(r, 'recover', generation_id=checkpoint['generation']['id'], output_path=path)
            recovered = execute(payload, r, bpy.context.scene, folder)
            self.assertEqual(recovered['status'], 'success', recovered)
            bpy.ops.wm.open_mainfile(filepath=path)
            r = bpy.data.objects['AF_ROOT']
            result = execute(request(r, 'export', document_id=value['document_id']), r, bpy.context.scene)
            self.assertEqual(result['document'], value, result)

    def test_stale_candidate_is_rejected(self):
        r = root()
        with tempfile.TemporaryDirectory() as folder:
            value = setup(r, folder)
            target = '/skeleton_profiles/default/bindings/origin'
            add_requirement(value, target)
            call(r, folder, 'draft', value, 0, document=value)
            instance = value['skeleton_profiles']['default']['bindings']['origin']['instance_id']
            result = call(r, folder, 'propose_binding', value, requirement='origin', provider='existing_control.v1', parameters=dict(instance_id=instance))
            patch = [dict(op='replace', path='/entities/origin/label', value='Renamed meaning')]
            call(r, folder, 'patch', value, patch=patch)
            stale = call(r, folder, 'adopt_binding', value, 2, candidate_id=result['candidates'][0]['id'], mode='resolved')
            self.assertEqual(stale['diagnostics'][0]['code'], 'STALE_CANDIDATE', stale)

    def test_binding_proposal_adoption(self):
        r = root()
        with tempfile.TemporaryDirectory() as folder:
            value = setup(r, folder)
            target = '/skeleton_profiles/default/bindings/origin'
            instance = value['skeleton_profiles']['default']['bindings']['origin'].pop('instance_id')
            add_requirement(value, target)
            self.assertEqual(call(r, folder, 'draft', value, 0, document=value)['status'], 'unresolved')
            proposed = call(r, folder, 'propose_binding', value, requirement='origin', provider='existing_control.v1', parameters=dict(instance_id=instance))
            self.assertEqual(len(proposed['candidates']), 1, proposed)
            adopted = call(r, folder, 'adopt_binding', value, candidate_id=proposed['candidates'][0]['id'], mode='resolved')
            self.assertEqual(adopted['status'], 'success', adopted)
            self.assertEqual(adopted['draft_revision'], 2)

    def test_discovery_does_not_mutate_identity(self):
        r = root()
        fixture(r)
        data = StaticScene(r, bpy.context.scene).capture_authoring()
        self.assertFalse(data['root_id'])
        self.assertTrue(all(not x['instance_id'] for x in data['instances']))
        self.assertNotIn('af_authoring_id', r)

    def test_copied_identity_is_rejected(self):
        r = root()
        with tempfile.TemporaryDirectory() as folder:
            setup(r, folder)
            source = next(o for o in bpy.context.scene.objects if o.get('af_scp_geometry'))
            clone = source.copy()
            bpy.context.scene.collection.objects.link(clone)
            from anthroforge.core.authoring.errors import AuthoringError
            with self.assertRaises(AuthoringError):
                StaticScene(r, bpy.context.scene).capture_authoring()


def add_requirement(value, target):
    value['requirements'] = dict(origin=dict(target=target, need='binding', depends_on=[], consumers=['/instances/example_muscle'], constraints=[], required_state='resolved', evidence=next(iter(value['entities'].values()))['evidence']))


def move_attachment(r):
    from anthroforge.core.vcp.attachment_backend import capture_attachment_from_world
    from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
    fiber = r.af_vcp_system.fibers[0]
    point = resolve_attachment_world(r, bpy.context.scene, fiber.a_parent_id, fiber.a_attach_param)
    point.x *= .95
    with suppress_vcp_prop_updates():
        fiber.a_attach_param = capture_attachment_from_world(r, bpy.context.scene, fiber.a_parent_id, point)
    return point


def verify_reload(test, r, path):
    expected = [(f.a_parent_id, f.a_attach_param) for f in r.af_vcp_system.fibers]
    bpy.ops.wm.open_mainfile(filepath=path)
    r = bpy.data.objects['AF_ROOT']
    for owner, parameter in expected:
        test.assertIsNotNone(resolve_attachment_world(r, bpy.context.scene, owner, parameter))
    test.assertIn('af_authoring_generation', r)


def make_mirror(source):
    clone = source.copy()
    del clone['af_authoring_id']
    clone['af_scp_mirror'] = True
    clone['af_source_scp_id'] = source['af_scp_id']
    clone.location.x += 4
    bpy.context.scene.collection.objects.link(clone)
    bpy.context.view_layer.update()
    return clone


def fail_response_cache(original):
    def write(store, category, key, value):
        if category == 'v04_requests':
            raise OSError('Injected response-cache failure')
        return original(store, category, key, value)
    return write


def fail_complete_generation(original):
    def write(store, category, key, value):
        if category == 'v04_generations' and value.get('complete'):
            raise OSError('Injected checkpoint completion interruption')
        return original(store, category, key, value)
    return write


def interrupt_recovery(original):
    def rename(source, target, *args, **kwargs):
        if str(target).endswith('.blend'):
            raise OSError('Injected interruption before recovered scene publication')
        return original(source, target, *args, **kwargs)
    return rename


def verify_incomplete(test, root, folder, request):
    from anthroforge.core.authoring.codec import digest
    from anthroforge.core.authoring.errors import AuthoringError
    from anthroforge.core.authoring.storage import FileStore
    from anthroforge.app.authoring.persistence import verify
    identity = digest([root['af_authoring_id'], request])
    manifest = FileStore(folder).get('v04_generations', identity)
    with test.assertRaises(AuthoringError) as error:
        verify(manifest)
    test.assertEqual(error.exception.code, 'CHECKPOINT_INCOMPLETE')
