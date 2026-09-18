"""Profile graph identity, undo, receipt persistence and unsupported native charts."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import bpy
import numpy as np
from _helpers import BlenderTestCase, root
from test_muscle_section_profile import fixture, mesh
from test_authoring_native_profiles import create, configure, call, request
from _profile_fixture import surface_only as _surface_only
from anthroforge.app.use_cases import muscle_profile as commands
from anthroforge.adapters.authoring.scene import StaticScene
from anthroforge.core.importing.service import import_package_from_blend, import_vcp_from_blend
from anthroforge.core.vcp.muscle_profile_cache import CACHE, clear_profile_cache
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.visualization.muscle_sync import register_muscle_sync


def imported_pair(test, importer):
    owner, surface, muscle = fixture()
    muscle['af_authoring_profile_receipt'] = 'old'; muscle['af_authoring_muscle_creation'] = 'old'
    with TemporaryDirectory() as folder:
        path = str(Path(folder)/'source.blend')
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
        result = importer(path, bpy.context)
    test.assertEqual(result.muscle_count, 1)
    return owner, surface, muscle, owner.af_vcp_system.muscles[-1]


def assert_new_identity(test, owner, surface, original, clone):
    test.assertNotEqual(clone.id, original.id)
    test.assertNotEqual(clone.fiber_surface_id, surface.id)
    source = next(row for row in owner.af_vcp_system.fiber_surfaces if row.id == clone.fiber_surface_id)
    test.assertTrue({r.fiber_id for r in source.fiber_refs}.isdisjoint(r.fiber_id for r in surface.fiber_refs))
    test.assertEqual(tuple(clone.section_depths), tuple(original.section_depths))
    test.assertNotIn('af_authoring_profile_receipt', clone); test.assertNotIn('af_authoring_muscle_creation', clone)
    with suppress_vcp_prop_updates():
        clone.section_depths[0] *= 2
    test.assertNotEqual(clone.section_depths[0], original.section_depths[0])


def reacquire():
    owner = root()
    return owner, owner.af_vcp_system.muscles[0]


class MuscleProfileLifecycleTests(BlenderTestCase):
    def test_unknown_raw_mode_is_invalid_without_control_migration(self):
        owner, _, muscle = fixture()
        muscle['inflation_mode'] = 999
        sync = register_muscle_sync()
        with patch.object(sync, '_collect_points_with_fallback', side_effect=AssertionError('solver fallback')):
            sync.sync_root_to_scene(owner, bpy.context.scene, {muscle.id})
        self.assertIn('PROFILE_MODE_UNSUPPORTED', muscle['_af_rt_section_profile_error'])
        self.assertEqual(len(mesh(owner, muscle)), 0)
        self.assertFalse(muscle.inflation_ctrl_initialized)

    def test_scaled_import_overflow_rejects_before_any_rna_assignment(self):
        from anthroforge.core.importing.rna import scalar_dict, apply_scalar_dict
        _, _, muscle = fixture()
        before = scalar_dict(muscle)
        with self.assertRaises(ValueError):
            apply_scalar_dict(muscle, dict(before, name='Must not write'), geometry_scale=1000)
        self.assertEqual(scalar_dict(muscle), before)

    def test_package_import_remaps_graph_and_clears_request_identity(self):
        assert_new_identity(self, *imported_pair(self, import_package_from_blend))

    def test_vcp_import_remaps_graph_and_clears_request_identity(self):
        assert_new_identity(self, *imported_pair(self, import_vcp_from_blend))

    def test_operator_undo_redo_restores_profile_and_geometry(self):
        owner, _, muscle = fixture(); before = mesh(owner, muscle)
        bpy.ops.ed.undo_push(message='Before profile scale')
        bpy.ops.af.muscle_profile_scale(muscle_id=muscle.id, factor=2)
        bpy.ops.ed.undo_push(message='After profile scale')
        after = mesh(owner, muscle)
        bpy.ops.ed.undo(); owner, muscle = reacquire()
        self.assertEqual(len(CACHE), 0)
        np.testing.assert_array_equal(mesh(owner, muscle), before)
        self.assertAlmostEqual(muscle.section_depths[1], .2)
        bpy.ops.ed.redo(); owner, muscle = reacquire()
        np.testing.assert_array_equal(mesh(owner, muscle), after)
        self.assertAlmostEqual(muscle.section_depths[1], .4)

    def test_receipts_reopen_and_undo_revalidate_live_state(self):
        owner, surface = _surface_only()
        with TemporaryDirectory() as folder:
            _, creation = create(owner, surface, folder)
            bpy.ops.ed.undo_push(message='Native creation')
            _, configuration = configure(owner, folder, owner.af_vcp_system.muscles[0].id)
            bpy.ops.ed.undo_push(message='Native configuration')
            bpy.ops.ed.undo(); owner, _ = reacquire()
            self.assertEqual(call(owner, folder, configuration)['diagnostics'][0]['code'], 'STALE_PROFILE_RECEIPT')
            self.assertTrue(call(owner, folder, creation)['replayed'])
            bpy.ops.ed.redo(); owner, _ = reacquire()
            path = Path(folder)/'receipt.blend'; StaticScene(owner, bpy.context.scene).save_debug_copy(path)
            bpy.ops.wm.open_mainfile(filepath=str(path)); owner, _ = reacquire()
            self.assertTrue(call(owner, folder, configuration)['replayed'])
            self.assertTrue(call(owner, folder, creation)['replayed'])

    def test_stale_receipt_cannot_reapply_after_undoing_creation(self):
        owner, surface = _surface_only()
        with TemporaryDirectory() as folder:
            bpy.ops.ed.undo_push(message='Before native creation')
            _, payload = create(owner, surface, folder)
            bpy.ops.ed.undo_push(message='After native creation')
            bpy.ops.ed.undo(); owner = root()
            self.assertEqual(call(owner, folder, payload)['diagnostics'][0]['code'], 'STALE_CREATION_RECEIPT')
            self.assertEqual(len(owner.af_vcp_system.muscles), 0)

    def test_closed_chart_rejects_profile_but_preserves_manual_legacy_creation(self):
        owner, surface = _surface_only()
        surface.close_across_fibers = True
        captured, state = commands.inspect(owner, bpy.context.scene, surface_id=surface.id)
        self.assertFalse(captured.eligible); self.assertIn('PROFILE_DOMAIN_UNSUPPORTED', str(state))
        self.assertEqual(bpy.ops.af.create_muscle_from_fiber_surface(surface_id=surface.id), {'FINISHED'})
        muscle = owner.af_vcp_system.muscles[0]
        self.assertEqual(muscle.inflation_mode, 'CTRL_POINT')
        with self.assertRaises(RuntimeError):
            bpy.ops.af.muscle_profile_mode(muscle_id=muscle.id, mode='section_profile')
        self.assertEqual(muscle.section_profile_version, 0)

    def test_missing_source_is_stale_and_raw_invalid_profile_is_inspectable(self):
        owner, _, muscle = fixture()
        with suppress_vcp_prop_updates():
            muscle.fiber_surface_id = 'MISSING'
            muscle['section_depths'] = [float('nan')]*4
        captured, state = commands.inspect(owner, bpy.context.scene, muscle.id)
        self.assertFalse(captured.current)
        self.assertIn('PROFILE_BASE_NOT_CURRENT', str(captured.reasons))
        register_muscle_sync().sync_root_to_scene(owner, bpy.context.scene, {muscle.id})
        self.assertEqual(len(mesh(owner, muscle)), 0)
        with TemporaryDirectory() as folder:
            reply = call(owner, folder, request(owner, 'profile_inspect', 'invalid', target=dict(muscle_id=muscle.id)))
            self.assertEqual(reply['status'], 'success', reply)
            self.assertIn('PROFILE_PARAMETER_RANGE', reply['entities'][0]['profile_error'])
