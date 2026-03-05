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

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            return {"CANCELLED"}

        target_index = -1
        for i, scp in enumerate(root.af_scp_system.scps):
            if scp.id == self.scp_id:
                target_index = i
                break
        if target_index < 0:
            return {"CANCELLED"}

        target_obj = None
        for obj in context.scene.objects:
            if (
                obj.get("af_proxy")
                and obj.get("af_root_name") == root.name
                and obj.get("af_scp_id") == self.scp_id
            ):
                target_obj = obj
                break
        if target_obj is None:
            return {"CANCELLED"}

        if not self.extend:
            for o in context.selected_objects:
                o.select_set(False)

        target_obj.select_set(True)
        context.view_layer.objects.active = target_obj

        scene = context.scene
        scene.af_selection_sync_lock = True
        try:
            root.af_scp_system.active_scp_index = target_index
        finally:
            scene.af_selection_sync_lock = False

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

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            return {"CANCELLED"}

        target_obj = None
        if self.node_type == "FIBER":
            for obj in context.scene.objects:
                if (
                    obj.get("af_fiber_proxy")
                    and obj.get("af_root_name") == root.name
                    and obj.get("af_fiber_id") == self.node_id
                ):
                    target_obj = obj
                    break
        elif self.node_type == "MUSCLE":
            for obj in context.scene.objects:
                if (
                    obj.get("af_muscle_proxy")
                    and obj.get("af_root_name") == root.name
                    and obj.get("af_muscle_id") == self.node_id
                ):
                    target_obj = obj
                    break
        elif self.node_type == "BLOB":
            for obj in context.scene.objects:
                if (
                    obj.get("af_blob_proxy")
                    and obj.get("af_root_name") == root.name
                    and obj.get("af_blob_id") == self.node_id
                ):
                    target_obj = obj
                    break

        if target_obj is None:
            return {"CANCELLED"}

        if not self.extend:
            for o in context.selected_objects:
                o.select_set(False)

        target_obj.select_set(True)
        context.view_layer.objects.active = target_obj

        v = root.af_vcp_system
        v.active_vcp_id = self.node_id
        v.active_vcp_type = self.node_type
        register_fiber_sync().sync_root_to_scene(root=root, scene=context.scene)
        return {"FINISHED"}
