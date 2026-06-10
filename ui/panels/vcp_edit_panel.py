import bpy
from ...app.queries.root import root_for_context
from ...app.queries.vcp import active_muscle_from_context, has_active_entity


class AF_PT_VCPEditPanel(bpy.types.Panel):
    bl_label = "Edit Muscle VCP"
    bl_idname = "AF_PT_vcp_edit_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"
    bl_parent_id = "AF_PT_main_panel"

    @classmethod
    def poll(cls, context):
        return root_for_context(context) is not None and has_active_entity(context, "MUSCLE")

    def _draw_identity(self, layout, muscle):
        row = layout.row()
        row.enabled = False
        row.prop(muscle, "id", text="ID")
        layout.prop(muscle, "name", text="Name")
        layout.prop(muscle, "closed_v", text="Closed Ring (V)")

    def _draw_inflation(self, layout, muscle):
        infl = layout.box()
        infl.label(text="Inflation")
        infl.prop(muscle, "inflation_enabled", text="Enabled")
        col = infl.column()
        col.enabled = muscle.inflation_enabled
        col.prop(muscle, "inflation_max_value", text="Max Inflation")
        col.prop(muscle, "inflation_falloff_type", text="Falloff")
        col.prop(muscle, "inflation_falloff_radius", text="Radius")
        col.prop(muscle, "inflation_direction_depth", text="Direction Depth (L)")
        col.prop(muscle, "inflation_boundary_strength", text="Boundary Strength")
        col.prop(muscle, "inflation_boundary_band", text="Boundary Band")
        col.prop(muscle, "inflation_boundary_power", text="Boundary Power")
        pick = infl.operator("af.select_muscle_inflation_ctrl", icon="RESTRICT_SELECT_OFF")
        pick.muscle_id = muscle.id
        return infl

    def _draw_actions(self, layout, infl, muscle):
        op = layout.operator("af.flip_muscle_normals", icon="ARROW_LEFTRIGHT")
        op.muscle_id = muscle.id
        info = infl.column()
        info.enabled = False
        info.label(text="Move gizmo in viewport:")
        info.label(text=f"AF_{muscle.id}_INFL_MAX")

    def draw(self, context):
        layout = self.layout
        muscle = active_muscle_from_context(context)
        if muscle is None:
            layout.label(text="Muscle not found")
            return

        self._draw_identity(layout, muscle)
        infl = self._draw_inflation(layout, muscle)
        self._draw_actions(layout, infl, muscle)
