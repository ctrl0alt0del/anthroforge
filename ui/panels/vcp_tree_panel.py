import bpy
from ...core.utils import get_af_root
from ..sections.vcp_tree_section import draw_vcp_tree_section


class AF_PT_VCPTreePanel(bpy.types.Panel):
    bl_label = "VCP Tree"
    bl_idname = "AF_PT_vcp_tree_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"
    bl_parent_id = "AF_PT_main_panel"

    @classmethod
    def poll(cls, context):
        return get_af_root(context.scene) is not None

    def draw(self, context):
        layout = self.layout
        root = get_af_root(context.scene)

        box = layout.box()
        draw_vcp_tree_section(box, context.scene, root)
