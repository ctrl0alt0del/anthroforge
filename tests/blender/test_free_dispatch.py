"""Public Free completion and creation contracts against native output geometry."""
from contextlib import contextmanager
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4
import bpy
import numpy as np
from _helpers import BlenderTestCase, reset_scene
from _branch_fixture import create_fixture
from test_free_resume import closed_loft
from test_free_review import geometry, output_state
from anthroforge.adapters import free_fiber_editor as editor
from anthroforge.app.use_cases import free_fiber as service
from anthroforge.app.use_cases.fiber_surface_create import create_fiber_surface
from anthroforge.app.use_cases.muscle_create import create_muscle_vcp
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.visualization import fiber_refinement as refinement, sync_runner
from anthroforge.core.visualization.fiber_surface_sync import evaluate_surface_record, find_fiber_surface_proxy
from anthroforge.core.visualization.free_output_verification import verify_outputs, affected_surfaces


@contextmanager
def no_solver():
    with patch.object(refinement, 'begin_fiber_solve', side_effect=AssertionError('solver')):
        with patch.object(refinement, '_hard_anchor_preflight', side_effect=AssertionError('planner')):
            yield


def flush():
    with patch.object(sync_runner, '_now', return_value=1e12):
        for _ in range(32):
            if not sync_runner._PENDING: break
            sync_runner._flush_pending()
    assert not sync_runner._PENDING and not sync_runner._TAIL_PENDING


def selected(owner, fibers):
    for obj in tuple(bpy.context.selected_objects): obj.select_set(False)
    for fiber in fibers:
        obj = next(o for o in bpy.context.scene.objects if o.get('af_fiber_proxy')
                   and not o.get('af_fiber_mirror_proxy') and o.get('af_fiber_id') == fiber.id)
        obj.select_set(True); bpy.context.view_layer.objects.active = obj


def branch_scene():
    owner, muscle, _connection, fibers = create_fixture()
    from anthroforge.core.vcp.fiber_node_attachment import capture_fiber_node_attachments
    from anthroforge.core.visualization.fiber_sync_helpers import persisted_fiber_points
    for item in fibers:
        result = capture_fiber_node_attachments(owner, bpy.context.scene, item,
                                              persisted_fiber_points(bpy.context.scene, owner.name, item.id))
        assert result.ok, result.error
    for item in (fibers[0], fibers[1]): service.configure_mode(owner, bpy.context.scene, item, 'FREE')
    with suppress_vcp_prop_updates(): owner.af_scp_system.scps[0].mirror_enabled = True
    service.rebuild(owner, bpy.context.scene, {f.id for f in fibers})
    flush()
    return owner, muscle, fibers


def dependent_objects(owner, item):
    ids = {s.id for s in affected_surfaces(owner, {item.id})}
    muscles = {m.id for m in owner.af_vcp_system.muscles if m.fiber_surface_id in ids}
    return [o for o in bpy.context.scene.objects if o.get('af_fiber_surface_id') in ids
            or (o.get('af_muscle_proxy') and o.get('af_muscle_id') in muscles)]


def snapshots(objects):
    return {o.name: geometry(o) for o in objects}


def assert_stale(case, objects, previous):
    case.assertTrue(objects)
    for obj in objects:
        case.assertEqual(geometry(obj), previous[obj.name], obj.name)
        key = 'af_fiber_surface_output_state' if obj.get('af_fiber_surface_proxy') else 'af_muscle_output_state'
        source = next((o for o in objects if o.data == obj.data and not o.get('af_muscle_mirror_proxy')), obj)
        case.assertEqual(source.get(key), 'STALE', obj.name)


def api_recompute(owner, ids):
    from anthroforge.adapters.authoring.scene import StaticScene
    from anthroforge.app.authoring.api import execute
    port = StaticScene(owner, bpy.context.scene); port.initialize()
    request = dict(version='0.4.0', message_type='request', request_id=str(uuid4()), op='fibers.recompute',
                   params=dict(scene_id=owner.name, fiber_ids=ids, expected_scene_revision=port.capture_authoring()['revision']))
    with TemporaryDirectory() as directory: return execute(request, owner, bpy.context.scene, directory)


