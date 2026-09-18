"""AF-23 review regressions: proxy rollback, invalid activation and legacy recovery."""
from tempfile import TemporaryDirectory
from unittest.mock import patch
import bpy
import numpy as np
from _helpers import BlenderTestCase, reset_scene, select_only
from test_muscle_section_profile import fixture, mesh
from test_authoring_native_profiles import inspect, request, call, fail_response
from anthroforge.core.authoring.storage import FileStore
from anthroforge.core.authoring.profile_config import wire
from anthroforge.core.vcp.muscle_section_profile import reset_profile, PROFILE_FIELDS
from anthroforge.core.vcp.fiber_solver import FiberSolver
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.visualization.muscle_sync import register_muscle_sync
from anthroforge.core.visualization.muscle_profile_publish import affected_objects


def selected_control():
    owner, surface, muscle = fixture(False)
    base = next(obj for obj in affected_objects(owner, bpy.context.scene, muscle.id) if obj.get('af_muscle_surface') == 'BASE')
    select_only(base)
    register_muscle_sync().sync_root_to_scene(owner, bpy.context.scene, {muscle.id})
    control = controls(owner, muscle)[0]
    select_only(control)
    bpy.context.view_layer.update()
    return owner, surface, muscle, control


def controls(owner, muscle):
    return [obj for obj in affected_objects(owner, bpy.context.scene, muscle.id) if obj.get('af_muscle_inflation_ctrl')]


def control_state(obj):
    return dict(name=obj.name, display=obj.empty_display_type, size=obj.empty_display_size, front=obj.show_in_front,
        hide_render=obj.hide_render, hide_viewport=obj.hide_viewport, hide_select=obj.hide_select, color=tuple(obj.color),
        show_name=obj.show_name, locks=tuple(obj.lock_rotation), parent=getattr(obj.parent, 'name', None),
        inverse=tuple(tuple(row) for row in obj.matrix_parent_inverse), basis=tuple(tuple(row) for row in obj.matrix_basis),
        collections=sorted(c.name for c in obj.users_collection),
        layers=[(layer.name, obj.hide_get(view_layer=layer), obj.select_get(view_layer=layer), layer.objects.active == obj)
                for layer in bpy.context.scene.view_layers if layer.objects.get(obj.name) == obj])


def configure_request(owner, directory, muscle, config, identity):
    _, guards = inspect(owner, directory, dict(muscle_id=muscle.id), identity+'-inspect')
    return request(owner, 'profile_configure', identity, muscle_id=muscle.id, configuration=config, **guards)


def failed_switch(owner, muscle, directory):
    payload = configure_request(owner, directory, muscle, wire(reset_profile(.3)), 'rollback')
    with patch.object(FileStore, 'put', fail_response(FileStore.put)):
        return call(owner, directory, payload)


def control_hierarchy(control):
    parent, child = [bpy.data.objects.new(name, None) for name in ('RollbackParent', 'RollbackChild')]
    for obj in (parent, child):
        bpy.context.scene.collection.objects.link(obj)
    control.parent, child.parent, child.location = parent, control, (.1, .2, .3)
    control.color, control.show_name, control.lock_rotation = (.1, .2, .3, .4), True, (True, False, True)
    layer = bpy.context.scene.view_layers.new('HiddenControl')
    layer.update(); control.hide_set(True, view_layer=layer)
    bpy.context.view_layer.update()
    return parent.name, child.name, tuple(tuple(row) for row in child.matrix_world)


def closed_legacy():
    owner, surface, muscle = fixture(False)
    with suppress_vcp_prop_updates():
        surface.close_across_fibers = True
        muscle.section_profile_version, muscle.section_depths = 1, (.1, .2, .3, .4)
    return owner, surface, muscle


def profile_values(muscle):
    return tuple(tuple(getattr(muscle, key)) if key in ('section_depths', 'section_peaks') else getattr(muscle, key) for key in PROFILE_FIELDS)


def invalid_activation(test, version, roundness, stale):
    reset_scene(); owner, _, muscle, control = selected_control()
    with suppress_vcp_prop_updates():
        muscle['section_profile_version'], muscle['section_roundness'] = version, roundness
    if stale:
        next(obj for obj in bpy.context.scene.objects if obj.get('af_fiber_proxy'))['af_fiber_output_state'] = 'STALE'
    name = control.name
    with patch.object(FiberSolver, 'solve_points', side_effect=AssertionError('Unexpected fiber solve')):
        muscle.inflation_mode = 'SECTION_PROFILE'
        bpy.context.view_layer.update()
    test.assertIsNone(bpy.data.objects.get(name)); test.assertEqual(controls(owner, muscle), [])
    test.assertIn('PROFILE_', muscle.get('_af_rt_section_profile_error', ''))
    test.assertTrue(all(obj.get('af_muscle_output_state') == ('STALE' if stale else 'INVALID') for obj in affected_objects(owner, bpy.context.scene, muscle.id)))


