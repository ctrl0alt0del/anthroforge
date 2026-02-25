import bpy
from ...core.utils import get_af_root
from ..context import get_active_af_entity


class AF_PT_VCPEditPanel(bpy.types.Panel):
    bl_label = "Edit Muscle VCP"
    bl_idname = "AF_PT_vcp_edit_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"
    bl_parent_id = "AF_PT_main_panel"

    @classmethod
    def poll(cls, context):
        root_is_valid = get_af_root(context.scene) is not None
        has_vcp_selected = get_active_af_entity(get_af_root(context.scene), context)[0]== "MUSCLE"
        return root_is_valid and has_vcp_selected

    def draw(self, context):
        layout = self.layout
        root = get_af_root(context.scene)
        v = root.af_vcp_system

        if v.active_vcp_type == "FIBER":
            fiber = next((f for f in v.fibers if f.id == v.active_vcp_id), None)
            if fiber is None:
                layout.label(text="Fiber not found")
                return
            row = layout.row()
            row.enabled = False
            row.prop(fiber, "id", text="ID")
            layout.prop(fiber, "name", text="Name")
            return

        if v.active_vcp_type == "MUSCLE":
            muscle = next((m for m in v.muscles if m.id == v.active_vcp_id), None)
            if muscle is None:
                layout.label(text="Muscle not found")
                return
            row = layout.row()
            row.enabled = False
            row.prop(muscle, "id", text="ID")
            layout.prop(muscle, "name", text="Name")
            return

        layout.label(text="Select Fiber or Muscle")
