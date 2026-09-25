import bpy

from ...app.queries.root import root_for_context
from ...app.queries.vcp import active_fiber_surface_from_context, has_active_entity
from ...core.vcp.runtime_state import fiber_surface_diagnostic, fiber_surface_status


class AF_PT_FiberSurfaceEditPanel(bpy.types.Panel):
    bl_label = "Edit Fiber Surface"
    bl_idname = "AF_PT_fiber_surface_edit_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"
    bl_parent_id = "AF_PT_main_panel"

    @classmethod
    def poll(cls, context):
        return root_for_context(context) is not None and has_active_entity(context, "FIBER_SURFACE")

    def draw(self, context):
        surface = active_fiber_surface_from_context(context)
        if surface is None:
            return
        _draw_properties(self.layout, surface)
        _draw_actions(self.layout, surface)
        _draw_status(self.layout, surface)


def _draw_properties(layout, surface):
    box = layout.box()
    box.prop(surface, "name")
    box.prop(surface, "construction_mode")
    label = "Flip Assembly Side" if surface.construction_mode == "BRANCHED_LOFT" else "Flip Surface Winding"
    box.prop(surface, "flip_normals", text=label)
    if surface.construction_mode == "LOFT":
        box.prop(surface, "close_across_fibers")
        box.prop(surface, "use_mirrored_rows")
    else:
        box.prop(surface, "patch_resolution")


def _draw_actions(layout, surface):
    row = layout.row(align=True)
    row.operator("af.recompute_fiber_surface", icon="FILE_REFRESH").surface_id = surface.id
    row.operator("af.select_fiber_surface_sources", icon="RESTRICT_SELECT_OFF").surface_id = surface.id
    op = layout.operator("af.create_muscle_from_fiber_surface", icon="MESH_UVSPHERE")
    op.surface_id = surface.id


def _draw_status(layout, surface):
    milliseconds, error = fiber_surface_diagnostic(surface)
    box = layout.box()
    box.label(text=f"Status: {fiber_surface_status(surface)}")
    box.label(text=f"Recompute: {milliseconds:.2f} ms")
    if error:
        box.label(text=error, icon="ERROR")
