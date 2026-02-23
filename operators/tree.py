import bpy
from ..core.utils import get_af_root
from ..ui.tree_state import toggle_collapsed, toggle_vcp_collapsed


class AF_OT_ToggleSCPCollapse(bpy.types.Operator):
    bl_idname = "af.toggle_scp_collapse"
    bl_label = "Toggle SCP Collapse"

    scp_id: bpy.props.StringProperty()

    def execute(self, context):
        if not self.scp_id:
            return {'CANCELLED'}
        toggle_collapsed(context.scene, self.scp_id)
        return {'FINISHED'}


class AF_OT_SelectSCPInTree(bpy.types.Operator):
    bl_idname = "af.select_scp_in_tree"
    bl_label = "Select SCP In Tree"

    scp_id: bpy.props.StringProperty()

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            return {'CANCELLED'}

        target_index = -1
        for i, scp in enumerate(root.af_scp_system.scps):
            if scp.id == self.scp_id:
                target_index = i
                break

        if target_index < 0:
            return {'CANCELLED'}

        root.af_scp_system.active_scp_index = target_index
        return {'FINISHED'}



class AF_OT_ToggleVCPCollapse(bpy.types.Operator):
    bl_idname = "af.toggle_vcp_collapse"
    bl_label = "Toggle VCP Collapse"

    node_key: bpy.props.StringProperty()

    def execute(self, context):
        if not self.node_key:
            return {'CANCELLED'}
        _toggle_vcp_collapsed(context.scene, self.node_key)
        return {'FINISHED'}


class AF_OT_SelectVCPInTree(bpy.types.Operator):
    bl_idname = "af.select_vcp_in_tree"
    bl_label = "Select VCP In Tree"

    node_id: bpy.props.StringProperty()
    node_type: bpy.props.EnumProperty(
        items=(
            ("MUSCLE", "Muscle", ""),
            ("FIBER", "Fiber", ""),
        )
    )

    def execute(self, context):
        root = get_af_root(context.scene)
        if root is None:
            return {'CANCELLED'}

        v = root.af_vcp_system
        v.active_vcp_id = self.node_id
        v.active_vcp_type = self.node_type
        return {'FINISHED'}
