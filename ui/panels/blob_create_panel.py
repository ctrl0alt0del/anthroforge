import bpy
from ...core.utils import get_af_root


class AF_PT_BlobCreatePanel(bpy.types.Panel):
    bl_label = "Blob Creation"
    bl_idname = "AF_PT_blob_create_panel"
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

        box = layout.box()
        box.label(text="New Blob")
        box.prop(scene, "af_new_blob_target_obj", text="Target")
        box.operator("af.add_blob_vcp", icon="META_BALL")
