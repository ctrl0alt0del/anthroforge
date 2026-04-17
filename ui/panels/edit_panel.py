import bpy


class AF_PT_EditPanel(bpy.types.Panel):
    bl_label = "Edit SCP"
    bl_idname = "AF_PT_edit_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"
    bl_parent_id = "AF_PT_main_panel"

    @classmethod
    def poll(cls, context):
        _ = context
        # Old SCP edit UI is intentionally disabled in the rewritten SCP system.
        return False

    def draw(self, context):
        _ = context
        self.layout.label(text="Disabled")
