import bpy

from ..app.queries.root import has_root
from ..app.use_cases.shortcuts import add_shortcut_from_context, delete_shortcut_from_context
from ..app.use_cases.shortcut_edit import save_shortcut_override, shortcut_override_modes
from ..app.use_cases.shortcut_wizard import apply_shortcut_wizard, clear_shortcut_wizard, populate_shortcut_wizard


def _wizard_items(scene):
    return tuple(getattr(scene, "af_shortcut_wizard_items", ()) or ())


def _draw_wildcard_value(layout, scene):
    box = layout.box()
    box.prop(scene, "af_shortcut_wizard_wildcard_value", text="Wildcard Value")
    box.label(text="Use * inside shortcut names to insert the wildcard value.")


def _draw_wizard_row(layout, item):
    row = layout.row(align=True)
    row.prop(item, "enabled", text="")
    row.label(text=str(getattr(item, "label", "") or ""))
    if not bool(getattr(item, "enabled", False)):
        return
    layout.row(align=True).prop(item, "shortcut_name", text="Shortcut Name")


def _draw_wizard_rows(layout, scene):
    items = _wizard_items(scene)
    if not items:
        return layout.label(text="No numeric shortcut candidates were found.")
    box = layout.box()
    for item in items:
        _draw_wizard_row(box, item)


def _parent_items(_self, _context):
    from ..core.shortcuts import parent_override_items
    return parent_override_items()


def _child_items(_self, _context):
    from ..core.shortcuts import child_override_items
    return child_override_items()


class AF_OT_AddDataShortcut(bpy.types.Operator):
    bl_idname = "af.add_data_shortcut"
    bl_label = "Add Data Shortcut"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if not has_root(context):
            return {"CANCELLED"}
        ok, error = add_shortcut_from_context(context)
        if not ok:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        return {"FINISHED"}


class AF_OT_DeleteDataShortcut(bpy.types.Operator):
    bl_idname = "af.delete_data_shortcut"
    bl_label = "Delete Data Shortcut"
    bl_options = {"REGISTER", "UNDO"}

    shortcut_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        if not has_root(context):
            return {"CANCELLED"}
        return {"FINISHED"} if delete_shortcut_from_context(context, self.shortcut_id) else {"CANCELLED"}


class AF_OT_EditShortcutOverride(bpy.types.Operator):
    bl_idname = "af.edit_shortcut_override"
    bl_label = "Shortcut Anchor Override"
    bl_options = {"REGISTER", "UNDO"}

    shortcut_id: bpy.props.StringProperty(default="")
    target_scp_id: bpy.props.StringProperty(default="")
    parent_anchor_mode: bpy.props.EnumProperty(name="Parent Anchor", items=_parent_items)
    child_anchor_mode: bpy.props.EnumProperty(name="Child Anchor", items=_child_items)

    def invoke(self, context, _event):
        if not has_root(context):
            return {"CANCELLED"}
        self.parent_anchor_mode, self.child_anchor_mode = shortcut_override_modes(context, self.shortcut_id, self.target_scp_id)
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, _context):
        self.layout.prop(self, "parent_anchor_mode")
        self.layout.prop(self, "child_anchor_mode")

    def execute(self, context):
        if not has_root(context):
            return {"CANCELLED"}
        return {"FINISHED"} if save_shortcut_override(context, self.shortcut_id, self.target_scp_id, self.parent_anchor_mode, self.child_anchor_mode) else {"CANCELLED"}


class AF_OT_ShortcutWizard(bpy.types.Operator):
    bl_idname = "af.shortcut_wizard"
    bl_label = "Shortcut Wizard"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, _event):
        ok, error = populate_shortcut_wizard(context)
        if not ok:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self, width=720)

    def draw(self, context):
        self.layout.label(text="Checked rows will exist as shortcuts for the current selected owner.")
        _draw_wildcard_value(self.layout, context.scene)
        _draw_wizard_rows(self.layout, context.scene)

    def cancel(self, context):
        clear_shortcut_wizard(context.scene)

    def execute(self, context):
        ok, error = apply_shortcut_wizard(context)
        if not ok:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}
        return {"FINISHED"}
