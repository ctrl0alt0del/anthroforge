import bpy
from ...core.utils import get_af_root
from ..context import get_active_scp
from ..sections.tree_section import draw_tree_section
from ..sections.vcp_tree_section import draw_vcp_tree_section


def _selected_scp_ids(context, root):
    out = set()
    for obj in context.selected_objects:
        if obj.get("af_proxy") and obj.get("af_root_name") == root.name and obj.get("af_scp_id"):
            out.add(obj.get("af_scp_id"))
    return out


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


class AF_PT_TreePanel(bpy.types.Panel):
    bl_label = "AF Tree"
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
        selected_scp = _selected_scp_ids(context, root)
        selected_fibers, selected_muscles = _selected_vcp_ids(context, root)

        box = layout.box()
        box.label(text="SCPs")
        draw_tree_section(box, scene, root, active_id, selected_scp)
        
        box.separator()
        box.label(text="VCPs")
        box.operator("af.add_muscle_vcp", icon="MESH_UVSPHERE")
        draw_vcp_tree_section(box, scene, root, selected_fibers, selected_muscles)