class ProfileReviewTests(BlenderTestCase):
    def test_failed_profile_switch_restores_selected_control_display(self):
        owner, _, muscle, control = selected_control()
        before, geometry = control_state(control), mesh(owner, muscle).copy()
        with TemporaryDirectory() as folder:
            self.assertEqual(failed_switch(owner, muscle, folder)['status'], 'failed')
        bpy.context.view_layer.update()
        self.assertEqual(muscle.inflation_mode, 'CTRL_POINT')
        self.assertEqual(control_state(controls(owner, muscle)[0]), before)
        np.testing.assert_array_equal(mesh(owner, muscle), geometry)
        self.assertNotIn('af_authoring_profile_receipt', muscle)

    def test_failed_profile_switch_restores_hierarchy_and_layer_visibility(self):
        owner, _, muscle, control = selected_control()
        parent, child, child_world = control_hierarchy(control)
        before = control_state(control)
        with TemporaryDirectory() as folder:
            self.assertEqual(failed_switch(owner, muscle, folder)['status'], 'failed')
        bpy.context.view_layer.update()
        restored = controls(owner, muscle)[0]
        self.assertEqual(control_state(restored), before)
        self.assertEqual(restored.parent.name, parent)
        self.assertEqual(bpy.data.objects[child].parent, restored)
        np.testing.assert_array_equal(bpy.data.objects[child].matrix_world, child_world)

    def test_invalid_and_stale_direct_activation_remove_target_control(self):
        for version, roundness, stale in ((0, 1, False), (77, 1, False), (1, float('nan'), False), (1, 1, True)):
            with self.subTest(version=version, roundness=roundness, stale=stale):
                invalid_activation(self, version, roundness, stale)

    def test_closed_domain_legacy_configuration_has_live_guards_and_parity(self):
        owner, _, muscle = closed_legacy(); values, amount = profile_values(muscle), muscle.inflation_max_value
        with TemporaryDirectory() as folder, patch.object(FiberSolver, 'solve_points', side_effect=AssertionError('Unexpected fiber solve')):
            self.assertEqual(bpy.ops.af.muscle_profile_mode(muscle_id=muscle.id, mode='distributed'), {'FINISHED'})
            expected = mesh(owner, muscle).copy()
            first = configure_request(owner, folder, muscle, dict(mode='control_point'), 'legacy-control')
            self.assertTrue(call(owner, folder, first)['published'])
            second = configure_request(owner, folder, muscle, dict(mode='distributed'), 'legacy-distributed')
            result = call(owner, folder, second)
            self.assertTrue(result['published'], result); self.assertTrue(call(owner, folder, second)['replayed'])
            self.assertEqual(call(owner, folder, first)['diagnostics'][0]['code'], 'STALE_PROFILE_RECEIPT')
        self.assertTrue(result['entities'][0]['current']); self.assertFalse(result['entities'][0]['eligible'])
        self.assertTrue(result['entities'][0]['base_revision'])
        self.assertEqual(profile_values(muscle), values); self.assertEqual(muscle.inflation_max_value, amount)
        np.testing.assert_array_equal(mesh(owner, muscle), expected)

    def test_closed_domain_still_rejects_profile_and_new_creation(self):
        owner, surface, muscle = closed_legacy()
        with TemporaryDirectory() as folder, patch.object(FiberSolver, 'solve_points', side_effect=AssertionError('Unexpected fiber solve')):
            payload = configure_request(owner, folder, muscle, wire(reset_profile(.3)), 'closed-profile')
            self.assertEqual(call(owner, folder, payload)['diagnostics'][0]['code'], 'PROFILE_DOMAIN_UNSUPPORTED')
            result, guards = inspect(owner, folder, dict(fiber_surface_id=surface.id), 'closed-source')
            self.assertTrue(result['entities'][0]['current']); self.assertTrue(guards['expected_base_revision'])
            payload = request(owner, 'create_from_surface', 'closed-create', surface_id=surface.id, **guards)
            self.assertEqual(call(owner, folder, payload)['diagnostics'][0]['code'], 'PROFILE_DOMAIN_UNSUPPORTED')
        self.assertEqual(len(owner.af_vcp_system.muscles), 1)
