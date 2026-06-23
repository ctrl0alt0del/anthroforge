from pathlib import Path
import sys
from math import pi

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy

from _helpers import BlenderTestCase, add_shortcut, empty_object, mesh_object, root, scp_with_object, select_only
from core.scp_runtime.bound_objects import iter_bound_objects, sync_scp_roles
from core.scp_runtime.common import find_scp_by_id, set_prop_raw
from core.scp_runtime.object_roles import add_bound_object_to_scp
from core.local_transform_props import local_transform_keys

_CURVE_GROUP = "AF_CurveGroup_v1"
_LOFT_GROUP = "AF_LoftTwoCurves_v1"


def _round_xyz(obj):
    return tuple(round(float(value), 4) for value in obj.location)


def _interface_sockets(group, in_out):
    items = tuple(group.interface.items_tree)
    return [item.name for item in items if getattr(item, "item_type", "") == "SOCKET" and getattr(item, "in_out", "") == in_out]


def _socket_subtype(group, name):
    items = tuple(group.interface.items_tree)
    item = next(item for item in items if getattr(item, "name", "") == name)
    return str(getattr(item, "subtype", "") or "")


def _group_nodes_by_tree(group, name):
    return [node for node in group.nodes if getattr(getattr(node, "node_tree", None), "name", "") == name]


def _socket_by_name(sockets, name):
    return next(sock for sock in sockets if sock.name == name)


def _factor_source(node):
    socket = next(sock for sock in node.inputs if sock.name == "Factor")
    return tuple(socket.links)[0].from_node.name


def _curve_circle(name, location):
    _ = name
    bpy.ops.curve.primitive_bezier_circle_add(location=location)
    return bpy.context.active_object


def _curve_path(name, coords):
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions, curve.bevel_depth = "3D", 0.02
    spline = curve.splines.new("BEZIER")
    spline.bezier_points.add(len(coords) - 1)
    for index, co in enumerate(coords):
        _set_bezier_point(spline.bezier_points[index], co)
    obj = bpy.data.objects.new(name, curve)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _vector_passthrough_group(name):
    group = bpy.data.node_groups.new(name, "GeometryNodeTree")
    group.interface.new_socket(name="Value", in_out="INPUT", socket_type="NodeSocketVector")
    group.interface.new_socket(name="Value", in_out="OUTPUT", socket_type="NodeSocketVector")
    group.links.new(_socket_by_name(group.nodes.new("NodeGroupOutput").inputs, "Value"), _socket_by_name(group.nodes.new("NodeGroupInput").outputs, "Value"))
    return group


def _insert_custom_curve_helper_node(helper, custom):
    sample, local = helper.nodes["Sample Curve"], helper.nodes["To Local"]
    node = helper.nodes.new("GeometryNodeGroup")
    node.name, node.node_tree = "Custom Bridge", custom
    helper.links.remove(next(link for link in tuple(helper.links) if link.from_node == sample and link.to_node == local))
    helper.links.new(_socket_by_name(node.inputs, "Value"), _socket_by_name(sample.outputs, "Value"))
    helper.links.new(_socket_by_name(local.inputs, "Vector"), _socket_by_name(node.outputs, "Value"))
    return node


def _set_bezier_point(point, co):
    point.co = co
    point.handle_left = (co[0] - 0.25, co[1], co[2])
    point.handle_right = (co[0] + 0.25, co[1], co[2])
    point.handle_left_type = "FREE"
    point.handle_right_type = "FREE"


def _socket_keys(mod):
    keys = [key for key in mod.keys() if str(key).startswith("Socket_")]
    keys = [key for key in keys if not str(key).endswith("_use_attribute")]
    keys = [key for key in keys if not str(key).endswith("_attribute_name")]
    return sorted(keys, key=lambda item: int(str(item).split("_")[1]))


def _bounds(obj):
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(deps)
    mesh = eval_obj.to_mesh()
    coords = [vert.co[:] for vert in mesh.vertices]
    mins = tuple(min(axis) for axis in zip(*coords))
    maxs = tuple(max(axis) for axis in zip(*coords))
    eval_obj.to_mesh_clear()
    return mins, maxs


