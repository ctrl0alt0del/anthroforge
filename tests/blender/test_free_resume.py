"""AF-24 resumed delivery: transactional replacement and closed-row conversion."""
from unittest.mock import patch
import bpy
import numpy as np
from mathutils import Vector
from _helpers import BlenderTestCase, capture_world_attachment, fiber, root, mesh_object, scp_with_object, select_only
from test_free_loops import loop_fixture
from _branch_fixture import create_fixture
from test_free_review import allocated, output_state, geometry
from anthroforge.adapters import free_fiber_editor as editor, free_fiber_lifecycle as lifecycle
from anthroforge.app.use_cases import free_fiber as service
from anthroforge.app.use_cases.fiber_surface_create import _new_surface, _assign_refs
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.vcp.fiber_node_attachment import capture_fiber_node_attachments
from anthroforge.core.visualization.fiber_sync import register_fiber_sync
from anthroforge.core.visualization.fiber_sync_helpers import persisted_fiber_points
from anthroforge.core.visualization.fiber_surface_sync import evaluate_surface_record, find_fiber_surface_proxy


def raw_draft(root, fiber):
    rows = editor.draft(root, fiber)
    for row in rows:
        if row['type'] == 'BEZIER':
            for knot in row['values']: knot.pop('sample_id')
    return rows


def prepared_draft():
    owner, _bone, item, _points = loop_fixture()
    objects = editor.open_edit(owner, bpy.context.scene, item); editor.convert_bezier(owner, item)
    point = objects[0].data.splines[0].bezier_points[0]; point.handle_right_type = 'FREE'; point.handle_right.z += .1
    lifecycle.save()
    session = editor.state(owner, item); session['recovery'] = [{'previous': 'must survive'}]; editor.save_state(owner, item, session)
    return owner, item


def fail_second(method):
    calls = []
    def failing(*args, **kwargs):
        calls.append(True)
        if len(calls) == 2: raise RuntimeError('Injected second span failure')
        return method(*args, **kwargs)
    return failing


def fail_after_save(owner, item, value):
    owner[editor.PREFIX + item.id] = editor.json.dumps(value)
    raise RuntimeError('Injected session persistence failure')


def check_replacement_failure(case, rebase, target, name, replacement):
    owner, item = prepared_draft(); raw = owner[editor.PREFIX + item.id]
    previous, allocation, outputs = raw_draft(owner, item), allocated(), output_state(owner)
    with patch.object(target, name, side_effect=replacement):
        with case.assertRaisesRegex(RuntimeError, 'Injected'): editor.refresh(owner, bpy.context.scene, item, rebase)
    case.assertEqual(owner[editor.PREFIX + item.id], raw)
    case.assertEqual(raw_draft(owner, item), previous); case.assertEqual(allocated(), allocation)
    case.assertEqual(output_state(owner), outputs)
    editor.cancel(owner, item)


def controlled_loop(owner, scp, points):
    samples = [Vector(a).lerp(Vector(b), u) for a, b in zip(points, np.roll(points, -1, axis=0)) for u in (0., .5)]
    with suppress_vcp_prop_updates():
        item = fiber(owner, scp.id, scp.id); item.topology_mode = 'LOOP'; item.node_count = len(samples)
        for point in points:
            anchor = item.loop_anchors.add(); anchor.parent_id = scp.id
            anchor.attach_param = capture_world_attachment(owner, scp.id, Vector(point))
    register_fiber_sync().apply_points(owner, bpy.context.scene, item, samples)
    captured = capture_fiber_node_attachments(owner, bpy.context.scene, item, samples)
    assert captured.ok, captured.error
    return item


