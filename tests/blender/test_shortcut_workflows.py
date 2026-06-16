from pathlib import Path
import sys

TEST_ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = Path(__file__).resolve().parents[2]
for value in (str(TEST_ROOT), str(ADDON_ROOT)):
    if value not in sys.path:
        sys.path.insert(0, value)

import bpy

from _helpers import BlenderTestCase, add_shortcut, empty_object, mesh_object, root, scp_with_object, select_only
from core.scp_runtime.attachment_runtime import capture_attachment_from_link
from core.scp_runtime.lookup import set_parent_relation
from core.scp_runtime.runtime_state import attach_parent_param
from core.shortcuts import resolve_shortcut, upsert_override
from core.shortcuts.proxy_props import proxy_prop_name


def _apply_float_shortcut(root_obj, shortcut, value):
    shortcut.proxy_float = value
    return True


def _geometry_nodes_setup(obj):
    group = bpy.data.node_groups.new(f"{obj.name}GN", "GeometryNodeTree")
    _group_sockets(group)
    _group_nodes(group)
    mod = obj.modifiers.new("GeometryNodes", "NODES")
    mod.node_group = group
    bpy.context.view_layer.update()
    return mod, _socket_key(mod)


def _group_sockets(group):
    iface = group.interface
    iface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    iface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    iface.new_socket(name="Offset", in_out="INPUT", socket_type="NodeSocketFloat")


def _group_nodes(group):
    nodes, links = group.nodes, group.links
    nodes.clear()
    in_node = nodes.new("NodeGroupInput")
    out_node = nodes.new("NodeGroupOutput")
    set_pos = nodes.new("GeometryNodeSetPosition")
    combine = nodes.new("ShaderNodeCombineXYZ")
    links.new(in_node.outputs[0], set_pos.inputs["Geometry"])
    links.new(in_node.outputs[1], combine.inputs["X"])
    links.new(combine.outputs[0], set_pos.inputs["Offset"])
    links.new(set_pos.outputs["Geometry"], out_node.inputs[0])


def _socket_key(mod):
    keys = [key for key in mod.keys() if str(key).startswith("Socket_")]
    keys = [key for key in keys if not str(key).endswith("_use_attribute")]
    keys = [key for key in keys if not str(key).endswith("_attribute_name")]
    return keys[-1]


def _evaluated_x(obj):
    bpy.context.view_layer.update()
    deps = bpy.context.evaluated_depsgraph_get()
    verts = obj.evaluated_get(deps).data.vertices
    return tuple(round(float(v.co.x), 4) for v in verts)


def _attached_empty_pair(root_obj):
    parent = scp_with_object(root_obj, "Parent", empty_object("Parent"), with_geometry=False)
    child = scp_with_object(root_obj, "Child", empty_object("Child", (1.0, 0.0, 0.0)), with_geometry=False)
    child.attach_parent_anchor_mode = child.attach_child_anchor_mode = "OBJECT_ORIGIN"
    set_parent_relation(child.transform_object_ref, child, parent.transform_object_ref)
    capture_attachment_from_link(child, child.transform_object_ref, None, parent.transform_object_ref, None)
    return parent, child


class ShortcutWorkflowTests(BlenderTestCase):
    def test_add_and_delete_data_shortcut_operator(self):
        root_obj = root()
        scp = scp_with_object(root_obj, "Arm", mesh_object("Arm"))
        select_only(scp.transform_object_ref)
        bpy.context.scene.af_new_shortcut_name = "Arm X"
        bpy.context.scene.af_new_shortcut_path = f'bpy.data.objects["{scp.transform_object_ref.name}"].location[0]'
        self.assertEqual(bpy.ops.af.add_data_shortcut(), {"FINISHED"})
        shortcut_id = root_obj.af_shortcut_system.shortcuts[0].id
        self.assertEqual(bpy.ops.af.delete_data_shortcut(shortcut_id=shortcut_id), {"FINISHED"})
        self.assertEqual(len(root_obj.af_shortcut_system.shortcuts), 0)

    def test_indexed_transform_shortcut_writes_through_scalar_proxy(self):
        root_obj = root()
        scp = scp_with_object(root_obj, "Arm", mesh_object("Arm"))
        select_only(scp.transform_object_ref)
        shortcut = add_shortcut(root_obj, "Arm X", "SCP", scp.id, f'bpy.data.objects["{scp.transform_object_ref.name}"].location[0]')
        target = resolve_shortcut(root_obj, bpy.context, shortcut.data_path)
        self.assertEqual(proxy_prop_name(target), "proxy_float")
        setattr(shortcut, proxy_prop_name(target), 2.5)
        bpy.context.view_layer.update()
        self.assertAlmostEqual(float(scp.transform_object_ref.location[0]), 2.5, places=4)
        self.assertAlmostEqual(float(getattr(shortcut, "proxy_float")), 2.5, places=4)

    def test_shortcut_session_uses_temporary_override_only_during_apply(self):
        root_obj = root()
        parent = scp_with_object(root_obj, "Parent", mesh_object("Parent"))
        child = scp_with_object(root_obj, "Child", mesh_object("Child", (1.0, 0.0, 0.0)))
        set_parent_relation(child.transform_object_ref, child, parent.transform_object_ref)
        child.attach_parent_anchor_mode = "OBJECT_ORIGIN"
        shortcut = add_shortcut(root_obj, "Parent X", "SCP", parent.id, f'bpy.data.objects["{parent.transform_object_ref.name}"].location[0]')
        upsert_override(shortcut, child.id, "SURFACE_NEAREST", "KEEP")
        select_only(child.transform_object_ref)
        self.assertTrue(_apply_float_shortcut(root_obj, shortcut, 2.0))
        session_loc = tuple(round(float(v), 4) for v in child.transform_object_ref.location)
        bpy.context.view_layer.update()
        self.assertNotEqual(tuple(attach_parent_param(child)["tri_vidx"]), (-1, -1, -1))
        self.assertEqual(tuple(round(float(v), 4) for v in child.transform_object_ref.location), session_loc)

    def test_parent_shortcut_moves_selected_child_without_override(self):
        root_obj = root()
        parent, child = _attached_empty_pair(root_obj)
        shortcut = add_shortcut(root_obj, "Parent X", "SCP", parent.id, f'bpy.data.objects["{parent.transform_object_ref.name}"].location[0]')
        select_only(child.transform_object_ref)
        shortcut.proxy_float = 2.0
        bpy.context.view_layer.update()
        loc = tuple(round(float(v), 4) for v in child.transform_object_ref.location)
        self.assertEqual(loc, (3.0, 0.0, 0.0))

    def test_geometry_nodes_shortcut_recomputes_evaluated_geometry(self):
        root_obj = root()
        scp = scp_with_object(root_obj, "Arm", mesh_object("Arm"))
        mod, key = _geometry_nodes_setup(scp.transform_object_ref)
        path = f'bpy.data.objects["{scp.transform_object_ref.name}"].modifiers["{mod.name}"]["{key}"]'
        shortcut = add_shortcut(root_obj, "Offset", "SCP", scp.id, path)
        select_only(scp.transform_object_ref)
        self.assertEqual(_evaluated_x(scp.transform_object_ref), (0.0, 1.0, 0.0))
        self.assertTrue(_apply_float_shortcut(root_obj, shortcut, 2.0))
        self.assertEqual(_evaluated_x(scp.transform_object_ref), (2.0, 3.0, 2.0))
