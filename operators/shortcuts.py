import bpy

from ..core.id_utils import next_prefixed_id
from ..core.shortcuts import normalize_shortcut_path, resolve_shortcut
from ..core.utils import get_af_root


def _draft_name(scene):
    return str(getattr(scene, "af_new_shortcut_name", "") or "").strip()


def _draft_path(scene):
    return str(getattr(scene, "af_new_shortcut_path", "") or "").strip()


def _clear_shortcut_draft(scene):
    scene.af_new_shortcut_name = ""
    scene.af_new_shortcut_path = ""


def _shortcut_index(root, shortcut_id):
    for index, item in enumerate(root.af_shortcut_system.shortcuts):
        if str(getattr(item, "id", "") or "") == str(shortcut_id or ""):
            return index
    return -1


def _add_shortcut(root, name, data_path):
    item = root.af_shortcut_system.shortcuts.add()
    item.id = next_prefixed_id(root.af_shortcut_system.shortcuts, "SHORTCUT")
    item.name = name
    item.data_path = data_path


class AF_OT_AddDataShortcut(bpy.types.Operator):
    bl_idname = "af.add_data_shortcut"
    bl_label = "Add Data Shortcut"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            return {"CANCELLED"}
        name = _draft_name(context.scene)
        data_path = normalize_shortcut_path(root, context, _draft_path(context.scene))
        if not name or not data_path:
            self.report({"ERROR"}, "Enter a shortcut name and a supported data path.")
            return {"CANCELLED"}
        if resolve_shortcut(root, context, data_path).owner is None:
            self.report({"ERROR"}, "Shortcut path could not be resolved.")
            return {"CANCELLED"}
        _add_shortcut(root, name, data_path)
        _clear_shortcut_draft(context.scene)
        return {"FINISHED"}


class AF_OT_DeleteDataShortcut(bpy.types.Operator):
    bl_idname = "af.delete_data_shortcut"
    bl_label = "Delete Data Shortcut"
    bl_options = {"REGISTER", "UNDO"}

    shortcut_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            return {"CANCELLED"}
        index = _shortcut_index(root, self.shortcut_id)
        if index < 0:
            return {"CANCELLED"}
        root.af_shortcut_system.shortcuts.remove(index)
        return {"FINISHED"}
