import bpy
from ..core.utils import get_af_root
from ..ui.tree_state import toggle_collapsed


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
        for i, scp in enumerate(root.af_system.scps):
            if scp.id == self.scp_id:
                target_index = i
                break

        if target_index < 0:
            return {'CANCELLED'}

        # This triggers existing active index callback -> viewport proxy select
        root.af_system.active_scp_index = target_index
        return {'FINISHED'}
