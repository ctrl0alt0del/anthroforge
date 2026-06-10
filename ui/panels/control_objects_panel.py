import bpy

from ...app.queries.control_objects import control_panel_state
from ...app.queries.root import has_root


def _draw_checkbox_row(layout, axis_state):
    icon = "CHECKBOX_HLT" if axis_state.checked else "CHECKBOX_DEHLT"
    row = layout.row(align=True)
    op = row.operator("af.toggle_control_object_shortcut_axis", text=f"Position {axis_state.axis}", icon=icon)
    op.axis = axis_state.axis


def _draw_shortcut_checkbox_mode(layout, state):
    box = layout.box()
    box.label(text=f"Control Object: {state.obj.name}", icon="CON_OBJECTSOLVER")
    parent_icon = "CHECKBOX_HLT" if state.apply_parent else "CHECKBOX_DEHLT"
    box.operator("af.toggle_control_object_apply_parent", text="Apply Parent", icon=parent_icon)
    box.label(text="Position Components")
    for axis_state in state.axis_states:
        _draw_checkbox_row(box, axis_state)


def _draw_mark_mode(layout, context, state):
    box = layout.box()
    box.label(text="Mark Control Object", icon="OUTLINER_OB_EMPTY")
    if state.obj is None:
        box.label(text="Select an object first.", icon="INFO")
        return

    box.prop(context.scene, "af_control_scp_obj", text="SCP")
    if state.picked is None:
        box.label(text="Pick an SCP object first.", icon="ERROR")
        return

    box.label(text=f"Selected Object: {state.obj.name}")
    box.label(text=f"Target SCP: {state.picked.name}")
    box.operator("af.mark_selected_scp_control_object", icon="ADD")


class AFPTControlObjectsPanel(bpy.types.Panel):
    bl_label = "Control Objects"
    bl_idname = "AF_PT_control_objects_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"
    bl_parent_id = "AF_PT_main_panel"

    @classmethod
    def poll(cls, context):
        return has_root(context)

    def draw(self, context):
        state = control_panel_state(context)
        if state.is_control:
            _draw_shortcut_checkbox_mode(self.layout, state)
            return
        _draw_mark_mode(self.layout, context, state)
