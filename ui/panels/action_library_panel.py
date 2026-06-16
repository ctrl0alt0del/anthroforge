import bpy

from ...app.queries.action_library import local_transform_panel_state


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