def _bounds_world(obj):
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(deps)
    mesh = eval_obj.to_mesh()
    coords = [tuple(obj.matrix_world @ vert.co) for vert in mesh.vertices]
    eval_obj.to_mesh_clear()
    return tuple(min(axis) for axis in zip(*coords)), tuple(max(axis) for axis in zip(*coords))


def _split_fixture():
    root_obj = root()
    parent = scp_with_object(root_obj, "Parent", empty_object("Parent"), with_geometry=False)
    geo = mesh_object("ChildGeo")
    child = scp_with_object(root_obj, "Child", geo)
    set_prop_raw(child, "parent_id", parent.id)
    curve_obj = _curve_path("ChildCurve", [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)])
    add_bound_object_to_scp(root_obj, child, curve_obj)
    sync_scp_roles(root_obj, child)
    geo.modifiers.new("CurvePath", "CURVE").object = curve_obj
    return root_obj, parent, child, geo, curve_obj


def _select_curve_point(curve_obj, index):
    select_only(curve_obj)
    bpy.ops.object.mode_set(mode="EDIT")
    for point in curve_obj.data.splines[0].bezier_points:
        point.select_left_handle = point.select_control_point = point.select_right_handle = False
    curve_obj.data.splines[0].bezier_points[index].select_control_point = True


def _bound_curve(scp):
    return next(obj for _entry, obj in iter_bound_objects(scp) if obj.type == "CURVE")


def _hook_mod(obj):
    return next(mod for mod in obj.modifiers if str(getattr(mod, "type", "")) == "HOOK")


def _extra_scps(root_obj, count):
    for index in range(count):
        scp_with_object(root_obj, f"Extra{index}", empty_object(f"Extra{index}"), with_geometry=False)


def _split_control(parent_id):
    return next(obj for obj in bpy.context.scene.objects if obj.get("af_scp_control") and obj.get("af_scp_id") == parent_id)


def _round_vec(vec):
    return tuple(round(float(value), 4) for value in vec)


def _assert_split_result(case, root_obj, parent_id, geo, curve_obj, expected_total, expected_world):
    parent = find_scp_by_id(root_obj, parent_id)
    clone = root_obj.af_scp_system.scps[-1]
    curve_clone, control = _bound_curve(clone), _split_control(parent_id)
    case.assertEqual((len(root_obj.af_scp_system.scps), clone.parent_id), (expected_total, parent_id))
    case.assertIsNot(clone.geometry_object_ref, geo)
    case.assertEqual((geo.modifiers["CurvePath"].object, clone.geometry_object_ref.modifiers["CurvePath"].object), (curve_obj, curve_clone))
    case.assertEqual((len(curve_obj.data.splines[0].bezier_points), len(curve_clone.data.splines[0].bezier_points)), (2, 2))
    case.assertEqual(tuple(curve_obj.data.splines[0].bezier_points[-1].co), tuple(curve_clone.data.splines[0].bezier_points[0].co))
    case.assertEqual(tuple(curve_obj.data.splines[0].bezier_points[-1].handle_right), tuple(curve_obj.data.splines[0].bezier_points[-1].co))
    case.assertEqual(tuple(curve_clone.data.splines[0].bezier_points[0].handle_left), tuple(curve_clone.data.splines[0].bezier_points[0].co))
    case.assertEqual((_hook_mod(curve_obj).object, _hook_mod(curve_clone).object), (control, control))
    case.assertEqual((tuple(_hook_mod(curve_obj).vertex_indices), tuple(_hook_mod(curve_clone).vertex_indices)), ((3, 4, 5), (0, 1, 2)))
    case.assertEqual(_round_vec(control.matrix_world.translation), _round_vec(expected_world))
    case.assertIn(control, [obj for _entry, obj in iter_bound_objects(parent)])
    case.assertEqual((bpy.context.active_object, bpy.context.mode), (control, "OBJECT"))