def closed_loft(reverse=False):
    owner = root(); first_bone = mesh_object('First loop'); second_bone = mesh_object('Second loop', (0, 0, 1))
    first_scp = scp_with_object(owner, 'First loop', first_bone); second_scp = scp_with_object(owner, 'Second loop', second_bone)
    points = np.array([(.1, .1, 0), (.3, .1, 0), (.3, .3, 0), (.1, .3, 0)])
    second = np.roll(points, 2, axis=0) + (0, 0, 1); second = second[::-1] if reverse else second
    first, last = controlled_loop(owner, first_scp, points), controlled_loop(owner, second_scp, second)
    with suppress_vcp_prop_updates():
        surface = _new_surface(owner.af_vcp_system, 'Closed conversion', 'LOFT', False, False)
        _assign_refs(surface, [first.id, last.id])
    return owner, first, last, surface


def check_loft_shape(case, result):
    for row in np.asarray(result.rows):
        np.testing.assert_allclose(row[:, :2].min(axis=0), (.1, .1), atol=1e-6)
        np.testing.assert_allclose(row[:, :2].max(axis=0), (.3, .3), atol=1e-6)
        area = np.sum(row[:, 0] * np.roll(row[:, 1], -1) - row[:, 1] * np.roll(row[:, 0], -1)) / 2
        case.assertAlmostEqual(area, .04, places=6)
    np.testing.assert_allclose(np.asarray(result.vertices).min(axis=0), (.1, .1, 0), atol=1e-6)
    np.testing.assert_allclose(np.asarray(result.vertices).max(axis=0), (.3, .3, 1), atol=1e-6)


def mixed_junction():
    owner, _muscle, connection, fibers = create_fixture()
    for item in (fibers[0], fibers[2]): service.configure_mode(owner, bpy.context.scene, item, 'FREE')
    with suppress_vcp_prop_updates(): owner.af_scp_system.scps[0].mirror_enabled = True
    service.rebuild(owner, bpy.context.scene, {item.id for item in fibers})
    point = next(p for p in owner.af_vcp_system.authored_points if p.id == connection.roots[0].point_id)
    return owner, point


def check_restored_outputs(case, actual, expected):
    case.assertEqual(actual['records'], expected['records']); case.assertEqual(actual['runtime'], expected['runtime'])
    case.assertEqual(actual['geometry'].keys(), expected['geometry'].keys())
    for key, (geometry, custom, matrix) in actual['geometry'].items():
        saved = expected['geometry'][key]
        case.assertEqual((geometry, custom), saved[:2])
        np.testing.assert_allclose(matrix, saved[2], atol=1e-6)


def invalidate_skeleton(owner):
    from anthroforge.core.scp_runtime.common import find_geometry_mesh_scp_obj
    from anthroforge.core.visualization import free_fiber_runtime as runtime
    bone = find_geometry_mesh_scp_obj(bpy.context.scene, owner.name, owner.af_scp_system.scps[0].id)
    bone.data.clear_geometry(); bpy.context.view_layer.update()
    return [runtime.update(owner, bpy.context.scene, item) for item in owner.af_vcp_system.fibers if item.behavior_mode == 'FREE']


def check_stale_outputs(case, outputs, before):
    for obj in outputs:
        case.assertEqual(geometry(obj), before[obj.name])
        source = next((o for o in outputs if o.data == obj.data and not o.get('af_muscle_mirror_proxy')), obj)
        key = 'af_fiber_surface_output_state' if source.get('af_fiber_surface_proxy') else 'af_muscle_output_state'
        case.assertEqual(source.get(key), 'STALE', source.name)


