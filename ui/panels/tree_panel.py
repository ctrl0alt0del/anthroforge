import bpy
from ...app.queries.root import has_root
from ...app.queries.tree import tree_panel_state
from ..sections.tree_section import draw_tree_section
from ..sections.vcp_tree_section import draw_vcp_tree_section


def _draw_vcp_box(box, scene, root, selected_fibers, selected_surfaces, selected_muscles, selected_blobs, selected_tissues):
    _ = scene
    box.separator()
    box.label(text="VCPs")
    row = box.row(align=True)
    row.operator("af.add_muscle_vcp", icon="MESH_UVSPHERE")
    row.operator("af.add_soft_tissue_vcp", icon="MOD_CLOTH")
    draw_vcp_tree_section(box, scene, root, selected_fibers, selected_surfaces, selected_muscles, selected_blobs, selected_tissues)


class AF_PT_TreePanel(bpy.types.Panel):
    bl_label = "AF Tree"
    bl_idname = "AF_PT_tree_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"
    bl_parent_id = "AF_PT_main_panel"

    @classmethod
    def poll(cls, context):
        return has_root(context)

    def draw(self, context):
        state = tree_panel_state(context)
        box = self.layout.box()
        box.label(text="SCPs")
        draw_tree_section(box, state.scene, state.root, state.active_scp_id, state.isolated_scp_id, state.selection.scp_ids)
        selected = state.selection
        _draw_vcp_box(box, state.scene, state.root, selected.fiber_ids, selected.fiber_surface_ids, selected.muscle_ids,
                      selected.blob_ids, selected.soft_tissue_ids)
