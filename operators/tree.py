import bpy
from ..core.utils import get_af_root
from ..ui.tree_state import toggle_collapsed, toggle_vcp_collapsed
from ..core.visualization.fiber_sync import register_fiber_sync


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

    def _find_scp_proxy(self, context, root_name):
        for obj in context.scene.objects:
            if obj.get("af_proxy") and obj.get("af_root_name") == root_name and obj.get("af_scp_id") == self.scp_id:
                return obj
        return None

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

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            return {"CANCELLED"}
        target_index = self._target_index(root)
        if target_index < 0:
            return {"CANCELLED"}
        target_obj = self._find_scp_proxy(context, root.name)
        if target_obj is None:
            return {"CANCELLED"}
        self._select_only(context, target_obj)
        self._set_active_scp_index(context.scene, root, target_index)
        return {"FINISHED"}


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
        register_fiber_sync().sync_root_to_scene(root=root, scene=context.scene)
        return {"FINISHED"}
