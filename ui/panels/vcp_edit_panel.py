import bpy
from ...app.queries.root import root_for_context
from ...app.queries.vcp import active_muscle_from_context, has_active_entity
from ...core.visualization.muscle_inflation_modes import CTRL_POINT_MODE, muscle_inflation_mode


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
        if str(getattr(muscle, "surface_source_mode", "LEGACY_FIBERS")) == "LEGACY_FIBERS":
            layout.prop(muscle, "closed_v", text="Closed Ring (V)")
            layout.prop(muscle, "use_mirrored_rows", text="Use Mirrored Rows")
        else:
            layout.label(text=f"Fiber Surface: {muscle.fiber_surface_id}")

    def _draw_inflation(self, layout, muscle):
        infl = layout.box()
        infl.label(text="Inflation")
        infl.prop(muscle, "inflation_enabled", text="Enabled")
        infl.prop(muscle, "inflation_mode", text="Mode")
        col = infl.column()
        col.enabled = muscle.inflation_enabled
        self._draw_shared_inflation(col, muscle)
        self._draw_point_inflation(col, muscle)
        self._draw_distributed_inflation(col, muscle)
        self._draw_inflation_pick(infl, muscle)
        return infl

    def _draw_actions(self, layout, infl, muscle):
        op = layout.operator("af.flip_muscle_normals", icon="ARROW_LEFTRIGHT")
        op.muscle_id = muscle.id
        if str(getattr(muscle, "surface_source_mode", "LEGACY_FIBERS")) == "LEGACY_FIBERS":
            convert = layout.operator("af.convert_muscle_to_fiber_surface", icon="MESH_GRID")
            convert.muscle_id = muscle.id
        if muscle_inflation_mode(muscle) != CTRL_POINT_MODE:
            return
        info = infl.column()
        info.enabled = False
        info.label(text="Move gizmo in viewport:")
        info.label(text=f"AF_{muscle.id}_INFL_MAX")

    def _draw_shared_inflation(self, layout, muscle):
        layout.prop(muscle, "inflation_max_value", text="Max Inflation")
        layout.prop(muscle, "inflation_boundary_strength", text="Boundary Strength")
        layout.prop(muscle, "inflation_boundary_band", text="Boundary Band")
        layout.prop(muscle, "inflation_boundary_power", text="Boundary Power")

    def _draw_point_inflation(self, layout, muscle):
        if muscle_inflation_mode(muscle) != CTRL_POINT_MODE:
            return
        layout.prop(muscle, "inflation_falloff_type", text="Falloff")
        layout.prop(muscle, "inflation_falloff_radius", text="Radius")
        layout.prop(muscle, "inflation_direction_depth", text="Direction Depth (L)")

    def _draw_distributed_inflation(self, layout, muscle):
        if muscle_inflation_mode(muscle) == CTRL_POINT_MODE:
            return
        layout.prop(muscle, "inflation_length_taper_band", text="Length Taper Band")

    def _draw_inflation_pick(self, layout, muscle):
        if muscle_inflation_mode(muscle) != CTRL_POINT_MODE:
            return
        pick = layout.operator("af.select_muscle_inflation_ctrl", icon="RESTRICT_SELECT_OFF")
        pick.muscle_id = muscle.id

    def draw(self, context):
        layout = self.layout
        muscle = active_muscle_from_context(context)
        if muscle is None:
            layout.label(text="Muscle not found")
            return

        self._draw_identity(layout, muscle)
        infl = self._draw_inflation(layout, muscle)
        self._draw_actions(layout, infl, muscle)
