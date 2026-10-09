"""Production muscle surfaces as Fiber attachment parents."""
import json
import bpy
from mathutils import Vector
from _helpers import BlenderTestCase
from test_soft_tissue_muscle_attachment import _muscle_tissue
from anthroforge.core.vcp import attachment_backend as bindings
from anthroforge.core.vcp.surface_reference import key, reference, from_object
from anthroforge.core.vcp.surface_target import target_ref
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.vcp.fiber_node_attachment import capture_fiber_node_attachments, resolve_fiber_node_attachments


def parent_fixture():
    owner, muscle, _tissue, _base, surface = _muscle_tissue('INFL')
    return owner, muscle, surface, key(from_object(surface))


def bound_fiber(owner, surface, parent):
    from anthroforge.core.id_utils import next_prefixed_id
    ends = [surface.matrix_world @ surface.data.vertices[i].co for i in (0, 2)]
    points = [ends[0].lerp(ends[1], index / 7) for index in range(8)]
    with suppress_vcp_prop_updates():
        item = owner.af_vcp_system.fibers.add(); item.id = next_prefixed_id(owner.af_vcp_system.fibers, 'FIBER')
        item.node_count = 8
        for side, point in zip(('a', 'b'), (points[0], points[-1])):
            setattr(item, side + '_parent_id', parent)
            setattr(item, side + '_attach_param', bindings.capture_attachment_from_world(owner, bpy.context.scene, parent, point))
    return item, points


def mirrored_surface(owner, muscle, surface):
    from mathutils import Matrix
    mirror = surface.copy(); mirror.data = surface.data.copy()
    bpy.context.scene.collection.objects.link(mirror)
    mirror.matrix_world = Matrix.Diagonal((-1., 1., 1., 1.)) @ surface.matrix_world
    mirror['af_muscle_mirror_proxy'] = True; mirror['af_source_muscle_id'] = muscle.id
    for vertex in mirror.data.vertices: vertex.co.z += .25
    mirror.data.update(); bpy.context.view_layer.update()
    return mirror


def arched_fiber(owner, surface, parent, shift=0):
    from math import sin, pi
    fiber, _points = bound_fiber(owner, surface, parent)
    queries = (Vector((1.05, .25 + shift, 1)), Vector((1.65, .75 + shift, 1)))
    with suppress_vcp_prop_updates():
        for side, point in zip(('a', 'b'), queries):
            setattr(fiber, side + '_attach_param', bindings.capture_attachment_from_world(owner, bpy.context.scene, parent, point))
    a, b = [bindings.resolve_attachment_world(owner, bpy.context.scene, parent, getattr(fiber, side + '_attach_param')) for side in ('a', 'b')]
    points = [a.lerp(b, i / 7) + Vector((0, 0, .2 * sin(pi * i / 7))) for i in range(8)]
    from anthroforge.core.visualization.fiber_sync import register_fiber_sync
    register_fiber_sync().apply_points(owner, bpy.context.scene, fiber, points, commit=True)
    return fiber, points


def tissue_chain(preset):
    from _helpers import find_flagged, select_only
    from anthroforge.app.use_cases.free_fiber import configure_mode
    owner, muscle, surface, parent = parent_fixture(); curves = []
    for shift in (0, .15):
        fiber, _points = arched_fiber(owner, surface, parent, shift)
        configure_mode(owner, bpy.context.scene, fiber, 'FREE')
        curves.append(find_flagged('af_fiber_proxy', fiber.id, 'af_fiber_id'))
    select_only(curves[0]); curves[1].select_set(True)
    assert bpy.ops.af.create_fiber_surface() == {'FINISHED'}
    loft = owner.af_vcp_system.fiber_surfaces[-1]
    select_only(find_flagged('af_fiber_surface_proxy', loft.id, 'af_fiber_surface_id'))
    bpy.context.scene.af_new_soft_tissue_preset = preset; bpy.context.scene.af_new_soft_tissue_target_obj = None
    assert bpy.ops.af.add_soft_tissue_vcp() == {'FINISHED'}
    return owner, muscle, owner.af_vcp_system.soft_tissues[-1], surface


