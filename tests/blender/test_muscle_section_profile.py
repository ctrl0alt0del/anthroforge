"""Native manual controls, no-solve capture, persistence and transaction rollback."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import bpy
import numpy as np
from _helpers import BlenderTestCase, root
from _profile_fixture import surface_only as _surface_only
from anthroforge.app.use_cases.fiber_surface_create import create_native_muscle
from anthroforge.app.use_cases import muscle_profile as commands
from anthroforge.core.authoring.profile_config import wire
from anthroforge.core.vcp.muscle_section_profile import reset_profile
from anthroforge.core.visualization.muscle_sync import register_muscle_sync
from anthroforge.core.visualization.muscle_profile_publish import affected_objects
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates


def fixture(profile=True):
    owner, surface = _surface_only()
    config = wire(reset_profile(.2)) if profile else None
    muscle = create_native_muscle(owner, bpy.context.scene, surface.id, "Profile", config)
    owner.af_vcp_system.active_vcp_type, owner.af_vcp_system.active_vcp_id = 'MUSCLE', muscle.id
    return owner, surface, muscle


def mesh(owner, muscle, role='INFL'):
    obj = next(obj for obj in affected_objects(owner, bpy.context.scene, muscle.id) if obj.get('af_muscle_surface') == role)
    return np.asarray([tuple(vertex.co) for vertex in obj.data.vertices])


class MuscleSectionProfileTests(BlenderTestCase):
    def test_unsupported_domain_is_invalid_even_when_source_is_stale(self):
        owner, surface, muscle = fixture()
        with suppress_vcp_prop_updates():
            surface.close_across_fibers = True
        proxy = next(obj for obj in bpy.context.scene.objects if obj.get('af_fiber_proxy'))
        proxy['af_fiber_output_state'] = 'STALE'
        register_muscle_sync().sync_root_to_scene(owner, bpy.context.scene, {muscle.id})
        self.assertIn('PROFILE_DOMAIN_UNSUPPORTED', muscle['_af_rt_section_profile_error'])
        self.assertEqual(len(mesh(owner, muscle)), 0)
        self.assertTrue(all(obj.get('af_muscle_output_state') == 'INVALID' for obj in affected_objects(owner, bpy.context.scene, muscle.id)))

    def test_manual_activation_side_scale_and_legacy_preservation(self):
        owner, surface, muscle = fixture(False)
        amount = muscle.inflation_max_value
        self.assertEqual(bpy.ops.af.muscle_profile_mode(muscle_id=muscle.id, mode='section_profile'), {'FINISHED'})
        before, winding = mesh(owner, muscle), surface.flip_normals
        self.assertEqual(bpy.ops.af.muscle_profile_side(muscle_id=muscle.id), {'FINISHED'})
        np.testing.assert_allclose(mesh(owner, muscle)+before, mesh(owner, muscle, 'BASE')*2, atol=2e-7)
        self.assertEqual(surface.flip_normals, winding)
        self.assertEqual(bpy.ops.af.muscle_profile_scale(muscle_id=muscle.id, factor=2), {'FINISHED'})
        self.assertEqual(bpy.ops.af.muscle_profile_mode(muscle_id=muscle.id, mode='distributed'), {'FINISHED'})
        self.assertEqual(muscle.inflation_max_value, amount)
        self.assertTrue(muscle.flip_normals)
        self.assertFalse(any(obj.get('af_muscle_inflation_ctrl') for obj in affected_objects(owner, bpy.context.scene, muscle.id)))

    def test_profile_edit_and_stale_capture_never_fall_back_to_solver(self):
        owner, _, muscle = fixture()
        sync = register_muscle_sync()
        with patch.object(sync, '_collect_points_with_fallback', side_effect=AssertionError('solver fallback')):
            muscle.section_roundness = 2
            sync.sync_root_to_scene(owner, bpy.context.scene, {muscle.id})
            self.assertGreater(len(mesh(owner, muscle)), 0)
            proxy = next(obj for obj in bpy.context.scene.objects if obj.get('af_fiber_proxy') and not obj.get('af_fiber_mirror_proxy'))
            proxy['af_fiber_output_state'] = 'STALE'
            sync.sync_root_to_scene(owner, bpy.context.scene, {muscle.id})
        self.assertIn('PROFILE_BASE_NOT_CURRENT', muscle['_af_rt_section_profile_error'])
        self.assertTrue(all(obj.get('af_muscle_output_state') == 'STALE' for obj in affected_objects(owner, bpy.context.scene, muscle.id)))

    def test_direct_uninitialized_and_future_modes_remain_invalid_until_reset(self):
        owner, _, muscle = fixture(False)
        muscle.inflation_mode = 'SECTION_PROFILE'
        register_muscle_sync().sync_root_to_scene(owner, bpy.context.scene, {muscle.id})
        self.assertEqual(muscle.section_profile_version, 0)
        self.assertEqual(len(mesh(owner, muscle)), 0)
        muscle.section_profile_version = 77
        self.assertEqual(muscle.section_profile_version, 77)
        self.assertEqual(bpy.ops.af.muscle_profile_reset(muscle_id=muscle.id, depth=.1), {'FINISHED'})
        self.assertEqual(muscle.section_profile_version, 1)
        self.assertGreater(len(mesh(owner, muscle)), 0)

    def test_overflow_and_publication_failure_restore_target(self):
        owner, _, muscle = fixture()
        before, values = mesh(owner, muscle), tuple(muscle.section_depths)
        with self.assertRaises(ValueError):
            commands.action_configuration(muscle, 'scale', 1000)
        with patch.object(commands, 'publish', side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):
                commands.configure(owner, bpy.context.scene, muscle.id, wire(reset_profile(.4)))
        self.assertEqual(tuple(muscle.section_depths), values)
        np.testing.assert_array_equal(mesh(owner, muscle), before)

    def test_disabled_invalid_profile_is_not_hidden(self):
        owner, _, muscle = fixture()
        muscle.inflation_enabled = False
        np.testing.assert_array_equal(mesh(owner, muscle), mesh(owner, muscle, 'BASE'))
        muscle.section_profile_version = 3
        register_muscle_sync().sync_root_to_scene(owner, bpy.context.scene, {muscle.id})
        self.assertEqual(len(mesh(owner, muscle)), 0)
        self.assertIn('VERSION_UNSUPPORTED', muscle['_af_rt_section_profile_error'])

    def test_save_reopen_preserves_parameters_and_geometry(self):
        owner, _, muscle = fixture()
        muscle.section_peaks = (.2, .4, .6, .8)
        before, depths, identity = mesh(owner, muscle), tuple(muscle.section_depths), muscle.id
        with TemporaryDirectory() as directory:
            path = str(Path(directory)/'profile.blend')
            bpy.ops.wm.save_as_mainfile(filepath=path)
            bpy.ops.wm.open_mainfile(filepath=path)
            owner, muscle = root(), next(item for item in root().af_vcp_system.muscles if item.id == identity)
            register_muscle_sync().sync_root_to_scene(owner, bpy.context.scene, {identity})
            self.assertEqual(tuple(muscle.section_depths), depths)
            np.testing.assert_allclose(mesh(owner, muscle), before, atol=5e-7, rtol=0)

    def test_import_vectors_independent_identity_and_explicit_scaling(self):
        from anthroforge.core.importing.rna import scalar_dict, apply_scalar_dict
        owner, _, muscle = fixture()
        muscle['af_authoring_muscle_creation'] = 'source-token'
        with suppress_vcp_prop_updates():
            clone = owner.af_vcp_system.muscles.add()
            apply_scalar_dict(clone, scalar_dict(muscle), geometry_scale=2)
            clone.id = 'MUSCLE_COPY'
            clone.section_depths[0] = .3
        self.assertNotEqual(clone.section_depths[0], muscle.section_depths[0])
        self.assertAlmostEqual(clone.section_depths[1], muscle.section_depths[1]*2)
        self.assertNotIn('af_authoring_muscle_creation', clone)
        self.assertEqual(clone.fiber_surface_id, muscle.fiber_surface_id)
