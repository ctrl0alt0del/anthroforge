import bpy

from ..app.queries.control_objects import active_object
from ..app.queries.root import has_root
from ..app.use_cases.control_objects import (
    can_edit_control_objects,
    mark_selected_control,
    toggle_control_axis,
    toggle_control_parent,
)
from ..core.control_flags import is_control_object


class AFOTMarkSelectedSCPControlObject(bpy.types.Operator):
    bl_idname = "af.mark_selected_scp_control_object"
    bl_label = "Mark Selected As SCP Control"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return can_edit_control_objects(context)

    def execute(self, context):
        if not has_root(context):
            return {"CANCELLED"}
        ok, error = mark_selected_control(context)
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
        return can_edit_control_objects(context)

    def execute(self, context):
        axis = str(self.axis or "")
        if not has_root(context):
            return {"CANCELLED"}
        ok, error = toggle_control_axis(context, axis)
        if not ok:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        return {"FINISHED"}


class AFOTToggleControlObjectApplyParent(bpy.types.Operator):
    bl_idname = "af.toggle_control_object_apply_parent"
    bl_label = "Toggle Control Object Apply Parent"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return can_edit_control_objects(context) and is_control_object(active_object(context))

    def execute(self, context):
        if not has_root(context):
            return {"CANCELLED"}
        ok, error = toggle_control_parent(context)
        if not ok:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        return {"FINISHED"}
