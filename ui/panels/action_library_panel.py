import bpy

from ...app.queries.action_library import curve_loft_panel_state, local_transform_panel_state, split_corner_panel_state


def _status_icon(state):
    if state.has_conflict:
        return "ERROR"
    return "CHECKMARK" if state.installed else "INFO"


def _draw_header(box, state):
    box.label(text="Local Transform Properties")
    box.label(text=f"Active: {state.active_name}" if state.has_object else "No active object", icon="OBJECT_DATA")


def _draw_status(box, state):
    box.label(text=state.message, icon=_status_icon(state))
    box.label(text="Created properties can be targeted by shortcuts manually.", icon="DRIVER")


def _draw_buttons(box, state):
    row = box.row(align=True)
    row.enabled = state.has_object and not state.has_conflict
    row.operator("af.create_local_transform_props", icon="ADD")
    row.operator("af.rebind_local_transform_props", icon="FILE_REFRESH")
    row = box.row()
    row.enabled = state.has_object and (state.has_props or state.installed) and not state.has_conflict
    row.operator("af.remove_local_transform_props", icon="X")


def _draw_curve_loft_header(box):
    box.label(text="Curve Loft Geometry Nodes")
    box.label(text="Create a reusable loft node group from N curves.", icon="NODETREE")


def _draw_curve_loft_fields(box, scene):
    box.prop(scene, "af_action_gn_name")
    box.prop(scene, "af_action_curve_count")
    box.prop(scene, "af_action_single_angle")


def _draw_curve_loft_status(box, state):
    icon = "CHECKMARK" if state.can_create else "INFO"
    box.label(text=state.message, icon=icon)


def _draw_curve_loft_button(box, state):
    row = box.row()
    row.enabled = state.can_create
    row.operator("af.create_curve_loft_group", icon="NODETREE")


def _draw_split_corner_header(box):
    box.label(text="Split SCP by Corner")
    box.label(text="Split one selected curve corner into two SCPs.", icon="HOOK")


def _draw_split_corner_status(box, state):
    box.label(text=state.message, icon="CHECKMARK" if state.can_split else "INFO")
    box.label(text="Run this from Curve Edit Mode on the bound curve object.", icon="OUTLINER_OB_CURVE")


def _draw_split_corner_button(box, state):
    row = box.row()
    row.enabled = state.can_split
    row.operator("af.split_scp_by_corner", icon="SPLIT_HORIZONTAL")


class AF_PT_ActionLibraryPanel(bpy.types.Panel):
    bl_label = "Action Library"
    bl_idname = "AF_PT_action_library_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"
    bl_parent_id = "AF_PT_main_panel"

    def draw(self, context):
        state = local_transform_panel_state(context)
        box = self.layout.box()
        _draw_header(box, state)
        _draw_status(box, state)
        _draw_buttons(box, state)
        curve_state = curve_loft_panel_state(context)
        box = self.layout.box()
        _draw_curve_loft_header(box)
        _draw_curve_loft_fields(box, context.scene)
        _draw_curve_loft_status(box, curve_state)
        _draw_curve_loft_button(box, curve_state)
        split_state = split_corner_panel_state(context)
        box = self.layout.box()
        _draw_split_corner_header(box)
        _draw_split_corner_status(box, split_state)
        _draw_split_corner_button(box, split_state)
