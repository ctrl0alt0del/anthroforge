import bpy

from ...app.queries.root import has_root
from ...app.queries.shortcuts import shortcut_panel_state
def _draw_delete_button(row, shortcut):
    op = row.operator("af.delete_data_shortcut", text="", icon="X")
    op.shortcut_id = shortcut.id


def _draw_override_button(row, row_state):
    if not row_state.show_override:
        return
    op = row.operator("af.edit_shortcut_override", text="", icon="KEY_HLT" if row_state.has_override else "KEY_DEHLT")
    op.shortcut_id = row_state.shortcut.id
    op.target_scp_id = row_state.selected_scp_id


def _draw_shortcut_value(layout, row_state):
    return _draw_array_value(layout, row_state) if _whole_array(row_state.target) else _draw_inline_value(layout.row(align=True), row_state)


def _draw_invalid_shortcut(box, shortcut, error):
    row = box.row(align=True)
    row.label(text=f"{shortcut.name}: {error}", icon="ERROR")
    _draw_delete_button(row, shortcut)


def _draw_valid_shortcut(box, row_state):
    _draw_shortcut_value(box, row_state)


def _draw_inline_value(row, row_state, index=None, actions=True):
    prop_name = _prop_name(row_state.target, index)
    kwargs = {"text": _row_label(row_state.shortcut.name, index)}
    if index is not None or (index is None and row_state.target.array_length and row_state.target.index >= 0):
        kwargs["index"] = row_state.target.index if index is None else int(index)
    row.prop(row_state.shortcut, prop_name, **kwargs)
    _draw_row_actions(row, row_state) if actions else None


def _draw_array_value(layout, row_state):
    for index in range(int(row_state.target.array_length or 0)):
        _draw_inline_value(layout.row(align=True), row_state, index=index, actions=index == 0)


def _whole_array(target):
    return int(getattr(target, "array_length", 0) or 0) > 0 and int(getattr(target, "index", -1)) < 0


def _prop_name(target, index):
    if int(getattr(target, "array_length", 0) or 0) > 0 and index is None and int(getattr(target, "index", -1)) < 0:
        return {"BOOL": "proxy_bool_vec", "INT": "proxy_int_vec", "FLOAT": "proxy_float_vec"}.get(target.value_type, "proxy_float_vec")
    return {"BOOL": "proxy_bool", "INT": "proxy_int", "FLOAT": "proxy_float", "STRING": "proxy_string", "ENUM": "proxy_enum"}.get(target.value_type, "proxy_string")


def _row_label(name, index):
    return str(name or "") if index is None else f"{name}[{int(index)}]"


def _draw_row_actions(row, row_state):
    _draw_override_button(row, row_state)
    _draw_delete_button(row, row_state.shortcut)


def _draw_shortcut_row(layout, row_state):
    box = layout.box()
    if row_state.target.owner is None:
        _draw_invalid_shortcut(box, row_state.shortcut, row_state.target.error)
        return
    _draw_valid_shortcut(box, row_state)


def _draw_shortcut_mode(layout, scene):
    layout.row(align=True).prop(scene, "af_shortcut_view_mode", expand=True)


def _draw_shortcut_list(layout, state):
    if not state.rows:
        layout.label(text="No shortcuts")
        return
    for row_state in state.rows:
        _draw_shortcut_row(layout, row_state)


def _draw_shortcut_form(layout, scene):
    box = layout.box()
    box.label(text="New Shortcut")
    box.prop(scene, "af_new_shortcut_name", text="Shortcut Name")
    box.prop(scene, "af_new_shortcut_path", text="Data Path")
    box.operator("af.add_data_shortcut", icon="ADD")


class AF_PT_ShortcutPanel(bpy.types.Panel):
    bl_label = "Shortcuts"
    bl_idname = "AF_PT_shortcut_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"
    bl_parent_id = "AF_PT_main_panel"

    @classmethod
    def poll(cls, context):
        return has_root(context)

    def draw(self, context):
        state = shortcut_panel_state(context)
        _draw_shortcut_mode(self.layout, context.scene)
        _draw_shortcut_form(self.layout, context.scene)
        _draw_shortcut_list(self.layout, state)
