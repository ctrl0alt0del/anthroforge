import bpy

from ...app.queries.root import has_root


class AF_PT_SoftTissueCreatePanel(bpy.types.Panel):
    bl_label = "Soft Tissue Creation"
    bl_idname = "AF_PT_soft_tissue_create_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"
    bl_parent_id = "AF_PT_main_panel"

    @classmethod
    def poll(cls, context):
        return has_root(context)

    def draw(self, context):
        box = self.layout.box()
        box.prop(context.scene, "af_new_soft_tissue_preset")
        box.prop(context.scene, "af_new_soft_tissue_base_obj", text="Base")
        box.label(text="Selected Fiber/Fiber Surface overrides Base", icon="INFO")
        box.prop(context.scene, "af_new_soft_tissue_target_obj", text="Target Surface")
        box.operator("af.add_soft_tissue_vcp", icon="MOD_CLOTH")