class ActionLibraryTests(BlenderTestCase):
    def test_create_local_transform_props_drives_location_in_local_space(self):
        obj = empty_object("Guide")
        obj.rotation_euler.z = pi / 2.0
        select_only(obj)
        self.assertEqual(bpy.ops.af.create_local_transform_props(), {"FINISHED"})
        obj[local_transform_keys()[0]] = 2.0
        obj.update_tag()
        bpy.context.view_layer.update()
        self.assertEqual(_round_xyz(obj), (0.0, 2.0, 0.0))

    def test_shortcut_can_drive_local_transform_property(self):
        root_obj = root()
        scp = scp_with_object(root_obj, "Guide", empty_object("Guide"), with_geometry=False)
        scp.transform_object_ref.rotation_euler.z = pi / 2.0
        select_only(scp.transform_object_ref)
        self.assertEqual(bpy.ops.af.create_local_transform_props(), {"FINISHED"})
        path = f'bpy.data.objects["{scp.transform_object_ref.name}"]["{local_transform_keys()[0]}"]'
        shortcut = add_shortcut(root_obj, "Local X", "SCP", scp.id, path)
        shortcut.proxy_float = 2.0
        bpy.context.view_layer.update()
        self.assertEqual(_round_xyz(scp.transform_object_ref), (0.0, 2.0, 0.0))

    def test_remove_local_transform_props_preserves_current_location(self):
        obj = empty_object("Guide")
        obj.rotation_euler.z = pi / 2.0
        select_only(obj)
        bpy.ops.af.create_local_transform_props()
        obj[local_transform_keys()[0]] = 2.0
        obj.update_tag()
        bpy.context.view_layer.update()
        self.assertEqual(_round_xyz(obj), (0.0, 2.0, 0.0))
        self.assertEqual(bpy.ops.af.remove_local_transform_props(), {"FINISHED"})
        self.assertEqual(_round_xyz(obj), (0.0, 2.0, 0.0))
        self.assertFalse(any(key in obj for key in local_transform_keys()))
        self.assertIsNone(next((fc for fc in tuple(getattr(getattr(obj, "animation_data", None), "drivers", ()) or ()) if fc.data_path == "location"), None))

    def test_create_curve_loft_group_builds_requested_interface(self):
        scene = bpy.context.scene
        scene.af_action_gn_name = "GeneratedLoft"
        scene.af_action_curve_count = 4
        scene.af_action_single_angle = False
        self.assertEqual(bpy.ops.af.create_curve_loft_group(), {"FINISHED"})
        group = bpy.data.node_groups["GeneratedLoft"]
        self.assertTrue(group.is_modifier)
        self.assertEqual(_interface_sockets(group, "OUTPUT"), ["Geometry"])
        self.assertEqual(_interface_sockets(group, "INPUT"), ["Geometry", "Curve 01", "Curve 02", "Curve 03", "Curve 04", "Resolution", "Angle 01", "Angle 02", "Angle 03", "Angle 04"])
        curve_nodes = _group_nodes_by_tree(group, _CURVE_GROUP)
        self.assertEqual(len(curve_nodes), 4)
        self.assertEqual(len(_group_nodes_by_tree(group, _LOFT_GROUP)), 3)
        self.assertEqual(_factor_source(curve_nodes[0]), "Angle 01 Factor")
        self.assertEqual(_factor_source(curve_nodes[1]), "Angle 02 Factor")
        self.assertEqual(_factor_source(curve_nodes[2]), "Angle 03 Factor")
        self.assertEqual(_factor_source(curve_nodes[3]), "Angle 04 Factor")
        self.assertEqual(_socket_subtype(group, "Angle 01"), "ANGLE")

    def test_create_curve_loft_group_can_use_single_angle(self):
        scene = bpy.context.scene
        scene.af_action_gn_name = "SingleAngleLoft"
        scene.af_action_curve_count = 3
        scene.af_action_single_angle = True
        self.assertEqual(bpy.ops.af.create_curve_loft_group(), {"FINISHED"})
        group = bpy.data.node_groups["SingleAngleLoft"]
        self.assertEqual(_interface_sockets(group, "INPUT"), ["Geometry", "Curve 01", "Curve 02", "Curve 03", "Resolution", "Angle"])
        curve_nodes = _group_nodes_by_tree(group, _CURVE_GROUP)
        self.assertEqual(len(curve_nodes), 3)
        self.assertTrue(all(_factor_source(node) == "Angle Factor" for node in curve_nodes))
        self.assertEqual(_socket_subtype(group, "Angle"), "ANGLE")

    def test_create_curve_loft_group_reuses_helper_groups(self):
        scene = bpy.context.scene
        scene.af_action_gn_name = "LoftTwo"
        scene.af_action_curve_count = 2
        scene.af_action_single_angle = False
        self.assertEqual(bpy.ops.af.create_curve_loft_group(), {"FINISHED"})
        scene.af_action_gn_name = "LoftFive"
        scene.af_action_curve_count = 5
        scene.af_action_single_angle = False
        self.assertEqual(bpy.ops.af.create_curve_loft_group(), {"FINISHED"})
        self.assertEqual(len([group for group in bpy.data.node_groups if group.name == _CURVE_GROUP]), 1)
        self.assertEqual(len([group for group in bpy.data.node_groups if group.name == _LOFT_GROUP]), 1)
        self.assertEqual(len(_group_nodes_by_tree(bpy.data.node_groups["LoftTwo"], _LOFT_GROUP)), 1)
        self.assertEqual(len(_group_nodes_by_tree(bpy.data.node_groups["LoftFive"], _LOFT_GROUP)), 4)

    def test_create_curve_loft_group_keeps_existing_helper_custom_group_links(self):
        scene = bpy.context.scene
        scene.af_action_gn_name = "LoftBase"
        scene.af_action_curve_count = 2
        scene.af_action_single_angle = False
        self.assertEqual(bpy.ops.af.create_curve_loft_group(), {"FINISHED"})
        helper = bpy.data.node_groups[_CURVE_GROUP]
        helper_ptr = helper.as_pointer()
        _insert_custom_curve_helper_node(helper, _vector_passthrough_group("CurveBridge"))
        scene.af_action_gn_name = "LoftWide"
        scene.af_action_curve_count = 5
        self.assertEqual(bpy.ops.af.create_curve_loft_group(), {"FINISHED"})
        helper = bpy.data.node_groups[_CURVE_GROUP]
        bridge = helper.nodes["Custom Bridge"]
        self.assertEqual((helper.as_pointer(), len(tuple(bridge.inputs["Value"].links)), len(tuple(bridge.outputs["Value"].links))), (helper_ptr, 1, 1))

    def test_create_curve_loft_group_rejects_duplicate_name(self):
        scene = bpy.context.scene
        scene.af_action_gn_name = "RepeatLoft"
        scene.af_action_curve_count = 3
        scene.af_action_single_angle = False
        self.assertEqual(bpy.ops.af.create_curve_loft_group(), {"FINISHED"})
        with self.assertRaisesRegex(RuntimeError, 'Node group "RepeatLoft" already exists.'):
            bpy.ops.af.create_curve_loft_group()

    def test_create_curve_loft_group_overwrite_preserves_modifier_bindings(self):
        scene = bpy.context.scene
        scene.af_action_gn_name = "RewriteLoft"
        scene.af_action_curve_count = 2
        scene.af_action_single_angle = False
        self.assertEqual(bpy.ops.af.create_curve_loft_group(), {"FINISHED"})
        group = bpy.data.node_groups["RewriteLoft"]
        ptr = group.as_pointer()
        host = mesh_object("RewriteHost")
        mod = host.modifiers.new("GeometryNodes", "NODES")
        mod.node_group = group
        keys = _socket_keys(mod)
        curve_a = _curve_circle("CurveA", (0.0, 0.0, 0.0))
        curve_b = _curve_circle("CurveB", (0.0, 0.0, 1.0))
        mod[keys[0]] = curve_a
        mod[keys[1]] = curve_b
        mod[keys[2]] = 32
        scene.af_action_curve_count = 4
        scene.af_action_single_angle = False
        self.assertEqual(bpy.ops.af.create_curve_loft_group(overwrite_existing=True), {"FINISHED"})
        group = bpy.data.node_groups["RewriteLoft"]
        self.assertNotEqual(group.as_pointer(), ptr)
        self.assertEqual(mod.node_group, group)
        self.assertEqual(_interface_sockets(group, "INPUT")[1:5], ["Curve 01", "Curve 02", "Curve 03", "Curve 04"])
        keys = _socket_keys(mod)
        self.assertEqual(mod[keys[0]], curve_a)
        self.assertEqual(mod[keys[1]], curve_b)
        self.assertEqual(mod[keys[4]], 32)

    def test_create_curve_loft_group_evaluates_non_planar_two_curve_loft(self):
        import anthroforge
        bpy.ops.wm.read_factory_settings(use_empty=True)
        if not hasattr(bpy.types.Object, "af_scp_system"):
            anthroforge.register()
        scene = bpy.context.scene
        scene.af_action_gn_name = "EvalLoft"
        scene.af_action_curve_count = 2
        scene.af_action_single_angle = False
        self.assertEqual(bpy.ops.af.create_curve_loft_group(), {"FINISHED"})
        curve_a = _curve_circle("CurveA", (0.0, 0.0, 0.0))
        curve_b = _curve_circle("CurveB", (0.0, 0.0, 1.0))
        host = mesh_object("LoftHost")
        host.location = (3.0, -2.0, 4.0)
        mod = host.modifiers.new("GeometryNodes", "NODES")
        mod.node_group = bpy.data.node_groups["EvalLoft"]
        keys = _socket_keys(mod)
        mod[keys[0]] = curve_a
        mod[keys[1]] = curve_b
        mins, maxs = _bounds_world(host)
        self.assertLess(mins[0], -0.9)
        self.assertGreater(maxs[0], 0.9)
        self.assertGreater(maxs[2] - mins[2], 0.9)

    def test_split_scp_by_corner_creates_clone_and_shared_control(self):
        root_obj, parent, _child, geo, curve_obj = _split_fixture()
        parent_id = parent.id
        expected_total = len(root_obj.af_scp_system.scps) + 1
        expected_world = tuple(curve_obj.matrix_world @ curve_obj.data.splines[0].bezier_points[1].co)
        _select_curve_point(curve_obj, 1)
        self.assertEqual(bpy.ops.af.split_scp_by_corner(), {"FINISHED"})
        _assert_split_result(self, root_obj, parent_id, geo, curve_obj, expected_total, expected_world)

    def test_split_scp_by_corner_rejects_endpoint_selection(self):
        root_obj, _parent, _child, _geo, curve_obj = _split_fixture()
        _select_curve_point(curve_obj, 0)
        with self.assertRaisesRegex(RuntimeError, "Selected point must be an interior point."):
            bpy.ops.af.split_scp_by_corner()
        self.assertEqual((len(root_obj.af_scp_system.scps), bpy.context.mode), (2, "EDIT_CURVE"))

    def test_split_scp_by_corner_survives_extra_scp_collection_growth(self):
        root_obj, parent, _child, geo, curve_obj = _split_fixture()
        parent_id = parent.id
        _extra_scps(root_obj, 6)
        expected_total = len(root_obj.af_scp_system.scps) + 1
        expected_world = tuple(curve_obj.matrix_world @ curve_obj.data.splines[0].bezier_points[1].co)
        _select_curve_point(curve_obj, 1)
        self.assertEqual(bpy.ops.af.split_scp_by_corner(), {"FINISHED"})
        _assert_split_result(self, root_obj, parent_id, geo, curve_obj, expected_total, expected_world)
