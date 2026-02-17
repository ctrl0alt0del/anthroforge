import bpy


class AF_PT_MainPanel(bpy.types.Panel):
    bl_label = "AnthroForge"
    bl_idname = "AF_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'AnthroForge'

    def draw(self, context):
        layout = self.layout
        layout.operator("af.create_root")
