import bpy
from ...app.queries.fiber_create import loop_fiber_create_state, proxy_fiber_create_state, symmetric_loop_fiber_create_state
from ...app.queries.root import has_root


def _draw_standard_box(layout, scene):
    box = layout.box()
    box.label(text="New Fiber")
    box.prop(scene, "af_new_fiber_origin_obj", text="Origin")
    box.prop(scene, "af_new_fiber_insertion_obj", text="Insertion")
    box.operator("af.add_fiber_vcp", icon="ADD")


def _draw_proxy_box(layout, context):
    state = proxy_fiber_create_state(context)
    box = layout.box()
    box.label(text="Connect Vertices with Fiber")
    box.label(text=state.message, icon="CHECKMARK" if state.can_connect else "INFO")
    row = box.row()
    row.enabled = state.can_connect
    row.operator("af.connect_proxy_vertices_with_fiber", icon="MOD_CURVE")


def _draw_loop_box(layout, context):
    state = loop_fiber_create_state(context)
    box = layout.box()
    box.label(text="Create Loop Fiber From Selected Vertices")
    box.label(text=state.message, icon="CHECKMARK" if state.can_connect else "INFO")
    row = box.row()
    row.enabled = state.can_connect
    row.operator("af.create_loop_fiber_from_selected_vertices", icon="CURVE_BEZCIRCLE")


def _draw_symmetric_loop_box(layout, context):
    state = symmetric_loop_fiber_create_state(context)
    box = layout.box()
    box.label(text="Create Symmetric Loop Fiber")
    box.label(text=state.message, icon="CHECKMARK" if state.can_connect else "INFO")
    row = box.row()
    row.enabled = state.can_connect
    row.operator("af.create_symmetric_loop_fiber_from_selected_vertices", icon="MOD_MIRROR")


class AF_PT_FiberCreatePanel(bpy.types.Panel):
    bl_label = "Fiber Creation"
    bl_idname = "AF_PT_fiber_create_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"
    bl_parent_id = "AF_PT_main_panel"

    @classmethod
    def poll(cls, context):
        return has_root(context)

    def draw(self, context):
        _draw_standard_box(self.layout, context.scene)
        _draw_proxy_box(self.layout, context)
        _draw_loop_box(self.layout, context)
        _draw_symmetric_loop_box(self.layout, context)
