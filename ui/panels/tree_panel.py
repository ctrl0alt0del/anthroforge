import bpy
from ...core.utils import get_af_root
from ..context import get_active_scp
from ..sections.tree_section import draw_tree_section


class AF_PT_TreePanel(bpy.types.Panel):
    bl_label = "SCP Tree"
    bl_idname = "AF_PT_tree_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"
    bl_parent_id = "AF_PT_main_panel"

    @classmethod
    def poll(cls, context):
        return get_af_root(context.scene) is not None

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        root = get_af_root(scene)

        active = get_active_scp(root, context)
        active_id = active.id if active else ""

        box = layout.box()
        draw_tree_section(box, scene, root, active_id)
