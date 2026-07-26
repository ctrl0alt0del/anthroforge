import bpy

from ...app.queries.draft_skin import draft_skin_panel_state


class AF_PT_DraftSkinPanel(bpy.types.Panel):
    bl_label = "Draft Skin"
    bl_idname = "AF_PT_draft_skin_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"
    bl_parent_id = "AF_PT_main_panel"

    @classmethod
    def poll(cls, context):
        return draft_skin_panel_state(context).has_root

    def draw(self, context):
        state = draft_skin_panel_state(context)
        if state.running:
            _draw_running(self.layout, context.scene, state)
        else:
            self.layout.operator("af.generate_draft_skin", icon="MOD_SKIN")
            _draw_message(self.layout, state)


def _draw_running(layout, scene, state):
    row = layout.row()
    row.enabled = False
    row.prop(scene, "af_draft_skin_progress", text=state.stage, slider=True)
    layout.operator("af.cancel_draft_skin", icon="CANCEL")
    _draw_message(layout, state)


def _draw_message(layout, state):
    if state.message:
        layout.label(text=state.message, icon="INFO")
    if state.diagnostic:
        layout.label(text=f"Log: {state.diagnostic}", icon="TEXT")
