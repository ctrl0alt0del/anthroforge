from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(HERE), str(ADDON_ROOT.parent)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bmesh
import bpy
from mathutils import Matrix

from _helpers import BlenderTestCase, empty_object, mesh_object, reset_scene, root, select_only
from anthroforge.app.queries.action_library import quick_hook_panel_state
from anthroforge.app.use_cases.action_library_quick_hook import commit_quick_hook, quick_hook_draft
from anthroforge.core.action_library_quick_hook import clear_quick_hook_sessions, reusable_quick_hook
from anthroforge.core.scp_runtime.bound_objects import find_bound_entry_by_object
from anthroforge.core.scp_runtime.object_roles import create_scp, set_scp_geometry_object, set_scp_transform_object
from anthroforge.operators.action_library_quick_hook import _adjust_draft, _cycle_falloff


def _bind_for_hook(obj):
    root_obj = root()
    scp = create_scp(root_obj, "Eye")
    transform = empty_object("EyeSCP")
    set_scp_transform_object(root_obj, scp, transform)
    set_scp_geometry_object(root_obj, scp, obj)
    return root_obj, scp, transform


def _select_mesh(obj, indices):
    select_only(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    mesh = bmesh.from_edit_mesh(obj.data)
    mesh.verts.ensure_lookup_table()
    for face in mesh.faces:
        face.select = False
    for edge in mesh.edges:
        edge.select = False
    for vert in mesh.verts:
        vert.select = vert.index in set(indices)
    bmesh.update_edit_mesh(obj.data)


def _curve_object(name, spline_type="NURBS", data_type="CURVE"):
    data = bpy.data.curves.new(name, data_type)
    data.dimensions = "3D"
    spline = data.splines.new(spline_type)
    _fill_spline(spline, spline_type, data_type)
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _fill_spline(spline, spline_type, data_type):
    if spline_type == "BEZIER":
        spline.bezier_points.add(2)
        for index, point in enumerate(spline.bezier_points):
            point.co = (float(index), float(index % 2), 0.0)
        return
    spline.points.add(3 if data_type == "SURFACE" else 2)
    for index, point in enumerate(spline.points):
        point.co = (float(index % 2), float(index // 2), 0.0, 1.0)
    spline.order_u = 2


def _lattice_object():
    data = bpy.data.lattices.new("HookLattice")
    obj = bpy.data.objects.new("HookLattice", data)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _select_first_point(obj):
    select_only(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    if obj.type == "MESH":
        return _select_mesh_edit(obj)
    if obj.type in {"CURVE", "SURFACE"}:
        return _select_curve_edit(obj)
    obj.data.points[0].select = True


def _select_mesh_edit(obj):
    mesh = bmesh.from_edit_mesh(obj.data)
    for face in mesh.faces:
        face.select = False
    for edge in mesh.edges:
        edge.select = False
    for vert in mesh.verts:
        vert.select = vert.index == 0
    bmesh.update_edit_mesh(obj.data)


def _select_curve_edit(obj):
    spline = obj.data.splines[0]
    for point in spline.points:
        point.select = False
    for point in spline.bezier_points:
        point.select_left_handle = point.select_control_point = point.select_right_handle = False
    if spline.type == "BEZIER":
        spline.bezier_points[0].select_control_point = True
    else:
        spline.points[0].select = True


def _hook_modifiers(obj):
    return [modifier for modifier in obj.modifiers if modifier.type == "HOOK"]


def _native_hook_result(factory):
    obj = factory()
    _root, _scp, _transform = _bind_for_hook(obj)
    _select_first_point(obj)
    draft, error = quick_hook_draft(bpy.context)
    ok, commit_error = commit_quick_hook(bpy.context, draft)
    return obj, draft, error, ok, commit_error


def _round_vector(value):
    return tuple(round(float(cell), 5) for cell in value)


class QuickHookTests(BlenderTestCase):
    def setUp(self):
        super().setUp()
        clear_quick_hook_sessions()

    def test_mesh_hook_is_named_bound_marked_and_keeps_edit_mode(self):
        obj, scp, transform = self._mesh_fixture()
        draft, error = quick_hook_draft(bpy.context)
        ok, commit_error = commit_quick_hook(bpy.context, draft)
        modifier = _hook_modifiers(obj)[0]
        control = modifier.object
        self.assertEqual((error, ok, commit_error), ("", True, ""))
        self.assertEqual((control.name, modifier.name), ("EyeSCP_Hook_01", "AF Hook EyeSCP_Hook_01"))
        self.assertTrue(control.get("af_scp_control") and control.get("af_scp_bound"))
        self.assertEqual((control.get("af_scp_id"), control.get("af_control_lifecycle")), (scp.id, "PERSISTENT"))
        self.assertEqual(_round_vector(control.color), _round_vector(scp.color))
        self.assertEqual((control.parent, bpy.context.active_object, bpy.context.mode), (transform, obj, "EDIT_MESH"))
        self.assertIsNotNone(find_bound_entry_by_object(scp, control))

    def _mesh_fixture(self):
        obj = mesh_object("EyeGeometry")
        root_obj, scp, transform = _bind_for_hook(obj)
        transform.matrix_world = Matrix.Translation((2.0, 3.0, 4.0))
        _select_mesh(obj, (0, 1))
        return obj, scp, transform

    def test_mesh_inference_and_world_target_are_correct(self):
        obj, _scp, _transform = self._mesh_fixture()
        draft, _error = quick_hook_draft(bpy.context)
        expected_world = obj.matrix_world @ draft.center
        ok, error = commit_quick_hook(bpy.context, draft)
        modifier = _hook_modifiers(obj)[0]
        self.assertEqual((ok, error, tuple(modifier.vertex_indices)), (True, "", (0, 1)))
        self.assertEqual(_round_vector(modifier.object.matrix_world.translation), _round_vector(expected_world))
        self.assertAlmostEqual(draft.radius, 0.625)
        self.assertEqual((modifier.strength, modifier.falloff_type), (1.0, "SMOOTH"))

    def test_reuse_adds_layer_without_control_or_bound_entry(self):
        obj, scp, _transform = self._mesh_fixture()
        first, _error = quick_hook_draft(bpy.context)
        commit_quick_hook(bpy.context, first)
        prototype, control = _hook_modifiers(obj)[0], _hook_modifiers(obj)[0].object
        prototype.falloff_radius, prototype.strength, prototype.falloff_type = 2.5, 0.35, "LINEAR"
        bound_count, object_count = len(scp.bound_objects), len(bpy.data.objects)
        _select_mesh(obj, (2,))
        second, error = quick_hook_draft(bpy.context)
        ok, commit_error = commit_quick_hook(bpy.context, second)
        self._assert_reuse(obj, scp, control, prototype, bound_count, object_count)
        self.assertEqual((error, ok, commit_error), ("", True, ""))

    def _assert_reuse(self, obj, scp, control, prototype, bound_count, object_count):
        layers = _hook_modifiers(obj)
        self.assertEqual((len(layers), len(scp.bound_objects), len(bpy.data.objects)), (2, bound_count, object_count))
        self.assertIs(layers[-1].object, control)
        self.assertEqual(tuple(layers[-1].vertex_indices), (2,))
        self.assertEqual((layers[-1].falloff_radius, layers[-1].falloff_type), (2.5, "LINEAR"))
        self.assertAlmostEqual(layers[-1].strength, 0.35)
        self.assertEqual(tuple(layers[-1].center), tuple(prototype.center))
        self.assertEqual(tuple(map(tuple, layers[-1].matrix_inverse)), tuple(map(tuple, prototype.matrix_inverse)))

    def test_invalid_reuse_cache_creates_a_new_control(self):
        obj, _scp, _transform = self._mesh_fixture()
        first, _error = quick_hook_draft(bpy.context)
        commit_quick_hook(bpy.context, first)
        old = _hook_modifiers(obj)[0].object
        bpy.data.objects.remove(old, do_unlink=True)
        _select_mesh(obj, (2,))
        draft, error = quick_hook_draft(bpy.context)
        ok, commit_error = commit_quick_hook(bpy.context, draft)
        self.assertIsNone(draft.reuse)
        self.assertEqual((error, ok, commit_error), ("", True, ""))
        self.assertIsNotNone(_hook_modifiers(obj)[-1].object)
        self.assertIsNotNone(reusable_quick_hook(bpy.context.scene, obj, draft.scp_id))

    def test_failure_rolls_back_modifier_control_and_bound_entry(self):
        obj, scp, _transform = self._mesh_fixture()
        draft, _error = quick_hook_draft(bpy.context)
        counts = len(obj.modifiers), len(scp.bound_objects), len(bpy.data.objects)
        target = "anthroforge.app.use_cases.action_library_quick_hook.sync_context"
        with patch(target, side_effect=RuntimeError("forced sync failure")):
            ok, error = commit_quick_hook(bpy.context, draft)
        self.assertFalse(ok)
        self.assertIn("forced sync failure", error)
        self.assertEqual((len(obj.modifiers), len(scp.bound_objects), len(bpy.data.objects)), counts)

    def test_panel_state_guides_invalid_and_reuse_contexts(self):
        self.assertFalse(quick_hook_panel_state(bpy.context).can_create)
        obj, _scp, _transform = self._mesh_fixture()
        state = quick_hook_panel_state(bpy.context)
        self.assertTrue(state.can_create)
        self.assertEqual(state.button_text, "Create Quick Hook")
        draft, _error = quick_hook_draft(bpy.context)
        commit_quick_hook(bpy.context, draft)
        _select_mesh(obj, (2,))
        state = quick_hook_panel_state(bpy.context)
        self.assertEqual((state.button_text, state.reuse_target), ("Add Hook Layer", "EyeSCP_Hook_01"))

    def test_panel_rejects_generated_mirror_and_empty_selection(self):
        obj, _scp, _transform = self._mesh_fixture()
        obj["af_scp_mirror"] = True
        state = quick_hook_panel_state(bpy.context)
        self.assertFalse(state.can_create)
        self.assertIn("generated mirrors", state.message)
        del obj["af_scp_mirror"]
        bpy.ops.mesh.select_all(action="DESELECT")
        state = quick_hook_panel_state(bpy.context)
        self.assertFalse(state.can_create)
        self.assertIn("Select at least one", state.message)

    def test_registered_operator_dispatches_one_dirty_sync(self):
        obj, _scp, _transform = self._mesh_fixture()
        target = "anthroforge.app.use_cases.action_library_quick_hook.sync_context"
        with patch(target) as sync:
            result = bpy.ops.af.quick_scp_hook("EXEC_DEFAULT")
        self.assertEqual(result, {"FINISHED"})
        self.assertEqual(len(_hook_modifiers(obj)), 1)
        sync.assert_called_once()

    def test_modal_adjustment_clamps_and_cycles_falloff(self):
        draft = SimpleNamespace(radius=1.0, strength=0.5, pixel_scale=0.01, falloff="SMOOTH")
        _adjust_draft(draft, (0, 0), (-200, 300))
        self.assertEqual((draft.radius, draft.strength), (0.0, 1.0))
        operator = SimpleNamespace(_quick_hook_draft=draft)
        _cycle_falloff(operator, True)
        self.assertEqual(draft.falloff, "LINEAR")
        _cycle_falloff(operator, False)
        self.assertEqual(draft.falloff, "SMOOTH")

    def test_native_hook_supports_all_editable_scp_geometry_types(self):
        factories = self._geometry_factories()
        for label, factory in factories:
            with self.subTest(object_type=label):
                reset_scene()
                clear_quick_hook_sessions()
                obj, draft, error, ok, commit_error = _native_hook_result(factory)
                self.assertEqual((error, ok, commit_error), ("", True, ""))
                self.assertGreater(len(_hook_modifiers(obj)[0].vertex_indices), 0)
                self.assertEqual((bpy.context.active_object, obj.mode), (obj, "EDIT"))
                self.assertIsNone(quick_hook_draft(bpy.context)[0])

    def _geometry_factories(self):
        return (
            ("Mesh", lambda: mesh_object("HookMesh")),
            ("Lattice", _lattice_object),
            ("Poly Curve", lambda: _curve_object("HookPoly", "POLY")),
            ("NURBS Curve", lambda: _curve_object("HookNurbs", "NURBS")),
            ("Bezier Curve", lambda: _curve_object("HookBezier", "BEZIER")),
            ("NURBS Surface", lambda: _curve_object("HookSurface", "NURBS", "SURFACE")),
        )


if __name__ == "__main__":
    unittest.main(argv=["test_quick_hook"])
