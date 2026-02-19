import bpy
from ..core.utils import get_af_root


class AF_PT_MainPanel(bpy.types.Panel):
    bl_label = "AnthroForge"
    bl_idname = "AF_PT_main_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"

    def draw(self, context):
        layout = self.layout
        root = get_af_root(context.scene)

        if root is None:
            layout.label(text="No AF_ROOT in scene", icon="ERROR")
            layout.operator("af.create_root", icon="ADD")
        else:
            layout.label(text="AF_ROOT ready", icon="CHECKMARK")