def public_pair(topology, both_free=True):
    if topology == 'LOOP':
        owner, first, last, _surface = closed_loft(); fibers = (first, last)
    else:
        owner, _muscle, _connection, rows = create_fixture(); fibers = (rows[0], rows[1])
    for item in fibers if both_free else fibers[1:]: service.configure_mode(owner, bpy.context.scene, item, 'FREE')
    item = fibers[-1]; item.free_sampling_resolution = 13
    editor.open_edit(owner, bpy.context.scene, item); editor.resample(owner, item); editor.apply(owner, bpy.context.scene, item)
    with suppress_vcp_prop_updates(): fibers[-1].node_count = 64 if topology == 'LOOP' else 8
    selected(owner, fibers)
    return owner, fibers


def assert_created(case, owner, result, muscle=False):
    case.assertTrue(result.ok, result.message)
    item = result.value
    surface = next(s for s in owner.af_vcp_system.fiber_surfaces if s.id == item.fiber_surface_id) if muscle else item
    expected = evaluate_surface_record(owner, bpy.context.scene, surface)
    proxy = find_fiber_surface_proxy(bpy.context.scene, owner.name, surface.id)
    case.assertTrue(expected.faces); case.assertEqual(proxy.get('af_fiber_surface_output_state'), 'CURRENT')
    np.testing.assert_allclose([v.co[:] for v in proxy.data.vertices], expected.vertices, atol=1e-6)
    verify_outputs(owner, bpy.context.scene, {ref.fiber_id for ref in surface.fiber_refs})


