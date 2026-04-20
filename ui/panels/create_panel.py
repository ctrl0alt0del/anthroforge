import bpy

from ...core.utils import get_af_root
from .scp_create_sections import active_scp_prop, draw_active_object_box, draw_delete_button, draw_mark_button, draw_mirror_box, draw_parent_box, is_marked_scp_obj


class AF_PT_CreatePanel(bpy.types.Panel):
    bl_label = "SCP Marking"
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
        obj = context.active_object
        draw_active_object_box(self.layout, obj)
        draw_mark_button(self.layout)
        if not is_marked_scp_obj(obj):
            return
        scp = active_scp_prop(root, obj)
        self.layout.separator()
        draw_delete_button(self.layout, obj)
        draw_parent_box(self.layout, context.scene, scp)
        if scp is not None:
            draw_mirror_box(self.layout, scp)
