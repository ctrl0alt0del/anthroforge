import bpy

from ...core.shortcuts import resolve_shortcut
from ...core.utils import get_af_root


def _draw_delete_button(row, shortcut):
    op = row.operator("af.delete_data_shortcut", text="", icon="X")
    op.shortcut_id = shortcut.id


def _draw_shortcut_value(row, target, shortcut):
    kwargs = {"text": shortcut.name}
    if target.index >= 0:
        kwargs["index"] = target.index
    row.prop(target.owner, target.prop_name, **kwargs)


def _draw_shortcut_path(box, shortcut):
    row = box.row()
    row.enabled = False
    row.label(text=shortcut.data_path)


def _draw_invalid_shortcut(box, shortcut, error):
    row = box.row(align=True)
    row.label(text=f"{shortcut.name}: {error}", icon="ERROR")
    _draw_delete_button(row, shortcut)
    _draw_shortcut_path(box, shortcut)


def _draw_valid_shortcut(box, shortcut, target):
    row = box.row(align=True)
    _draw_shortcut_value(row, target, shortcut)
    _draw_delete_button(row, shortcut)
    _draw_shortcut_path(box, shortcut)


def _draw_shortcut_row(layout, root, context, shortcut):
    target = resolve_shortcut(root, context, shortcut.data_path)
    box = layout.box()
    if target.owner is None:
        _draw_invalid_shortcut(box, shortcut, target.error)
        return
    _draw_valid_shortcut(box, shortcut, target)


def _draw_shortcut_list(layout, root, context):
    if not root.af_shortcut_system.shortcuts:
        layout.label(text="No shortcuts")
        return
    for shortcut in root.af_shortcut_system.shortcuts:
        _draw_shortcut_row(layout, root, context, shortcut)


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
        return get_af_root(context.scene) is not None

    def draw(self, context):
        root = get_af_root(context.scene)
        _draw_shortcut_form(self.layout, context.scene)
        _draw_shortcut_list(self.layout, root, context)
