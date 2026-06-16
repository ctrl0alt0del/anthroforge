import bpy
from ..core.utils import get_af_root


def _draw_attachment_toggle(layout, scene):
    box = layout.box()
    box.label(text="Attachment Runtime")
    box.prop(scene, "af_attachments_enabled", text="Attachments Enabled")
    if not bool(getattr(scene, "af_attachments_enabled", True)):
        box.label(text="Children stay frozen until re-enabled.", icon="PAUSE")


class AF_PT_MainPanel(bpy.types.Panel):
    bl_label = "AnthroForge"
    bl_idname = "AF_PT_main_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"

    def draw(self, context):
        layout = self.layout
        root = get_af_root(context.scene)
        layout.operator("af.import_package", icon="IMPORT")
        _draw_attachment_toggle(layout, context.scene)

        if root is None:
            layout.label(text="No AF_ROOT in scene", icon="ERROR")
            layout.operator("af.create_root", icon="ADD")
        else:
            layout.label(text="AF_ROOT ready", icon="CHECKMARK")