class FreeDispatchTests(BlenderTestCase):
    def test_material_mirror_error_rolls_back_apply_and_preserves_draft(self):
        from anthroforge.core.visualization import free_output_verification as verification
        from test_free_resume import check_restored_outputs
        owner, _muscle, fibers = branch_scene(); item = fibers[1]; before = output_state(owner)
        objects = editor.open_edit(owner, bpy.context.scene, item); objects[0].data.splines[0].points[1].co.z += .01
        draft = editor.draft(owner, item); original = verification._mirrors
        def displaced(*args):
            mirror = next(o for o in bpy.context.scene.objects if o.get('af_fiber_mirror_proxy') and o.get('af_fiber_id') == item.id)
            mirror.matrix_world.translation.x += .01
            return original(*args)
        with no_solver(), patch.object(verification, '_mirrors', side_effect=displaced):
            with self.assertRaisesRegex(ValueError, 'derived mirror'): editor.apply(owner, bpy.context.scene, item)
        self.assertEqual(editor.draft(owner, item), draft); check_restored_outputs(self, output_state(owner), before)

    def test_reopened_mirrors_allow_free_edit_but_reject_material_transform_error(self):
        from pathlib import Path
        from anthroforge.adapters.authoring.scene import StaticScene
        from anthroforge.core.visualization.free_fiber_runtime import current
        owner, _muscle, fibers = branch_scene(); name, key = owner.name, fibers[1].id
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'dispatch.blend'; StaticScene(owner, bpy.context.scene).save_debug_copy(path)
            with no_solver(): bpy.ops.wm.open_mainfile(filepath=str(path))
            owner = bpy.data.objects[name]; item = next(f for f in owner.af_vcp_system.fibers if f.id == key)
            payload, points = current(owner, bpy.context.scene, item); points = list(points); points[1].z += .01
            with no_solver(): service.commit(owner, bpy.context.scene, item, payload, points)
            mirror = next(o for o in bpy.context.scene.objects if o.get('af_fiber_mirror_proxy') and o.get('af_fiber_id') == key)
            mirror.matrix_world.translation.x += .01
            with self.assertRaisesRegex(ValueError, 'derived mirror'): verify_outputs(owner, bpy.context.scene, {key})

    def test_public_api_success_publishes_current_meshes_and_mirrors_before_done(self):
        owner, _muscle, fibers = branch_scene(); item = fibers[1]
        objects = dependent_objects(owner, item); before = snapshots(objects)
        owner.af_scp_system.scps[0].geometry_object_ref.location.z += .25; bpy.context.view_layer.update()
        with no_solver(): result = api_recompute(owner, [item.id])
        self.assertTrue(result['published']); self.assertTrue(result['recompute']['done'])
        self.assertFalse(result['recompute']['failures']); verify_outputs(owner, bpy.context.scene, {item.id})
        for obj in objects: self.assertNotEqual(geometry(obj), before[obj.name], obj.name)

    def test_standalone_moves_loft_transitive_branch_inflation_and_mirrors_once(self):
        owner, _muscle, fibers = branch_scene(); item = fibers[1]
        objects = dependent_objects(owner, item); before = snapshots(objects)
        bone = owner.af_scp_system.scps[0].geometry_object_ref; bone.location.z += .25
        bpy.context.view_layer.update()
        with no_solver(), patch.object(refinement, '_sync_fiber_group', wraps=refinement._sync_fiber_group) as dispatch:
            result = refinement.request_fiber_refinement(owner, bpy.context.scene, item); flush()
        self.assertTrue(result.ok, result.error); self.assertEqual(dispatch.call_count, 1)
        verify_outputs(owner, bpy.context.scene, {item.id})
        for obj in objects: self.assertNotEqual(geometry(obj), before[obj.name], obj.name)
        self.assertTrue(any(o.get('af_muscle_mirror_proxy') for o in objects))

    def test_direct_property_success_refreshes_dependents_and_mirrors(self):
        owner, _muscle, fibers = branch_scene(); item = fibers[1]
        objects = dependent_objects(owner, item); before = snapshots(objects)
        owner.af_scp_system.scps[0].geometry_object_ref.location.z += .25; bpy.context.view_layer.update()
        with no_solver(), patch.object(refinement, '_sync_fiber_group', wraps=refinement._sync_fiber_group) as dispatch:
            item.node_count += 1; flush()
        self.assertEqual(dispatch.call_count, 1); verify_outputs(owner, bpy.context.scene, {item.id})
        for obj in objects: self.assertNotEqual(geometry(obj), before[obj.name], obj.name)

    def test_direct_topology_failure_retains_all_dependent_geometry_stale(self):
        owner, _muscle, fibers = branch_scene(); item = fibers[1]
        objects = dependent_objects(owner, item); before = snapshots(objects)
        with no_solver(): item.topology_mode = 'LOOP'; flush()
        assert_stale(self, objects, before)

    def test_standalone_failure_retains_all_dependent_geometry_stale(self):
        owner, _muscle, fibers = branch_scene(); item = fibers[1]
        objects = dependent_objects(owner, item); before = snapshots(objects)
        with suppress_vcp_prop_updates(): item.topology_mode = 'LOOP'
        with no_solver(): result = refinement.request_fiber_refinement(owner, bpy.context.scene, item); flush()
        self.assertFalse(result.ok); assert_stale(self, objects, before)

    def test_all_failed_group_and_public_api_preserve_geometry_with_honest_status(self):
        for public_api in (False, True):
            with self.subTest(public_api=public_api):
                reset_scene(); owner, _muscle, fibers = branch_scene(); item = fibers[1]
                objects = dependent_objects(owner, item); before = snapshots(objects)
                with suppress_vcp_prop_updates(): item.free_path_json = '{}'
                with no_solver():
                    value = api_recompute(owner, [item.id]) if public_api else refinement.fiber_refinement_group_state(
                        refinement.request_fiber_refinement_group(owner, bpy.context.scene, [item.id]))
                    flush()
                state = value['recompute'] if public_api else value
                self.assertTrue(state['done']); self.assertIn(item.id, state['failures']); self.assertFalse(state['committed'])
                if public_api: self.assertFalse(value['published']); self.assertEqual(value['status'], 'unresolved')
                assert_stale(self, objects, before)

    def test_partial_group_keeps_failed_family_stale_and_reports_successful_member(self):
        owner, _muscle, fibers = branch_scene(); good, bad = fibers[:2]
        objects = dependent_objects(owner, bad); before = snapshots(objects)
        with suppress_vcp_prop_updates(): bad.free_path_json = '{}'
        with no_solver(), patch.object(refinement, '_sync_fiber_group', wraps=refinement._sync_fiber_group) as dispatch:
            token = refinement.request_fiber_refinement_group(owner, bpy.context.scene, [good.id, bad.id]); flush()
        state = refinement.fiber_refinement_group_state(token)
        self.assertEqual(state['committed'], (good.id,)); self.assertIn(bad.id, state['failures'])
        self.assertEqual(dispatch.call_count, 1); assert_stale(self, objects, before)

    def test_mixed_controlled_group_does_not_claim_failed_free_dependency_current(self):
        owner, first, last, surface = closed_loft(); service.configure_mode(owner, bpy.context.scene, last, 'FREE')
        objects = [find_fiber_surface_proxy(bpy.context.scene, owner.name, surface.id)]; before = snapshots(objects)
        with suppress_vcp_prop_updates(): last.free_path_json = '{}'
        with patch.object(refinement, '_hard_anchor_preflight', wraps=refinement._hard_anchor_preflight) as preflight:
            token = refinement.request_fiber_refinement_group(owner, bpy.context.scene, [first.id, last.id])
            refinement.drain_fiber_refinements(); flush()
        state = refinement.fiber_refinement_group_state(token)
        self.assertTrue(state['done']); self.assertIn(last.id, state['failures']); self.assertIn(first.id, state['committed'])
        self.assertTrue(preflight.call_args_list)
        self.assertTrue(all(call.args[2].id == first.id for call in preflight.call_args_list))
        assert_stale(self, objects, before)


