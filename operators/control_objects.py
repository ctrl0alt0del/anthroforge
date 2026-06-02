import bpy

from ..core.id_utils import next_prefixed_id
from ..core.shortcuts.path_codec import make_shortcut_path
from ..core.utils import get_af_root
from ..core.selection import get_active_scp
from ..core.scp_runtime.common import scp_for_object
from ..core.visualization.scp_control_helpers import mark_scp_control_object


_AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}
_AXIS_LABEL = {"X": "X", "Y": "Y", "Z": "Z"}


def _selected_object(context):
    return getattr(context, "active_object", None)


def _picked_scp(root, context):
    picker = getattr(context.scene, "af_control_scp_obj", None)
    if picker is not None:
        scp = scp_for_object(root, picker)
        if scp is not None:
            return scp
    return get_active_scp(root, context)


def _shortcut_name(obj, axis):
    return f"{obj.name} Position {_AXIS_LABEL[str(axis)]}"


def _shortcut_path(obj, axis):
    axis_index = _AXIS_INDEX[str(axis)]
    return make_shortcut_path("object_rna", f"location[{int(axis_index)}]", entity_id=str(obj.name))


def _shortcut_owner_from_object(obj):
    if obj is None:
        return "NONE", ""
    if obj.get("af_scp_id"):
        return "SCP", str(obj.get("af_scp_id"))
    if obj.get("af_fiber_id"):
        return "FIBER", str(obj.get("af_fiber_id"))
    if obj.get("af_muscle_id"):
        return "MUSCLE", str(obj.get("af_muscle_id"))
    if obj.get("af_blob_id"):
        return "BLOB", str(obj.get("af_blob_id"))
    return "NONE", ""


def _shortcut_owner(root, context, obj):
    owner_type, owner_id = _shortcut_owner_from_object(obj)
    if owner_type != "NONE" and owner_id:
        return owner_type, owner_id
    scp = _picked_scp(root, context)
    return ("SCP", str(getattr(scp, "id", "") or "")) if scp is not None else ("NONE", "")


def _find_shortcut(root, data_path):
    needle = str(data_path or "")
    for item in root.af_shortcut_system.shortcuts:
        if str(getattr(item, "data_path", "") or "") == needle:
            return item
    return None


def has_axis_shortcut(root, obj, axis):
    if root is None or obj is None or str(axis or "") not in _AXIS_INDEX:
        return False
    return _find_shortcut(root, _shortcut_path(obj, axis)) is not None


def _remove_shortcut(root, shortcut_id):
    sid = str(shortcut_id or "")
    for index, item in enumerate(root.af_shortcut_system.shortcuts):
        if str(getattr(item, "id", "") or "") == sid:
            root.af_shortcut_system.shortcuts.remove(index)
            return True
    return False


def _add_shortcut(root, name, data_path, owner_type, owner_id):
    item = root.af_shortcut_system.shortcuts.add()
    item.id = next_prefixed_id(root.af_shortcut_system.shortcuts, "SHORTCUT")
    item.name = str(name or "").strip()
    item.owner_type = str(owner_type or "NONE")
    item.owner_id = str(owner_id or "")
    item.data_path = str(data_path or "")


class AFOTMarkSelectedSCPControlObject(bpy.types.Operator):
    bl_idname = "af.mark_selected_scp_control_object"
    bl_label = "Mark Selected As SCP Control"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        root = get_af_root(scene)
        return root is not None and _selected_object(context) is not None

    def execute(self, context):
        root = get_af_root(context.scene)
        obj = _selected_object(context)
        if root is None or obj is None:
            return {"CANCELLED"}

        scp = _picked_scp(root, context)
        scp_id = "" if scp is None else str(getattr(scp, "id", "") or "")
        if not scp_id:
            self.report({"ERROR"}, "Pick an SCP object first.")
            return {"CANCELLED"}

        mark_scp_control_object(obj, root, scp_id)
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
        scene = getattr(context, "scene", None)
        root = get_af_root(scene)
        return root is not None and _selected_object(context) is not None

    def execute(self, context):
        root = get_af_root(context.scene)
        obj = _selected_object(context)
        axis = str(self.axis or "")
        if root is None or obj is None or axis not in _AXIS_INDEX:
            return {"CANCELLED"}

        data_path = _shortcut_path(obj, axis)
        existing = _find_shortcut(root, data_path)
        if existing is not None:
            _remove_shortcut(root, existing.id)
            return {"FINISHED"}

        owner_type, owner_id = _shortcut_owner(root, context, obj)
        if owner_type == "NONE" or not owner_id:
            self.report({"ERROR"}, "Could not resolve shortcut owner. Select an SCP or VCP first.")
            return {"CANCELLED"}

        _add_shortcut(
            root=root,
            name=_shortcut_name(obj, axis),
            data_path=data_path,
            owner_type=owner_type,
            owner_id=owner_id,
        )
        return {"FINISHED"}
