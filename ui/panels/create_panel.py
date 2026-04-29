import bpy

from ...core.selection import get_active_scp
from ...core.utils import get_af_root
from .scp_create_sections import draw_active_object_box, draw_create_buttons, draw_mirror_box, draw_parent_box
from .scp_objects_panel import draw_scp_object_section


def _draw_active_scp_sections(layout, scene, scp):
    if scp is None:
        return
    layout.separator()
    draw_parent_box(layout, scene, scp)
    draw_mirror_box(layout, scp)
    draw_scp_object_section(layout, scene, scp)


class AF_PT_CreatePanel(bpy.types.Panel):
    bl_label = "SCPs"
    bl_idname = "AF_PT_create_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"
    bl_parent_id = "AF_PT_main_panel"

    @classmethod
    def poll(cls, context):
        return get_af_root(context.scene) is not None

    def draw(self, context):
        root = get_af_root(context.scene)
        draw_active_object_box(self.layout, context.active_object)
        draw_create_buttons(self.layout)
        _draw_active_scp_sections(self.layout, context.scene, get_active_scp(root, context))