class FreePublicCreationTests(BlenderTestCase):
    def test_public_surface_and_muscle_accept_free_and_mixed_open_loop_counts(self):
        for topology in ('OPEN', 'LOOP'):
            for both in (False, True):
                for command in (create_fiber_surface, create_muscle_vcp):
                    with self.subTest(topology=topology, both_free=both, command=command.__name__):
                        reset_scene(); owner, fibers = public_pair(topology, both)
                        before = tuple(f.free_path_json for f in fibers)
                        with no_solver(): result = command(bpy.context)
                        assert_created(self, owner, result, command == create_muscle_vcp)
                        self.assertEqual(tuple(f.free_path_json for f in fibers), before)

    def test_controlled_count_and_mixed_topology_rejection_have_no_partial_allocations(self):
        for command in (create_fiber_surface, create_muscle_vcp):
            for mixed in (False, True):
                with self.subTest(command=command.__name__, mixed_topology=mixed):
                    reset_scene(); owner, first, last, _surface = closed_loft()
                    if mixed: service.configure_mode(owner, bpy.context.scene, last, 'FREE')
                    with suppress_vcp_prop_updates():
                        if mixed: last.topology_mode = 'OPEN'
                        else: last.node_count = 64
                    selected(owner, (first, last)); before = output_state(owner)
                    with no_solver(): result = command(bpy.context)
                    self.assertFalse(result.ok); self.assertEqual(output_state(owner), before)
                    self.assertIn('open and loop' if mixed else 'identical node_count', result.message)

    def test_free_invalid_and_budget_errors_reject_before_allocating_records_or_meshes(self):
        from anthroforge.core.vcp import free_surface
        for command in (create_fiber_surface, create_muscle_vcp):
            for invalid in (False, True):
                with self.subTest(command=command.__name__, invalid=invalid):
                    reset_scene(); owner, fibers = public_pair('LOOP')
                    if invalid:
                        with suppress_vcp_prop_updates(): fibers[-1].free_path_json = '{}'
                    before = output_state(owner); meshes = set(bpy.data.meshes.keys())
                    with no_solver(), patch.object(free_surface, 'MAX_VERTICES', 1 if not invalid else 262144):
                        result = command(bpy.context)
                    self.assertFalse(result.ok); self.assertEqual(output_state(owner), before)
                    self.assertEqual(set(bpy.data.meshes.keys()), meshes)

    def test_native_surface_operator_uses_free_count_contract(self):
        owner, _fibers = public_pair('LOOP', False)
        with no_solver(): self.assertEqual(bpy.ops.af.create_fiber_surface(), {'FINISHED'})
        surface = owner.af_vcp_system.fiber_surfaces[-1]
        self.assertTrue(evaluate_surface_record(owner, bpy.context.scene, surface).faces)

    def test_native_muscle_operator_uses_free_count_contract(self):
        owner, fibers = public_pair('OPEN', False)
        with no_solver(): self.assertEqual(bpy.ops.af.add_muscle_vcp(), {'FINISHED'})
        verify_outputs(owner, bpy.context.scene, {f.id for f in fibers})
