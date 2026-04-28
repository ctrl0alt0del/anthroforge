import bpy

from ..core.scp_runtime.actions import (
    execute_mark_scp,
    execute_set_scp_parent,
)


class AF_OT_AddSCP(bpy.types.Operator):
    bl_idname = "af.add_scp"
    bl_label = "Mark Selected Mesh As SCP"
    bl_description = "Mark active mesh object as SCP"

    def execute(self, context):
        return execute_mark_scp(self, context)


class AF_OT_SetSCPParent(bpy.types.Operator):
    bl_idname = "af.set_scp_parent"
    bl_label = "Set SCP Parent"
    bl_description = "Assign or clear parent for active SCP"

    def execute(self, context):
        return execute_set_scp_parent(self, context)
