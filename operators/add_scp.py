import bpy

from ..app.use_cases.attachment_anchor_lock import clear_active_scp_child_anchor_lock, set_active_scp_child_anchor_lock
from ..app.use_cases.attachment_origin import move_active_origin_to_attachment
from ..app.use_cases.scp_parenting import mark_active_mesh_as_scp, set_active_scp_parent


def _finish(operator, result):
    if result.message:
        operator.report({result.level}, result.message)
    return {"FINISHED"} if result.ok else {"CANCELLED"}


class AF_OT_AddSCP(bpy.types.Operator):
    bl_idname = "af.add_scp"
    bl_label = "Mark Selected Mesh As SCP"
    bl_description = "Mark active mesh object as SCP"

    def execute(self, context):
        return _finish(self, mark_active_mesh_as_scp(context))


class AF_OT_SetSCPParent(bpy.types.Operator):
    bl_idname = "af.set_scp_parent"
    bl_label = "Set SCP Parent"
    bl_description = "Assign or clear parent for active SCP"

    def execute(self, context):
        return _finish(self, set_active_scp_parent(context))


class AF_OT_MoveSCPOriginToAttachment(bpy.types.Operator):
    bl_idname = "af.move_scp_origin_to_attachment"
    bl_label = "Move SCP Origin To Attachment"
    bl_description = "Move the active SCP transform origin to its current attachment point"

    def execute(self, context):
        return _finish(self, move_active_origin_to_attachment(context))


class AF_OT_SetSCPChildAnchorLock(bpy.types.Operator):
    bl_idname = "af.set_scp_child_anchor_lock"
    bl_label = "Set SCP Child Anchor Lock"
    bl_description = "Keep the selected child face or vertex as the permanent attachment anchor until cleared"

    def execute(self, context):
        return _finish(self, set_active_scp_child_anchor_lock(context))


class AF_OT_ClearSCPChildAnchorLock(bpy.types.Operator):
    bl_idname = "af.clear_scp_child_anchor_lock"
    bl_label = "Clear SCP Child Anchor Lock"
    bl_description = "Clear the permanent child attachment anchor for the active SCP"

    def execute(self, context):
        return _finish(self, clear_active_scp_child_anchor_lock(context))