class MuscleParentFiberTests(BlenderTestCase):
    def test_mirrored_controlled_native_route_keeps_source_bindings(self):
        import os
        from unittest.mock import patch
        from _helpers import find_flagged
        from anthroforge.core.vcp.fiber_instance import MirroredFiber
        from anthroforge.core.visualization.fiber_refinement import request_fiber_refinement, drain_fiber_refinements
        owner, muscle, surface, parent = parent_fixture(); fiber, points = arched_fiber(owner, surface, parent)
        self.assertTrue(capture_fiber_node_attachments(owner, bpy.context.scene, fiber, points).ok)
        raw = fiber.node_attachments_json; mirrored_surface(owner, muscle, surface)
        proxy = find_flagged('af_fiber_proxy', fiber.id, 'af_fiber_id').copy(); proxy.data = proxy.data.copy()
        bpy.context.scene.collection.objects.link(proxy); proxy['af_fiber_mirror_proxy'] = True; proxy['af_source_fiber_id'] = fiber.id
        with patch.dict(os.environ, {'AF_FIBER_ENGINE': 'V3'}):
            result = request_fiber_refinement(owner, bpy.context.scene, MirroredFiber(fiber, True), quality='FINAL')
            self.assertTrue(result.ok, result.error); drain_fiber_refinements()
        self.assertEqual(raw, fiber.node_attachments_json)
        self.assertTrue(fiber.get('af_mirror_node_bindings'), proxy.get('af_attachment_error'))

    def test_controlled_muscle_fiber_uses_native_v3(self):
        import os
        from unittest.mock import patch
        from _helpers import find_flagged
        from anthroforge.core.visualization.fiber_refinement import request_fiber_refinement, drain_fiber_refinements
        from anthroforge.core.vcp.runtime_state import fiber_invalid_reason
        owner, _muscle, surface, parent = parent_fixture()
        fiber, _points = arched_fiber(owner, surface, parent)
        with patch.dict(os.environ, {'AF_FIBER_ENGINE': 'V3'}):
            request = request_fiber_refinement(owner, bpy.context.scene, fiber, quality='FINAL')
            self.assertTrue(request.ok, request.error); drain_fiber_refinements()
        self.assertTrue(fiber.node_attachments_json, fiber_invalid_reason(fiber))
        proxy = find_flagged('af_fiber_proxy', fiber.id, 'af_fiber_id')
        self.assertEqual(proxy.get('af_fiber_output_state'), 'CURRENT', fiber_invalid_reason(fiber))

    def test_layer_chain_has_source_relative_constraints_without_target(self):
        from anthroforge.core.visualization.soft_tissue_sync import _evaluate_generic_tissue, register_soft_tissue_sync
        from anthroforge.core.vcp.soft_tissue_source_goals import source_goals
        owner, _muscle, tissue, _surface = tissue_chain('LAYER')
        self.assertEqual((tissue.constraint_reference, tissue.attachment_target_type), ('SOURCE', 'NONE'))
        result = _evaluate_generic_tissue(register_soft_tissue_sync(), owner, bpy.context.scene, tissue, '')
        goals = source_goals(tissue, result.rest, result.sample)
        self.assertTrue(any(mode == 'FIXED' for mode, _i, _p, _s in goals))
        for mode, index, point, _strength in goals:
            if mode == 'FIXED': self.assertLess((Vector(result.final.vertices[index]) - Vector(point)).length, 1e-5)

    def test_pouch_chain_uses_source_goals(self):
        from anthroforge.core.vcp.runtime_state import soft_tissue_status
        _owner, _muscle, tissue, _surface = tissue_chain('POUCH')
        self.assertEqual((tissue.constraint_reference, tissue.attachment_target_type), ('SOURCE', 'NONE'))
        self.assertEqual(soft_tissue_status(tissue), 'CLEAN')

    def test_free_muscle_path_follows_deformation_without_recapture(self):
        from anthroforge.app.use_cases.free_fiber import configure_mode
        from anthroforge.core.visualization.free_fiber_runtime import update, current
        owner, _muscle, surface, parent = parent_fixture()
        fiber, points = arched_fiber(owner, surface, parent)
        configure_mode(owner, bpy.context.scene, fiber, 'FREE')
        raw = fiber.node_attachments_json
        for vertex in surface.data.vertices: vertex.co.z += .125
        surface.data.update(); bpy.context.view_layer.update()
        ok, reason, _proxy = update(owner, bpy.context.scene, fiber)
        self.assertTrue(ok, reason)
        self.assertEqual(raw, fiber.node_attachments_json)
        for source, actual in zip(points, current(owner, bpy.context.scene, fiber)[1]):
            self.assertLess((actual - source - Vector((0, 0, .125))).length, 1e-5)

    def test_actual_mirrored_surface_resolves_asymmetric_geometry(self):
        from anthroforge.core.vcp.fiber_instance import MirroredFiber
        from anthroforge.core.visualization.muscle_fiber_attachment import resolve_batch
        owner, muscle, surface, parent = parent_fixture()
        fiber, points = bound_fiber(owner, surface, parent)
        for index, point in enumerate(points[1:-1], 1): points[index] = point + Vector((0, 0, .1))
        self.assertTrue(capture_fiber_node_attachments(owner, bpy.context.scene, fiber, points).ok)
        mirrored_surface(owner, muscle, surface)
        results, errors = resolve_batch(owner, bpy.context.scene, (MirroredFiber(fiber),))
        self.assertFalse(errors, errors)
        for source, actual in zip(points, results[fiber.id]):
            self.assertLess((actual - Vector((-source.x, source.y, source.z + .25))).length, 1e-5)

    def test_degenerate_triangle_invalidates_python_and_native(self):
        from anthroforge.core.visualization.muscle_fiber_attachment import resolve_batch
        owner, _muscle, surface, parent = parent_fixture()
        fiber, points = bound_fiber(owner, surface, parent)
        self.assertTrue(capture_fiber_node_attachments(owner, bpy.context.scene, fiber, points).ok)
        for vertex in surface.data.vertices: vertex.co = (0, 0, 0)
        surface.data.update(); bpy.context.view_layer.update()
        self.assertIsNone(bindings.resolve_attachment_world(owner, bpy.context.scene, parent, fiber.a_attach_param))
        _points, errors = resolve_batch(owner, bpy.context.scene, (fiber,))
        self.assertIn(fiber.id, errors)

    def test_cyclic_support_assignment_rolls_back(self):
        from anthroforge.app.use_cases.fiber_attachment import set_supports
        owner, _muscle, _surface, parent = parent_fixture()
        fiber = owner.af_vcp_system.fibers[0]
        previous = fiber.node_attachments_json
        with self.assertRaisesRegex(ValueError, 'Cyclic'):
            set_supports(owner, bpy.context.scene, fiber, (parent,))
        self.assertFalse(fiber.attachment_supports)
        self.assertEqual(previous, fiber.node_attachments_json)

    def test_referenced_parent_deletion_reports_child(self):
        from anthroforge.app.use_cases.vcp_delete import _consumer_error
        owner, muscle, surface, parent = parent_fixture()
        fiber, _points = bound_fiber(owner, surface, parent)
        self.assertIn(fiber.id, _consumer_error(owner, 'MUSCLE', muscle.id))

    def test_typed_parent_round_trip_and_mesh_resolution(self):
        owner, _muscle, surface, parent = parent_fixture()
        self.assertEqual(reference(parent), from_object(surface))
        self.assertEqual(bindings._parent_mesh(owner, bpy.context.scene, parent), surface)
        point = surface.matrix_world @ surface.data.vertices[0].co
        raw = bindings.capture_attachment_from_world(owner, bpy.context.scene, parent, point)
        resolved = bindings.resolve_attachment_world(owner, bpy.context.scene, parent, raw)
        self.assertLess((resolved - point).length, 1e-5)
        self.assertTrue(json.loads(raw)['topology_signature'])

    def test_muscle_deformation_preserves_binding_coordinates(self):
        owner, _muscle, surface, parent = parent_fixture()
        point = surface.matrix_world @ surface.data.vertices[0].co
        raw = bindings.capture_attachment_from_world(owner, bpy.context.scene, parent, point)
        for vertex in surface.data.vertices: vertex.co.z += .125
        surface.data.update(); bpy.context.view_layer.update()
        moved = bindings.resolve_attachment_world(owner, bpy.context.scene, parent, raw)
        self.assertAlmostEqual(moved.z - point.z, .125, places=5)

    def test_topology_change_invalidates_binding(self):
        owner, _muscle, surface, parent = parent_fixture()
        raw = bindings.capture_attachment_from_world(owner, bpy.context.scene, parent, Vector())
        surface.data.clear_geometry(); surface.data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        surface.data.update(); bpy.context.view_layer.update()
        self.assertIsNone(bindings.resolve_attachment_world(owner, bpy.context.scene, parent, raw))

    def test_node_capture_uses_selected_muscle_supports(self):
        owner, _muscle, surface, parent = parent_fixture()
        fiber, points = bound_fiber(owner, surface, parent)
        result = capture_fiber_node_attachments(owner, bpy.context.scene, fiber, points)
        self.assertTrue(result.ok, result.error)
        data = json.loads(fiber.node_attachments_json)
        self.assertEqual(data['version'], 3)
        self.assertEqual({row['target_id'] for row in data['nodes']}, {parent})

    def test_native_batch_resolves_retained_muscle_bindings(self):
        from anthroforge.core.visualization.muscle_fiber_attachment import resolve_batch
        owner, _muscle, surface, parent = parent_fixture()
        fiber, points = bound_fiber(owner, surface, parent)
        self.assertTrue(capture_fiber_node_attachments(owner, bpy.context.scene, fiber, points).ok)
        raw = fiber.node_attachments_json
        for vertex in surface.data.vertices: vertex.co.z += .125
        surface.data.update(); bpy.context.view_layer.update()
        resolved, errors = resolve_batch(owner, bpy.context.scene, (fiber,))
        self.assertFalse(errors, errors)
        self.assertEqual(raw, fiber.node_attachments_json)
        for previous, current in zip(points, resolved[fiber.id]):
            self.assertLess((current - previous - Vector((0, 0, .125))).length, 1e-5)
