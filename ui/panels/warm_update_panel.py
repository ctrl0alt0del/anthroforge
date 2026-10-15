import bpy

from ...app.queries.root import root_for_context


class AF_PT_WarmUpdatePanel(bpy.types.Panel):
    bl_label = "Output Update"
    bl_idname = "AF_PT_warm_update_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"
    bl_parent_id = "AF_PT_main_panel"

    @classmethod
    def poll(cls, context):
        return root_for_context(context) is not None

    def draw(self, context):
        scene = context.scene
        root = root_for_context(context)
        if scene.af_warm_update_running:
            _draw_running(self.layout, scene); return
        if root.get("af_deformation_reference") is not None:
            _draw_deformation(self.layout,root); return
        _draw_migration(self.layout, context)
        _button(self.layout, "Update Skin & Topology", "AUTO", "FILE_REFRESH")
        row = self.layout.row(align=True)
        _button(row, "Force Rebuild Skin", "FORCE_SKIN", "MOD_SKIN")
        _button(row, "Force Rebuild Topology", "FORCE_TOPOLOGY", "MOD_REMESH")
        _draw_last(self.layout, scene)


def _button(layout, text, mode, icon):
    operator = layout.operator("af.update_skin_topology", text=text, icon=icon)
    operator.mode = mode


def _draw_deformation(layout, root):
    layout.prop(root.af_topology_settings,"deformation_method")
    layout.label(text=root.get("af_deformation_status","Ready"))
    layout.label(text=f"Issues: {root.get('af_deformation_issue_count',0)} (see Issues panel)")
    if root.get("af_deformation_construction_stale"):
        layout.label(text="Construction settings changed; explicit rebuild required",icon="INFO")
    row = layout.row(align=True)
    row.operator("af.update_final_skin",icon="FILE_REFRESH")
    row.operator("af.cancel_final_skin",icon="CANCEL")
    layout.operator("af.initialize_final_skin",text="Reinitialize Reference",icon="MOD_DATA_TRANSFER")
    _button(layout,"Rebuild Skin & Topology","FORCE_FULL","MOD_REMESH")
    if root.get("af_deformation_seconds") is not None:
        layout.label(text=f"Last update: {root['af_deformation_seconds']:.2f}s")


def _draw_migration(layout, context):
    root = root_for_context(context)
    _button(layout,"Build Skin & Topology","FORCE_FULL","MOD_REMESH")
    layout.operator("af.initialize_final_skin",icon="MOD_DATA_TRANSFER")
    if root.get("af_deformation_status"):
        layout.label(text=root["af_deformation_status"],icon="INFO")
        layout.operator("af.cancel_final_skin",icon="CANCEL")
    from ...adapters.warm_update.migration import migration_state
    state = migration_state(root, context.scene)
    if any(state.values()):
        _button(layout, "Prepare Warm Start", "PREPARE", "MOD_DATA_TRANSFER")
        missing = ", ".join(name for name, value in state.items() if value)
        layout.label(text=f"Bindings missing: {missing}", icon="INFO")


def _draw_running(layout, scene):
    row = layout.row(); row.enabled = False
    row.prop(scene, "af_warm_update_progress", text=scene.af_warm_update_stage, slider=True)
    layout.operator("af.cancel_warm_update", icon="CANCEL")
    if scene.af_warm_update_message:
        layout.label(text=scene.af_warm_update_message, icon="INFO")


def _draw_last(layout, scene):
    if scene.af_last_update_type:
        layout.label(text=f"Last: {scene.af_last_update_type} ({scene.af_last_update_seconds:.2f}s)")
    if scene.af_last_update_diagnostic:
        layout.label(text=scene.af_last_update_diagnostic, icon="ERROR")
    if scene.af_warm_update_message:
        layout.label(text=scene.af_warm_update_message, icon="INFO")
    if scene.af_warm_update_diagnostic:
        layout.label(text=f"Log: {scene.af_warm_update_diagnostic}", icon="TEXT")
