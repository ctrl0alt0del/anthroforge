"""AF-24 review regressions against live outputs, scenes and allocations."""
from unittest.mock import patch
import bpy
from mathutils import Vector
from _helpers import BlenderTestCase, select_only
from _branch_fixture import create_fixture
from test_free_fibers import fixture
from test_free_loops import loop_fixture
from anthroforge.adapters import free_fiber_editor as editor
from anthroforge.adapters.authoring.capture import native_records
from anthroforge.adapters.free_fiber_transaction import _owned, _custom
from anthroforge.app.use_cases import free_fiber as service
from anthroforge.core.vcp.prop_update_guard import suppress_vcp_prop_updates
from anthroforge.core.visualization.fiber_surface_sync import register_fiber_surface_sync, evaluate_surface_record
from anthroforge.app.use_cases.fiber_surface_create import _new_surface, _assign_refs


def patch_fixture():
    root, _bone, fiber, points = loop_fixture()
    with suppress_vcp_prop_updates():
        surface = _new_surface(root.af_vcp_system, 'Review patch', 'LOOP_PATCH', False, False)
        _assign_refs(surface, [fiber.id]); surface.patch_resolution = 2
    register_fiber_surface_sync().sync_root_to_scene(root, bpy.context.scene)
    return root, fiber, surface, points


def output_state(root):
    rows = {obj.name: (geometry(obj), _custom(obj), tuple(tuple(r) for r in obj.matrix_world))
            for obj in _owned(root, bpy.context.scene)}
    runtime = {name: {item.id: {k: item[k] for k in item.keys() if k.startswith('_af_rt_')}
                     for item in getattr(root.af_vcp_system, name)} for name in ('fibers', 'fiber_surfaces', 'muscles')}
    return dict(records=native_records(root), geometry=rows, runtime=runtime)


def geometry(obj):
    if obj.type == 'MESH': return ([tuple(v.co) for v in obj.data.vertices], [tuple(p.vertices) for p in obj.data.polygons])
    if obj.type == 'CURVE': return [[tuple(p.co) for p in spline.points] for spline in obj.data.splines]
    return None


def free_fixture():
    root, _bone, fiber, _points = fixture()
    service.configure_mode(root, bpy.context.scene, fiber, 'FREE')
    return root, fiber


def allocated():
    return {kind: {item.name for item in getattr(bpy.data, kind)} for kind in ('objects', 'curves')}


class FreeReviewTests(BlenderTestCase):
    def test_self_intersecting_patch_rolls_back_records_meshes_status_and_keeps_draft(self):
        root, fiber, surface, points = patch_fixture(); before = output_state(root)
        drafts = editor.open_edit(root, bpy.context.scene, fiber)
        editor._poly(drafts[0].data, [points[0], Vector((.3, .7, 0)), points[1]])
        draft = editor.draft(root, fiber)
        with self.assertRaisesRegex(ValueError, 'self-intersects'): editor.apply(root, bpy.context.scene, fiber)
        self.assertEqual(output_state(root), before); self.assertEqual(editor.draft(root, fiber), draft)
        self.assertTrue(editor.state(root, fiber)); self.assertTrue(evaluate_surface_record(root, bpy.context.scene, surface).faces)

    def test_branch_junction_failure_restores_source_surfaces_base_and_inflation(self):
        root, muscle, _connection, fibers = create_fixture(); fiber = fibers[2]
        service.configure_mode(root, bpy.context.scene, fiber, 'FREE'); before = output_state(root)
        self.assertTrue(any(obj.get('af_muscle_surface') == 'INFL' for obj in _owned(root, bpy.context.scene)))
        drafts = editor.open_edit(root, bpy.context.scene, fiber)
        drafts[0].data.splines[0].points[0].co.x += 5e-6
        draft = editor.draft(root, fiber)
        with self.assertRaisesRegex(ValueError, 'shared solved main point'): editor.apply(root, bpy.context.scene, fiber)
        self.assertEqual(output_state(root), before); self.assertEqual(editor.draft(root, fiber), draft)

    def test_hidden_collection_is_reenabled_in_active_view_layer(self):
        root, fiber = free_fixture(); scene = bpy.context.scene
        editor.open_edit(root, scene, fiber); editor.cancel(root, fiber)
        collection = editor._collection(scene); collection.hide_viewport = collection.hide_select = True
        layer = next(c for c in bpy.context.view_layer.layer_collection.children if c.collection == collection)
        layer.exclude = layer.hide_viewport = True
        obj = editor.open_edit(root, scene, fiber)[0]; select_only(obj)
        self.assertTrue(obj.visible_get()); self.assertEqual(bpy.ops.object.mode_set(mode='EDIT'), {'FINISHED'})
        bpy.ops.object.mode_set(mode='OBJECT'); editor.cancel(root, fiber)

    def test_scene_owned_drafts_support_edit_mode_without_cross_scene_leaks(self):
        first, fiber = free_fixture(); scene_a = bpy.context.scene
        editor.open_edit(first, scene_a, fiber); editor.cancel(first, fiber)
        scene_b = bpy.data.scenes.new('Other editor scene'); bpy.context.window.scene = scene_b
        second, other = free_fixture(); obj_b = editor.open_edit(second, scene_b, other)[0]
        select_only(obj_b); self.assertEqual(bpy.ops.object.mode_set(mode='EDIT'), {'FINISHED'})
        bpy.ops.object.mode_set(mode='OBJECT'); self.assertNotIn(obj_b.name, scene_a.objects)
        bpy.context.window.scene = scene_a; obj_a = editor.open_edit(first, scene_a, fiber)[0]
        self.assertNotIn(obj_a.name, scene_b.objects); self.assertNotEqual(obj_a.users_collection, obj_b.users_collection)
        self.assertIn(obj_a.name, bpy.context.view_layer.objects)
        editor.cancel(first, fiber); editor.cancel(second, other)

    def test_singular_root_open_rejects_without_allocating_objects_or_curves(self):
        root, fiber = free_fixture(); root.scale.x = 0; bpy.context.view_layer.update(); before = allocated()
        with self.assertRaisesRegex(ValueError, 'Noninvertible'): editor.open_edit(root, bpy.context.scene, fiber)
        self.assertEqual(allocated(), before); self.assertIsNone(editor.state(root, fiber))
        editor.cancel(root, fiber); self.assertEqual(allocated(), before)

    def test_later_span_failure_cleans_all_prior_and_partial_allocations(self):
        root, _bone, fiber, _points = loop_fixture(); before = allocated(); original = editor._poly; calls = []
        def fail_second(curve, points):
            calls.append(curve.name)
            if len(calls) == 2: raise RuntimeError('Second span allocation failure')
            original(curve, points)
        with patch.object(editor, '_poly', side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError, 'Second span'): editor.open_edit(root, bpy.context.scene, fiber)
        self.assertEqual(len(calls), 2); self.assertEqual(allocated(), before); self.assertIsNone(editor.state(root, fiber))

    def test_state_write_failure_cleans_fully_allocated_session(self):
        root, fiber = free_fixture(); before = allocated()
        with patch.object(editor, 'save_state', side_effect=RuntimeError('Session write failure')):
            with self.assertRaisesRegex(RuntimeError, 'Session write'): editor.open_edit(root, bpy.context.scene, fiber)
        self.assertEqual(allocated(), before); self.assertIsNone(editor.state(root, fiber))
