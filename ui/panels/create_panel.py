import bpy
from ...core.utils import get_af_root
from ...core.shapes.registry import ShapeRegistry


class AF_PT_CreatePanel(bpy.types.Panel):
    bl_label = "SCP Creation"
    bl_idname = "AF_PT_create_panel"
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

        layout.prop(scene, "af_scp_type", text="Shape")

        # Global mesh asset registration
        lib = layout.box()
        lib.label(text="SCP Mesh Library")
        lib.prop(scene, "af_new_scp_source_mesh_obj", text="Source Mesh")
        
        lib.operator("af.register_mesh_scp_asset", icon="ADD")

        box = layout.box()
        box.label(text="New SCP Params")
        box.prop(scene, "af_new_parent_obj", text="Parent")
        ShapeRegistry.draw_creation_ui(scene.af_scp_type, box, scene)

        layout.operator("af.add_scp", icon="ADD")
