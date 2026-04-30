import bpy
from ..core.utils import get_af_root
from ..core.deps.dirty_hints import empty_dirty_hints
from ..core.scp_runtime.copy import copy_scp_subtree
from ..core.scp_runtime.delete import delete_scp
from ..core.scp_runtime.common import find_primary_scp_obj
from ..core.scp_runtime.lookup import activate_scp
from ..core.scp_runtime.object_colors import enable_object_color_view
from ..core.scp_runtime.tree import children_map
from ..ui.tree_state import toggle_collapsed, toggle_vcp_collapsed
from ..core.deps.dirty_hints import dirty_hints_for
from ..core.visualization.sync_runner import sync_from_dirty_hints
from ..core.visualization.control_runtime import notify_selection_changed


class AF_OT_ToggleSCPCollapse(bpy.types.Operator):
    bl_idname = "af.toggle_scp_collapse"
    bl_label = "Toggle SCP Collapse"

    scp_id: bpy.props.StringProperty()

    def execute(self, context):
        if not self.scp_id:
            return {"CANCELLED"}
        toggle_collapsed(context.scene, self.scp_id)
        return {"FINISHED"}


class AF_OT_SelectSCPInTree(bpy.types.Operator):
    bl_idname = "af.select_scp_in_tree"
    bl_label = "Select SCP In Tree"

    scp_id: bpy.props.StringProperty()
    extend: bpy.props.BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        self.extend = bool(event.shift)
        return self.execute(context)

    def _target_index(self, root):
        for i, scp in enumerate(root.af_scp_system.scps):
            if scp.id == self.scp_id:
                return i
        return -1

    def _find_scp_object(self, context, root_name):
        return find_primary_scp_obj(context.scene, root_name, self.scp_id)

    def _select_only(self, context, obj):
        if not self.extend:
            for o in context.selected_objects:
                o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj

    def _set_active_scp_index(self, scene, root, index):
        scene.af_selection_sync_lock = True
        try:
            root.af_scp_system.active_scp_index = index
        finally:
            scene.af_selection_sync_lock = False

    def _selection_target(self, context):
        root = get_af_root(context.scene)
        if root is None:
            return None, -1, None
        return root, self._target_index(root), self._find_scp_object(context, root.name)

    def execute(self, context):
        root, target_index, target_obj = self._selection_target(context)
        if root is None or target_index < 0 or target_obj is None:
            return {"CANCELLED"}
        self._select_only(context, target_obj)
        self._set_active_scp_index(context.scene, root, target_index)
        notify_selection_changed(context.scene)
        return {"FINISHED"}


class AF_OT_DeleteSCPInTree(bpy.types.Operator):
    bl_idname = "af.delete_scp_in_tree"
    bl_label = "Delete SCP In Tree"
    bl_options = {"REGISTER", "UNDO"}

    scp_id: bpy.props.StringProperty()

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None or not self.scp_id:
            return {"CANCELLED"}
        if not delete_scp(root, context.scene, self.scp_id):
            return {"CANCELLED"}
        sync_from_dirty_hints(root=root, scene=context.scene, dirty_hints=empty_dirty_hints(), source="operator", event_type="DELETE")
        notify_selection_changed(context.scene, force=True)
        return {"FINISHED"}


