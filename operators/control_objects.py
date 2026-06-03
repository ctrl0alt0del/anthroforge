import bpy

from ..core.utils import get_af_root
from ..core.visualization.control_object_service import (
    mark_selected_scp_control,
    selected_object,
    toggle_selected_control_axis_shortcut,
)


class AFOTMarkSelectedSCPControlObject(bpy.types.Operator):
    bl_idname = "af.mark_selected_scp_control_object"
    bl_label = "Mark Selected As SCP Control"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        root = get_af_root(scene)
        return root is not None and selected_object(context) is not None

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            return {"CANCELLED"}
        ok, error = mark_selected_scp_control(root, context)
        if not ok:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        return {"FINISHED"}


class AFOTToggleControlObjectShortcutAxis(bpy.types.Operator):
    bl_idname = "af.toggle_control_object_shortcut_axis"
    bl_label = "Toggle Control Object Shortcut Axis"
    bl_options = {"REGISTER", "UNDO"}

    axis: bpy.props.EnumProperty(
        name="Axis",
        items=(("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", "")),
        default="X",
    )

    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        root = get_af_root(scene)
        return root is not None and selected_object(context) is not None

    def execute(self, context):
        root = get_af_root(context.scene)
        axis = str(self.axis or "")
        if root is None:
            return {"CANCELLED"}
        ok, error = toggle_selected_control_axis_shortcut(root, context, axis)
        if not ok:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        return {"FINISHED"}
