from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(HERE), str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy

from _helpers import BlenderTestCase, root
from anthroforge.core.action_library_split_corner import (
    _curve_frame,
    _forward_axis,
    _roll_delta,
    _split_reference_frames,
    split_corner,
    split_corner_spec,
)
from anthroforge.core.scp_runtime.object_roles import create_scp, set_scp_geometry_object, set_scp_transform_object
from anthroforge.core.scp_runtime.prop_update_guard import set_parent_id_raw
from anthroforge.core.scp_runtime.common import set_prop_raw
from anthroforge.core.scp_runtime.object_colors import apply_object_color


def _mesh_strip(name):
    mesh = bpy.data.meshes.new(name)
    verts = [(0, -0.2, 0), (0, 0.2, 0.15), (6, -0.2, 0), (6, 0.2, 0.15)]
    mesh.from_pydata(verts, [], [(0, 1, 3, 2)])
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _curve_object():
    curve = bpy.data.curves.new("SplitCurve", "CURVE")
    curve.dimensions, curve.resolution_u = "3D", 16
    spline = curve.splines.new("BEZIER")
    spline.bezier_points.add(3)
    vals = (
        ((0, 0, 0), (-0.6, 0, 0), (0.8, 0.2, 0.5)),
        ((2, 0.5, 1.0), (1.2, -0.4, 0.8), (2.8, 0.8, 1.5)),
        ((4, 1.0, -0.5), (3.2, 1.4, -1.1), (4.8, 0.6, 0.2)),
        ((6, 0.2, 1.5), (5.4, 0.8, 1.1), (6.8, -0.2, 2.0)),
    )
    for point, (co, left, right) in zip(spline.bezier_points, vals):
        _set_bezier_point(point, co, left, right)
    obj = bpy.data.objects.new("SplitCurveObj", curve)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _set_bezier_point(point, co, left, right):
    point.co, point.handle_left, point.handle_right = co, left, right
    point.handle_left_type, point.handle_right_type = "FREE", "FREE"


def _split_fixture():
    root_obj = root()
    parent = create_scp(root_obj, "Parent")
    parent_obj = bpy.data.objects.new("ParentXform", None)
    bpy.context.scene.collection.objects.link(parent_obj)
    set_scp_transform_object(root_obj, parent, parent_obj)
    curve_obj, geo = _curve_object(), _mesh_strip("SplitGeo")
    geo.modifiers.new("Curve", "CURVE").object = curve_obj
    source = create_scp(root_obj, "Source")
    set_scp_transform_object(root_obj, source, curve_obj)
    set_scp_geometry_object(root_obj, source, geo)
    set_parent_id_raw(source, parent.id)
    return source, curve_obj


def _select_split_point(curve_obj, index):
    for point in curve_obj.data.splines[0].bezier_points:
        point.select_control_point = False
    curve_obj.data.splines[0].bezier_points[index].select_control_point = True
    bpy.context.view_layer.objects.active = curve_obj
    curve_obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")


class SplitCornerTests(BlenderTestCase):
    def test_split_corner_applies_uniform_child_tilt_offset(self):
        _source, curve_obj = _split_fixture()
        _select_split_point(curve_obj, 1)
        spec, error = split_corner_spec(bpy.context)
        refs = _split_reference_frames(spec)
        result, error = split_corner(bpy.context)
        self.assertEqual((spec is not None, error), (True, ""))
        self.assertEqual(len(result["clone_scps"]), 1)
        child_curve = result["clone_scps"][0].transform_object_ref
        tangent, normal = _curve_frame(bpy.context.scene, child_curve, 0.0, _forward_axis(spec))
        ref_tangent, ref_normal = refs[0]
        tilts = [round(float(point.tilt), 4) for point in child_curve.data.splines[0].bezier_points]
        self.assertTrue(any(abs(value) > 1.0e-4 for value in tilts))
        self.assertEqual(len(set(tilts)), 1)
        self.assertAlmostEqual(_roll_delta(normal, ref_normal, tangent if tangent.length > 1.0e-9 else ref_tangent), 0.0, places=4)

    def test_split_corner_restores_visible_source_color_to_clone(self):
        source, curve_obj = _split_fixture()
        color = (0.2, 0.7, 0.35, 1.0)
        set_prop_raw(source, "color", (0.0, 0.0, 0.0, 1.0))
        set_prop_raw(source, "color_initialized", False)
        apply_object_color(curve_obj, color)
        apply_object_color(source.geometry_object_ref, color)
        _select_split_point(curve_obj, 1)
        result, error = split_corner(bpy.context)
        child = result["clone_scps"][0]
        self.assertEqual(error, "")
        self.assertEqual(tuple(round(v, 4) for v in child.color), color)
        self.assertEqual(tuple(round(v, 4) for v in child.geometry_object_ref.color), color)


if __name__ == "__main__":
    unittest.main(argv=["test_split_corner"])
