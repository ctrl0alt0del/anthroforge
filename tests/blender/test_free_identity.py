"""One request namespace across Free, native, profile and anatomy dispatch."""
import tempfile
import bpy
from _helpers import BlenderTestCase, reset_scene
from _branch_fixture import create_fixture
from test_free_fibers import fixture
from test_free_authoring import creation, request
from anthroforge.app.authoring.api import execute
from anthroforge.adapters.authoring.inventory import capture
from anthroforge.adapters.authoring.capture import native_records
from anthroforge.app.use_cases import free_fiber as service
from anthroforge.core.visualization import free_fiber_runtime as runtime


def other_requests(root, fiber):
    revision = capture(root, bpy.context.scene)['revision']
    return [request(root, op, expected_scene_revision=revision, **params) for op, params in (
        ('points.edit', dict(point_id=fiber.a_point_id, position=[.15, .15, 0])),
        ('fibers.recompute', dict(fiber_ids=[fiber.id])),
        ('muscles.branch_configure', dict(muscle_id='missing', connection_id='missing', connector=dict(width=.3))),
        ('muscles.profile_configure', dict(muscle_id='missing', expected_base_revision='missing', configuration=dict(mode='distributed'))),
        ('anatomy.initialize', {}))]


def free_update(root, fiber, identity):
    payload, points = runtime.current(root, bpy.context.scene, fiber)
    value = dict(representation='POLY', space='WORLD', structural=payload['structural'],
                 samples=[dict(sample_id=p['sample_id'], co=list(co)) for p, co in zip(payload['samples'], points)])
    result = request(root, 'fibers.path_update', fiber_id=fiber.id, path=value, expected_path_revision=fiber.free_path_revision,
                     expected_scene_revision=capture(root, bpy.context.scene)['revision'])
    result['request_id'] = identity
    return result


class FreeIdentityTests(BlenderTestCase):
    def test_free_identity_blocks_all_other_dispatch_families_before_mutation(self):
        root, _bone, fiber, points = fixture(); initial = creation(root, fiber, points)
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(execute(initial, root, bpy.context.scene, folder)['status'], 'success')
            before = native_records(root)
            for value in other_requests(root, root.af_vcp_system.fibers[-1]):
                value['request_id'] = initial['request_id']; value['dsl'] = 'anthroforge.authoring.protocol'
                with self.subTest(operation=value['op']):
                    result = execute(value, root, bpy.context.scene, folder)
                    self.assertIn('REQUEST_ID_REUSED', str(result)); self.assertEqual(native_records(root), before)
            self.assertTrue(execute(initial, root, bpy.context.scene, folder)['replayed'])

    def test_successful_point_recompute_and_anatomy_identities_block_free_update(self):
        for index in (0, 1, 4):
            reset_scene(); root, _bone, fiber, _points = fixture()
            service.configure_mode(root, bpy.context.scene, fiber, 'FREE')
            with tempfile.TemporaryDirectory() as folder:
                initial = other_requests(root, fiber)[index]; result = execute(initial, root, bpy.context.scene, folder)
                self.assertEqual(result['status'], 'success', result); before = native_records(root)
                value = free_update(root, fiber, initial['request_id'])
                self.assertIn('REQUEST_ID_REUSED', str(execute(value, root, bpy.context.scene, folder)))
                self.assertEqual(native_records(root), before)

    def test_successful_branch_and_profile_identities_block_free_update(self):
        from test_authoring_legacy_profile import payload, configuration
        for kind in ('branch', 'profile'):
            reset_scene(); root, muscle, connection, fibers = create_fixture(); fiber = fibers[0]
            service.configure_mode(root, bpy.context.scene, fiber, 'FREE')
            with tempfile.TemporaryDirectory() as folder:
                initial = (request(root, 'muscles.branch_configure', muscle_id=muscle.id, connection_id=connection.id,
                           expected_scene_revision=capture(root, bpy.context.scene)['revision'], connector=dict(width=.3)) if kind == 'branch'
                           else payload(root, folder, muscle, 'profile_configure', 'profile-write', configuration()))
                result = execute(initial, root, bpy.context.scene, folder); self.assertEqual(result['status'], 'success', result)
                before = native_records(root); value = free_update(root, fiber, initial['request_id'])
                self.assertIn('REQUEST_ID_REUSED', str(execute(value, root, bpy.context.scene, folder)))
                self.assertEqual(native_records(root), before)
