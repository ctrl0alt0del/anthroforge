import bpy
from ...core.utils import get_af_root
from ..sections.vcp_tree_section import draw_vcp_tree_section


def _selected_vcp_ids(context, root):
    sel_fibers = set()
    sel_muscles = set()

    for obj in context.selected_objects:
        if obj.get("af_root_name") != root.name:
            continue
        if obj.get("af_fiber_proxy") and obj.get("af_fiber_id"):
            sel_fibers.add(obj.get("af_fiber_id"))
        if obj.get("af_muscle_proxy") and obj.get("af_muscle_id"):
            sel_muscles.add(obj.get("af_muscle_id"))

    return sel_fibers, sel_muscles


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

        # Create muscle from currently selected fibers
        layout.operator("af.add_muscle_vcp", icon="MESH_UVSPHERE")

        sel_fibers, sel_muscles = _selected_vcp_ids(context, root)

        box = layout.box()
        draw_vcp_tree_section(box, context.scene, root, sel_fibers, sel_muscles)