class FreeResumeTests(BlenderTestCase):
    def test_invalid_skeleton_retains_mixed_outputs_as_stale_without_solver(self):
        from anthroforge.core.visualization.fiber_surface_sync import register_fiber_surface_sync
        from anthroforge.core.visualization.muscle_sync import register_muscle_sync
        owner, _point = mixed_junction(); scene = bpy.context.scene
        outputs = [o for o in scene.objects if o.get('af_fiber_surface_proxy') or o.get('af_muscle_proxy')]
        before = {o.name: geometry(o) for o in outputs}; self.assertTrue(before)
        with patch('anthroforge.core.visualization.fiber_refinement.begin_fiber_solve', side_effect=AssertionError('solver')):
            self.assertTrue(all(not result[0] for result in invalidate_skeleton(owner)))
            register_fiber_surface_sync().sync_root_to_scene(owner, scene)
            register_muscle_sync().sync_root_to_scene(owner, scene)
        check_stale_outputs(self, outputs, before)

    def test_direct_shared_edit_rolls_back_mixed_assembly_after_partial_numeric_publication(self):
        from anthroforge.core.vcp.shared_point_storage import point_updated
        from anthroforge.core.visualization import muscle_numeric_runtime as numeric
        owner, point = mixed_junction(); before = output_state(owner); offset = point.normal_offset
        with suppress_vcp_prop_updates(): point.normal_offset += .05
        with patch.object(numeric, '_sync_control', side_effect=RuntimeError('Injected partial muscle publication')):
            with patch('anthroforge.app.runtime_api.schedule_context') as schedule:
                with self.assertRaises((ValueError, RuntimeError)): point_updated(point, bpy.context)
                schedule.assert_not_called()
        self.assertEqual(point.normal_offset, offset)
        check_restored_outputs(self, output_state(owner), before)

    def test_refresh_allocation_failure_retains_raw_bezier_session_and_recovery(self):
        check_replacement_failure(self, False, editor, '_poly', fail_second(editor._poly))

    def test_rebase_allocation_failure_retains_raw_bezier_session_and_recovery(self):
        check_replacement_failure(self, True, editor, '_poly', fail_second(editor._poly))

    def test_rebase_failure_after_first_span_retains_raw_bezier_session_and_recovery(self):
        check_replacement_failure(self, True, editor.free_path, 'rebase_span', fail_second(editor.free_path.rebase_span))

    def test_refresh_partial_persistence_failure_restores_raw_session_and_recovery(self):
        check_replacement_failure(self, False, editor, 'save_state', fail_after_save)

    def test_rebase_partial_persistence_failure_restores_raw_session_and_recovery(self):
        check_replacement_failure(self, True, editor, 'save_state', fail_after_save)

    def test_mesh_apply_rejects_without_mutation_then_cancel_cleans_every_span(self):
        owner, _bone, item, _points = loop_fixture(); committed = output_state(owner)
        objects = editor.open_edit(owner, bpy.context.scene, item); select_only(objects[0])
        bpy.ops.object.convert(target='MESH'); mesh_name = bpy.context.object.data.name
        raw, allocation = owner[editor.PREFIX + item.id], allocated()
        with self.assertRaisesRegex(ValueError, 'native curve'): editor.apply(owner, bpy.context.scene, item)
        self.assertEqual(owner[editor.PREFIX + item.id], raw); self.assertEqual(allocated(), allocation)
        self.assertEqual(output_state(owner), committed); editor.cancel(owner, item)
        self.assertIsNone(editor.state(owner, item)); self.assertNotIn(mesh_name, bpy.data.meshes)
        self.assertFalse(any(obj.get('af_free_editor_session') for obj in bpy.data.objects))
        self.assertEqual(output_state(owner), committed)

    def test_shifted_controlled_loop_conversion_preserves_loft_and_source(self):
        self.check_closed_conversion(False)

    def test_reversed_controlled_loop_conversion_preserves_loft_and_source(self):
        self.check_closed_conversion(True)

    def check_closed_conversion(self, reverse):
        owner, first, last, surface = closed_loft(reverse); scene = bpy.context.scene
        sources = [persisted_fiber_points(scene, owner.name, item.id) for item in (first, last)]
        before = evaluate_surface_record(owner, scene, surface)
        service.configure_mode(owner, scene, last, 'FREE'); after = evaluate_surface_record(owner, scene, surface)
        check_loft_shape(self, before); check_loft_shape(self, after)
        for item, points in zip((first, last), sources): self.assertEqual(persisted_fiber_points(scene, owner.name, item.id), points)
        proxy = find_fiber_surface_proxy(scene, owner.name, surface.id)
        np.testing.assert_allclose([vertex.co[:] for vertex in proxy.data.vertices], after.vertices, atol=1e-6)
        self.assertEqual(proxy['af_fiber_surface_output_state'], 'CURRENT')
