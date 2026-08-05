import bpy

from ...app.queries.root import root_for_context
from ...app.queries.topology import topology_panel_state


class AF_PT_TopologyPanel(bpy.types.Panel):
    bl_label = "Topology"
    bl_idname = "AF_PT_topology_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"
    bl_parent_id = "AF_PT_main_panel"

    @classmethod
    def poll(cls, context):
        return topology_panel_state(context).has_root

    def draw(self, context):
        state, root = topology_panel_state(context), root_for_context(context)
        _draw_settings(self.layout, root, state.running)
        if state.running:
            _draw_running(self.layout, context.scene, state)
        else:
            row = self.layout.row(); row.enabled = state.has_skin
            row.operator("af.generate_topology", icon="MOD_REMESH")
            if not state.has_skin:
                self.layout.label(text="Generate Draft Skin first", icon="INFO")
            _draw_message(self.layout, state)


def _draw_settings(layout, root, running):
    box, settings = layout.box(), root.af_topology_settings
    box.label(text="Quad Generation")
    column = box.column(); column.enabled = not running
    column.prop(settings, "target_quad_count")
    column.prop(settings, "refinement_strategy")
    column.prop(settings, "symmetry_mode")
    if settings.symmetry_mode == "CUSTOM":
        column.prop(settings, "custom_origin")
        column.prop(settings, "custom_normal")


def _draw_running(layout, scene, state):
    row = layout.row(); row.enabled = False
    row.prop(scene, "af_topology_progress", text=state.stage, slider=True)
    layout.operator("af.cancel_topology", icon="CANCEL")
    _draw_message(layout, state)


def _draw_message(layout, state):
    if state.message:
        layout.label(text=state.message, icon="INFO")
    if state.diagnostic:
        layout.label(text=f"Log: {state.diagnostic}", icon="TEXT")
