import bpy

from ..app.use_cases.action_library_gn import create_curve_loft_group, curve_loft_exists, curve_loft_name
from ..app.use_cases.action_library_split_corner import split_scp_by_corner
from ..app.use_cases.local_transform_props import create_local_transform_props, rebind_local_transform_props, remove_local_transform_props
from .action_library_quick_hook import (
    cancel_quick_hook,
    draw_quick_hook_name,
    execute_quick_hook,
    execute_quick_hook_name,
    invoke_quick_hook,
    invoke_quick_hook_name,
    modal_quick_hook,
)


def _finish(op, context, action):
    ok, error = action(context)
    if ok:
        return {"FINISHED"}
    op.report({"ERROR"}, error)
    return {"CANCELLED"}


class AF_OT_CreateLocalTransformProps(bpy.types.Operator):
    bl_idname = "af.create_local_transform_props"
    bl_label = "Create Local Transform Properties"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return _finish(self, context, create_local_transform_props)


class AF_OT_RebindLocalTransformProps(bpy.types.Operator):
    bl_idname = "af.rebind_local_transform_props"
    bl_label = "Rebind Local Transform Properties"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return _finish(self, context, rebind_local_transform_props)


class AF_OT_RemoveLocalTransformProps(bpy.types.Operator):
    bl_idname = "af.remove_local_transform_props"
    bl_label = "Remove Local Transform Properties"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return _finish(self, context, remove_local_transform_props)


class AF_OT_CreateCurveLoftGroup(bpy.types.Operator):
    bl_idname = "af.create_curve_loft_group"
    bl_label = "Create Curve Loft Geometry Nodes"
    bl_options = {"REGISTER", "UNDO"}

    overwrite_existing: bpy.props.BoolProperty(default=False, options={"SKIP_SAVE"})

    def invoke(self, context, event):
        return _invoke_curve_loft(self, context, event)

    def execute(self, context):
        return _finish(self, context, lambda ctx: create_curve_loft_group(ctx, overwrite=self.overwrite_existing))


class AF_OT_SplitSCPByCorner(bpy.types.Operator):
    bl_idname = "af.split_scp_by_corner"
    bl_label = "Split SCP by Corner"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return _finish(self, context, split_scp_by_corner)


class AF_OT_QuickSCPHook(bpy.types.Operator):
    bl_idname = "af.quick_scp_hook"
    bl_label = "Quick Hook"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, _event):
        return invoke_quick_hook(self, context)

    def modal(self, context, event):
        return modal_quick_hook(self, context, event)

    def cancel(self, context):
        cancel_quick_hook(self, context)

    def execute(self, context):
        return execute_quick_hook(self, context)


class AF_OT_NameQuickSCPHook(bpy.types.Operator):
    bl_idname = "af.name_quick_scp_hook"
    bl_label = "Name Quick Hook"
    bl_options = {"REGISTER", "UNDO"}

    hook_name: bpy.props.StringProperty(name="Hook Name", default="", options={"SKIP_SAVE"})
    control_object_name: bpy.props.StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})
    geometry_object_name: bpy.props.StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})
    default_name: bpy.props.StringProperty(default="", options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, _event):
        return invoke_quick_hook_name(self, context)

    def draw(self, _context):
        draw_quick_hook_name(self)

    def execute(self, context):
        return execute_quick_hook_name(self, context)


def _invoke_curve_loft(op, context, event):
    if op.overwrite_existing or not curve_loft_exists(context):
        return op.execute(context)
    op.overwrite_existing = True
    name = curve_loft_name(context)
    return context.window_manager.invoke_confirm(op, event, title="Overwrite Geometry Nodes?", message=f'Overwrite "{name}"?', confirm_text="Overwrite", icon="ERROR")
