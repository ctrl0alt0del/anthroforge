import bpy
from ...core.utils import get_af_root
from ...core.shapes.registry import ShapeRegistry
from ..context import get_active_scp


class AF_PT_EditPanel(bpy.types.Panel):
    bl_label = "Edit SCP"
    bl_idname = "AF_PT_edit_panel"
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

        scp = get_active_scp(root, context)
        if not scp:
            layout.label(text="Select SCP from tree or viewport")
            return

        row = layout.row()
        row.prop(scp, "id")

        row = layout.row()
        row.enabled = False
        row.prop(scp, "shape_type", text="Shape")

        layout.separator()
        layout.label(text="Transform")
        layout.prop(scp, "local_origin")
        layout.prop(scp, "local_rotation_euler")
        layout.prop(scp, "local_scale")

        layout.separator()
        layout.label(text="Shape Params")
        ShapeRegistry.draw_scp_ui(scp.shape_type, layout, scp, readonly=True)
        layout.operator("af.delete_selected_scp", icon="TRASH")
