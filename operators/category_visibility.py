import bpy

from ..app.use_cases.category_visibility import set_vcp_category_visibility


class AF_OT_SetVCPCategoryVisibility(bpy.types.Operator):
    bl_idname = "af.set_vcp_category_visibility"
    bl_label = "Set VCP Category Visibility"
    bl_description = ("Set object hiding in the active view layer for this root's category; "
                      "collection and global visibility restrictions still apply")

    category: bpy.props.EnumProperty(items=(("MUSCLE", "Muscles", ""), ("FIBER", "Fibers", "")))
    hidden: bpy.props.BoolProperty(default=False)

    def execute(self, context):
        result = set_vcp_category_visibility(context, self.category, self.hidden)
        if result.message:
            self.report({result.level}, result.message)
        return {"FINISHED"} if result.ok else {"CANCELLED"}
