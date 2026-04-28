import bpy

from ..core.deps.dirty_hints import dirty_hints_for
from ..core.scp_runtime.object_roles import active_scp_from_context, add_bound_object_to_scp, create_scp, create_transform_empty, remove_scp_bound_object, set_scp_geometry_object, set_scp_transform_object
from ..core.scp_runtime.lookup import activate_scp
from ..core.utils import get_af_root
from ..core.visualization.control_runtime import notify_selection_changed
from ..core.visualization.sync_runner import sync_from_dirty_hints


def _active_scp(context):
    root = get_af_root(context.scene)
    scp = None if root is None else active_scp_from_context(root, context)
    return root, scp


def _picker_obj(scene):
    return getattr(scene, "af_scp_object_picker", None)


def _sync_scp(context, scp_id, event_type="UPDATE"):
    sync_from_dirty_hints(root=get_af_root(context.scene), scene=context.scene, dirty_hints=dirty_hints_for("SCP", {scp_id}), source="operator", event_type=event_type)


def _report_error(operator, message):
    operator.report({"ERROR"}, message)
    return {"CANCELLED"}


def _select_only(context, obj):
    for other in context.selected_objects:
        other.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


class AF_OT_CreateEmptySCP(bpy.types.Operator):
    bl_idname = "af.create_empty_scp"
    bl_label = "Create Empty SCP"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            return _report_error(self, "No AF_ROOT found in scene.")
        scp = create_scp(root)
        obj = create_transform_empty(context, scp)
        set_scp_transform_object(root, scp, obj)
        activate_scp(root, scp.id)
        _select_only(context, obj)
        _sync_scp(context, scp.id, event_type="MARK")
        notify_selection_changed(context.scene, force=True)
        return {"FINISHED"}


class _AF_OT_SCPObjectBase(bpy.types.Operator):
    bl_options = {"REGISTER", "UNDO"}

    def _root_scp_obj(self, context):
        root, scp = _active_scp(context)
        obj = _picker_obj(context.scene)
        return root, scp, obj


class AF_OT_SetSCPTransformObject(_AF_OT_SCPObjectBase):
    bl_idname = "af.set_scp_transform_object"
    bl_label = "Set SCP Transform Object"

    def execute(self, context):
        root, scp, obj = self._root_scp_obj(context)
        if root is None or scp is None or obj is None:
            return _report_error(self, "Pick an object and select an SCP first.")
        if not set_scp_transform_object(root, scp, obj):
            return _report_error(self, "Object already belongs to another SCP.")
        _sync_scp(context, scp.id)
        return {"FINISHED"}


class AF_OT_SetSCPGeometryObject(_AF_OT_SCPObjectBase):
    bl_idname = "af.set_scp_geometry_object"
    bl_label = "Set SCP Geometry Object"

    def execute(self, context):
        root, scp, obj = self._root_scp_obj(context)
        if root is None or scp is None or obj is None:
            return _report_error(self, "Pick an object and select an SCP first.")
        if not set_scp_geometry_object(root, scp, obj):
            return _report_error(self, "Object already belongs to another SCP.")
        _sync_scp(context, scp.id)
        return {"FINISHED"}


class AF_OT_AddSCPBoundObject(_AF_OT_SCPObjectBase):
    bl_idname = "af.add_scp_bound_object"
    bl_label = "Add SCP Bound Object"

    def execute(self, context):
        root, scp, obj = self._root_scp_obj(context)
        if root is None or scp is None or obj is None:
            return _report_error(self, "Pick an object and select an SCP first.")
        if not add_bound_object_to_scp(root, scp, obj):
            return _report_error(self, "Object already belongs to another SCP.")
        _sync_scp(context, scp.id)
        return {"FINISHED"}


class AF_OT_RemoveSCPBoundObject(bpy.types.Operator):
    bl_idname = "af.remove_scp_bound_object"
    bl_label = "Remove SCP Bound Object"
    bl_options = {"REGISTER", "UNDO"}

    bound_id: bpy.props.StringProperty(default="")

    def execute(self, context):
        root, scp = _active_scp(context)
        if root is None or scp is None or not self.bound_id:
            return _report_error(self, "Select an SCP and a bound object.")
        if not remove_scp_bound_object(root, scp, self.bound_id):
            return _report_error(self, "Transform object cannot be removed.")
        _sync_scp(context, scp.id)
        return {"FINISHED"}
