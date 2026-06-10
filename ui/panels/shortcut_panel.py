import bpy

from ...app.queries.root import has_root
from ...app.queries.shortcuts import shortcut_panel_state


def _draw_delete_button(row, shortcut):
    op = row.operator("af.delete_data_shortcut", text="", icon="X")
    op.shortcut_id = shortcut.id


def _draw_shortcut_value(row, target, shortcut):
    kwargs = {"text": shortcut.name}
    if target.index >= 0:
        kwargs["index"] = target.index
    row.prop(target.owner, target.prop_name, **kwargs)


def _draw_invalid_shortcut(box, shortcut, error):
    row = box.row(align=True)
    row.label(text=f"{shortcut.name}: {error}", icon="ERROR")
    _draw_delete_button(row, shortcut)


def _draw_valid_shortcut(box, shortcut, target):
    row = box.row(align=True)
    _draw_shortcut_value(row, target, shortcut)
    _draw_delete_button(row, shortcut)


def _draw_shortcut_row(layout, row_state):
    box = layout.box()
    if row_state.target.owner is None:
        _draw_invalid_shortcut(box, row_state.shortcut, row_state.target.error)
        return
    _draw_valid_shortcut(box, row_state.shortcut, row_state.target)


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