class AF_OT_CopySCPInTree(bpy.types.Operator):
    bl_idname = "af.copy_scp_in_tree"
    bl_label = "Copy SCP In Tree"
    bl_options = {"REGISTER", "UNDO"}
    bl_property = "copy_scope"

    scp_id: bpy.props.StringProperty()
    copy_scope: bpy.props.EnumProperty(
        name="Copy Scope",
        items=(
            ("PARENT_ONLY", "Copy Parent Only", ""),
            ("ALL", "Copy All", ""),
        ),
        default="PARENT_ONLY",
    )

    def invoke(self, context, event):
        _ = event
        root = get_af_root(context.scene)
        return self.execute(context) if not _has_children(root, self.scp_id) else context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        _ = context
        self.layout.prop(self, "copy_scope", expand=True)

    def _child_ids(self, root):
        return [] if self.copy_scope == "PARENT_ONLY" else _subtree_child_ids(root, self.scp_id)

    def execute(self, context):
        root = get_af_root(context.scene)
        new_id = "" if root is None else copy_scp_subtree(root, context.scene, self.scp_id, self._child_ids(root))
        if root is None or not new_id:
            return {"CANCELLED"}
        _select_copied_scp(context, root, new_id)
        sync_from_dirty_hints(root=root, scene=context.scene, dirty_hints=empty_dirty_hints(), source="operator", event_type="MARK")
        notify_selection_changed(context.scene, force=True)
        return {"FINISHED"}


def _subtree_child_ids(root, scp_id):
    kids = children_map({str(s.id): s for s in root.af_scp_system.scps})
    stack, out = list(reversed(kids.get(str(scp_id), []))), []
    while stack:
        sid = stack.pop()
        out.append(sid), stack.extend(reversed(kids.get(sid, [])))
    return out


def _has_children(root, scp_id):
    if root is None or not scp_id:
        return False
    kids = children_map({str(s.id): s for s in root.af_scp_system.scps})
    return bool(kids.get(str(scp_id), []))


def _select_copied_scp(context, root, scp_id):
    obj = find_primary_scp_obj(context.scene, root.name, scp_id)
    activate_scp(root, scp_id), enable_object_color_view(context)
    if obj is None:
        return
    for other in context.selected_objects:
        other.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


class AF_OT_ToggleVCPCollapse(bpy.types.Operator):
    bl_idname = "af.toggle_vcp_collapse"
    bl_label = "Toggle VCP Collapse"

    node_key: bpy.props.StringProperty()

    def execute(self, context):
        if not self.node_key:
            return {"CANCELLED"}
        toggle_vcp_collapsed(context.scene, self.node_key)
        return {"FINISHED"}


class AF_OT_SelectVCPInTree(bpy.types.Operator):
    bl_idname = "af.select_vcp_in_tree"
    bl_label = "Select VCP In Tree"

    node_id: bpy.props.StringProperty()
    node_type: bpy.props.EnumProperty(
        items=(
            ("MUSCLE", "Muscle", ""),
            ("FIBER", "Fiber", ""),
            ("BLOB", "Blob", ""),
        )
    )
    extend: bpy.props.BoolProperty(default=False, options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        self.extend = bool(event.shift)
        return self.execute(context)

    def _match_vcp_obj(self, obj, root_name):
        if self.node_type == "FIBER":
            return obj.get("af_fiber_proxy") and obj.get("af_root_name") == root_name and obj.get("af_fiber_id") == self.node_id
        if self.node_type == "MUSCLE":
            return obj.get("af_muscle_proxy") and obj.get("af_root_name") == root_name and obj.get("af_muscle_id") == self.node_id
        if self.node_type == "BLOB":
            return obj.get("af_blob_proxy") and obj.get("af_root_name") == root_name and obj.get("af_blob_id") == self.node_id
        return False

    def _find_target_obj(self, context, root_name):
        for obj in context.scene.objects:
            if self._match_vcp_obj(obj, root_name):
                return obj
        return None

    def _select_target(self, context, obj):
        if not self.extend:
            for o in context.selected_objects:
                o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj

    def _sync_selected_vcp(self, context, root):
        notify_selection_changed(context.scene)
        sync_from_dirty_hints(root=root, scene=context.scene, dirty_hints=dirty_hints_for(self.node_type, {self.node_id}), bake=False)

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            return {"CANCELLED"}
        target_obj = self._find_target_obj(context, root.name)
        if target_obj is None:
            return {"CANCELLED"}
        self._select_target(context, target_obj)
        v = root.af_vcp_system
        v.active_vcp_id = self.node_id
        v.active_vcp_type = self.node_type
        self._sync_selected_vcp(context, root)
        return {"FINISHED"}
