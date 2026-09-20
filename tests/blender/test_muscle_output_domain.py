"""Actual material crop publication, branch provenance, guards and persistence."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import bpy
import numpy as np
from mathutils import Matrix
from _helpers import BlenderTestCase, root
from _branch_fixture import create_fixture
from _profile_fixture import surface_only
from test_authoring_native_profiles import call, inspect, request, create, fail_response
from anthroforge.app.use_cases import muscle_profile as profiles
from anthroforge.app.use_cases import muscle_domain as domains
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.adapters.authoring.records import record
from anthroforge.adapters.authoring.capture import native_records
from anthroforge.core.authoring.storage import FileStore
from anthroforge.core.authoring.codec import encode
from anthroforge.core.vcp.muscle_output_domain import capture, configuration
from anthroforge.core.vcp.muscle_numeric import execute_muscle_batch
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.visualization.muscle_sync import register_muscle_sync
from anthroforge.core.visualization.muscle_profile_publish import affected_objects


def plane(axis=0, coordinate=1.):
    origin, normal = [0., 0., 0.], [0., 0., 0.]
    origin[axis], normal[axis] = coordinate, 1.
    return dict(mode='plane', space='root_local', origin=origin, normal=normal, keep_positive=True)


def payload(owner, folder, muscle, value, identity='crop'):
    _, guards = inspect(owner, folder, dict(muscle_id=muscle.id), identity+'-inspect')
    return request(owner, 'domain_configure', identity, muscle_id=muscle.id, configuration=value, **guards)


def published(owner, muscle):
    return tuple(o for o in affected_objects(owner, bpy.context.scene, muscle.id) if o.type == 'MESH')


def geometry(owner, muscle):
    return {o.name: (tuple(tuple(v.co) for v in o.data.vertices), tuple(tuple(p.vertices) for p in o.data.polygons))
            for o in published(owner, muscle)}


def controls(owner):
    return tuple(record(f) for f in owner.af_vcp_system.fibers), tuple(record(s) for s in owner.af_vcp_system.fiber_surfaces)


def numeric(owner, muscle):
    target, _ = profiles.inspect(owner, bpy.context.scene, muscle.id)
    config = profiles.mode_configuration(muscle, 'section_profile' if muscle.inflation_mode == 'SECTION_PROFILE' else 'distributed')
    return profiles.preview(target, config)[2].results[0]


def assert_published(test, owner, muscle, result):
    for obj in published(owner, muscle):
        expected = result.base_vertices if obj['af_muscle_surface'] == 'BASE' else result.inflated_vertices
        np.testing.assert_array_equal(np.asarray([v.co[:] for v in obj.data.vertices]), expected.astype(np.float32))
        np.testing.assert_array_equal([p.vertices[:] for p in obj.data.polygons], result.faces)


class OutputDomainTests(BlenderTestCase):
    def setUp(self):
        super().setUp()
        folder = TemporaryDirectory(); self.addCleanup(folder.cleanup); self.folder = folder.name

    def ordinary(self):
        owner, surface = surface_only()
        create(owner, surface, self.folder)
        return owner, owner.af_vcp_system.muscles[0]

    def test_ordinary_crop_updates_actual_shells_preserving_controls_and_profile(self):
        owner, muscle = self.ordinary()
        before, profile = controls(owner), tuple(muscle.section_depths)
        command = payload(owner, self.folder, muscle, plane())
        result = call(owner, self.folder, command)
        self.assertTrue(result.get('published'), result)
        actual = numeric(owner, muscle)
        self.assertGreaterEqual(actual.base_vertices[:, 0].min(), 1.-1e-10)
        self.assertEqual(actual.faces.shape[1], 3); self.assertEqual(set(actual.face_parts), {0})
        self.assertEqual(before, controls(owner)); self.assertEqual(profile, tuple(muscle.section_depths))
        assert_published(self, owner, muscle, actual)
        self.assertTrue(call(owner, self.folder, command).get('replayed'))

    def test_profile_guard_and_preview_include_current_material_domain(self):
        owner, muscle = self.ordinary()
        _, guards = inspect(owner, self.folder, dict(muscle_id=muscle.id), 'before')
        config = dict(mode='distributed')
        stale = request(owner, 'profile_configure', 'stale', muscle_id=muscle.id, configuration=config, **guards)
        domains.configure(owner, bpy.context.scene, muscle.id, plane())
        stale['params']['expected_scene_revision'] = StaticScene(owner, bpy.context.scene).capture_authoring()['revision']
        self.assertEqual(call(owner, self.folder, stale)['diagnostics'][0]['code'], 'STALE_BASE_REVISION')
        target, state = profiles.inspect(owner, bpy.context.scene, muscle.id)
        result = profiles.preview(target, config)[2].results[0]
        self.assertGreaterEqual(result.base_vertices[:, 0].min(), 1.-1e-10)
        self.assertEqual(state['output_domain'], plane())
        self.assertNotEqual(guards['expected_base_revision'], state['base_revision'])

    def test_branch_crop_keeps_shared_graph_and_face_part_identity(self):
        owner, muscle, _, _ = create_fixture()
        before = controls(owner)
        result = call(owner, self.folder, payload(owner, self.folder, muscle, plane(2, -.25)))
        self.assertTrue(result.get('published'), result)
        actual = numeric(owner, muscle)
        self.assertEqual(set(actual.face_parts), {0, 1})
        self.assertEqual(len(actual.source_faces), len(actual.faces))
        self.assertGreaterEqual(actual.base_vertices[:, 2].min(), -.25-1e-10)
        self.assertEqual(before, controls(owner)); assert_published(self, owner, muscle, actual)

    def test_full_domain_restores_exact_original_native_mesh(self):
        owner, muscle = self.ordinary(); original = numeric(owner, muscle)
        domains.configure(owner, bpy.context.scene, muscle.id, plane())
        domains.configure(owner, bpy.context.scene, muscle.id, dict(mode='full'))
        restored = numeric(owner, muscle)
        np.testing.assert_array_equal(original.base_vertices, restored.base_vertices)
        np.testing.assert_array_equal(original.inflated_vertices, restored.inflated_vertices)
        np.testing.assert_array_equal(original.faces, restored.faces)

    def test_journal_failure_restores_domain_and_both_meshes(self):
        owner, muscle = self.ordinary()
        command = payload(owner, self.folder, muscle, plane())
        before = native_records(owner), geometry(owner, muscle)
        with patch.object(FileStore, 'put', fail_response(FileStore.put)):
            result = call(owner, self.folder, command)
        self.assertEqual(result['status'], 'failed', result)
        self.assertEqual(before, (native_records(owner), geometry(owner, muscle)))

    def test_empty_and_zero_normal_domains_fail_without_mutation(self):
        owner, muscle = self.ordinary(); before = native_records(owner), geometry(owner, muscle)
        for value in (plane(0, 100.), dict(plane(), normal=[0., 0., 0.]), dict(plane(), normal=[1e308]*3)):
            with self.assertRaises(ValueError):
                domains.configure(owner, bpy.context.scene, muscle.id, value)
            self.assertEqual(before, (native_records(owner), geometry(owner, muscle)))

    def test_root_local_plane_transforms_with_nonuniform_moved_root(self):
        owner, muscle = self.ordinary()
        domains.configure(owner, bpy.context.scene, muscle.id, plane())
        before = numeric(owner, muscle); target, _ = profiles.inspect(owner, bpy.context.scene, muscle.id)
        req = profiles._preview_request(target, muscle, False)
        matrix = Matrix.Translation((3., -2., .5)) @ Matrix.Rotation(.8, 4, 'Y') @ Matrix.Diagonal((2., 1., .5, 1.))
        owner.matrix_world = matrix; bpy.context.view_layer.update()
        points = np.asarray(req.points) @ np.asarray(matrix)[:3, :3].T + np.asarray(matrix)[:3, 3]
        moved = execute_muscle_batch((replace(req, points=points, output_domain=capture(muscle)),)).results[0]
        expected = before.base_vertices @ np.asarray(matrix)[:3, :3].T + np.asarray(matrix)[:3, 3]
        np.testing.assert_allclose(moved.base_vertices, expected, atol=2e-7)

    def test_derived_mirror_uses_the_same_clipped_material_mesh(self):
        owner, muscle = self.ordinary()
        for fiber in owner.af_vcp_system.fibers:
            fiber['af_authoring_symmetry'] = 'native_mirror'; fiber['af_authoring_mirror_axis'] = 'X'
            fiber['af_authoring_mirror_origin'] = [0., 0., 0.]
        domains.configure(owner, bpy.context.scene, muscle.id, plane())
        objects = published(owner, muscle)
        mirrors = [o for o in objects if o.get('af_muscle_mirror_proxy')]
        self.assertEqual(len(mirrors), 2)
        for obj in mirrors:
            self.assertLessEqual(max((obj.matrix_world @ v.co).x for v in obj.data.vertices), -1.+1e-7)
            self.assertTrue(all(len(p.vertices) == 3 for p in obj.data.polygons))

    def test_debug_save_normal_reopen_retains_crop_and_visible_curves(self):
        owner, muscle = self.ordinary()
        command = payload(owner, self.folder, muscle, plane()); call(owner, self.folder, command)
        before, identity = geometry(owner, muscle), muscle.id
        path = Path(self.folder)/'cropped.blend'; StaticScene(owner, bpy.context.scene).save_debug_copy(path)
        bpy.ops.wm.open_mainfile(filepath=str(path)); owner = root()
        muscle = next(m for m in owner.af_vcp_system.muscles if m.id == identity)
        self.assertEqual(configuration(muscle), plane()); self.assertEqual(before, geometry(owner, muscle))
        self.assertTrue(call(owner, self.folder, command).get('replayed'))
        curves = [o for o in bpy.context.scene.objects if o.get('af_fiber_proxy')]
        self.assertTrue(curves and all(not o.hide_get() and not o.hide_viewport and o.display_type == 'TEXTURED' for o in curves))

    def test_historical_v2_profile_receipt_replays_only_before_crop(self):
        from anthroforge.app.authoring.native_profiles import _postcondition
        from test_authoring_native_profiles import configure
        owner, muscle = self.ordinary()
        _, command = configure(owner, self.folder, muscle.id)
        store, key = FileStore(self.folder), [owner.name, command['request_id']]
        receipt = store.get('v04_profile_receipts', key)
        _, state = profiles.inspect(owner, bpy.context.scene, muscle.id)
        receipt.update(version=2, postcondition=_postcondition(state, receipt['kind'], 2))
        store.put('v04_profile_receipts', key, receipt); muscle['af_authoring_profile_receipt'] = encode(receipt)
        self.assertTrue(call(owner, self.folder, command).get('replayed'))
        domains.configure(owner, bpy.context.scene, muscle.id, plane())
        self.assertEqual(call(owner, self.folder, command)['diagnostics'][0]['code'], 'STALE_PROFILE_RECEIPT')

    def test_import_settings_scale_local_origin_and_drop_foreign_receipt(self):
        from anthroforge.core.importing.muscle_profile import prepared_properties
        owner, muscle = self.ordinary()
        domains.configure(owner, bpy.context.scene, muscle.id, plane())
        values = record(muscle)['values']; values['af_authoring_domain_receipt'] = 'old identity'
        copied = prepared_properties(values, geometry_scale=2.)
        self.assertEqual(copied['output_domain_origin'], [2., 0., 0.])
        self.assertEqual(copied['output_domain_normal'], [1., 0., 0.])
        self.assertNotIn('af_authoring_domain_receipt', copied)

    def test_arbitrary_plane_publication_matches_persisted_float_coordinates(self):
        owner, muscle = self.ordinary()
        value = dict(plane(), origin=[.937156873, .063224146, .046322914], normal=[.91537264, .437566622, .322111488])
        domains.configure(owner, bpy.context.scene, muscle.id, value)
        assert_published(self, owner, muscle, numeric(owner, muscle))
