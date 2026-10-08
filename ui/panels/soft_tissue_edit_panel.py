import bpy

from ...app.queries.root import root_for_context
from ...app.queries.vcp import active_soft_tissue_from_context, has_active_entity
from ...core.vcp.runtime_state import soft_tissue_diagnostic, soft_tissue_status, soft_tissue_solve_report
from ...core.vcp.surface_target import effective_tissue_target


class AF_PT_SoftTissueEditPanel(bpy.types.Panel):
    bl_label = "Edit Soft Tissue VCP"
    bl_idname = "AF_PT_soft_tissue_edit_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AnthroForge"
    bl_parent_id = "AF_PT_main_panel"

    @classmethod
    def poll(cls, context):
        return root_for_context(context) is not None and has_active_entity(context, "SOFT_TISSUE")

    def draw(self, context):
        tissue = active_soft_tissue_from_context(context)
        if tissue is None:
            self.layout.label(text="Soft tissue not found")
            return
        _draw_identity(self.layout, tissue)
        _draw_base(self.layout, tissue)
        _draw_target(self.layout, context, tissue)
        _draw_inflation(self.layout, tissue)
        _draw_relaxation(self.layout, tissue)
        _draw_material(self.layout, tissue)
        _draw_attachments(self.layout, tissue)
        _draw_solver(self.layout, tissue)
        _draw_actions(self.layout, tissue)
        _draw_status(self.layout, tissue)


def _draw_identity(layout, tissue):
    box = layout.box()
    box.label(text="Identity")
    box.prop(tissue, "name")
    box.label(text=f"Preset: {str(tissue.preset).replace('_', ' ').title()}")
    box.operator_menu_enum("af.apply_soft_tissue_preset", "preset", text="Apply Preset")
    box.prop(tissue, "auto_recompute")


def _draw_base(layout, tissue):
    box = layout.box()
    box.label(text="Base")
    box.label(text=f"Source: {str(tissue.base_source_type).replace('_', ' ').title()}")
    if str(tissue.base_source_type) == "OBJECT":
        box.prop(tissue, "base_object_ref")
    else:
        box.label(text=f"ID: {tissue.base_source_id}")
    box.label(text=f"Domain: {str(tissue.base_domain).title()} (inferred)")
    box.prop(tissue, "base_resolution")


def _draw_target(layout, context, tissue):
    box, target = layout.box(), effective_tissue_target(tissue)
    box.label(text="Attachment Target")
    label = "None" if target.kind.value == "NONE" else f"{target.kind.value}: {target.entity_id}"
    box.label(text=label)
    if target.kind.value != "NONE":
        box.label(text=target.surface.value.replace("_", " ").title())
    box.prop(context.scene, "af_new_soft_tissue_target_obj", text="Assign From")
    row = box.row(align=True)
    _target_operator(row, "af.assign_soft_tissue_target", "LINKED", tissue.id)
    _target_operator(row, "af.select_soft_tissue_target", "RESTRICT_SELECT_OFF", tissue.id)
    _target_operator(row, "af.clear_soft_tissue_target", "UNLINKED", tissue.id)
    message = "Object base follows target controls." if tissue.base_source_type == "OBJECT" else "Upstream Fiber source remains independently driven."
    box.label(text=message, icon="INFO")


def _target_operator(row, operator, icon, tissue_id):
    row.operator(operator, icon=icon).tissue_id = tissue_id


def _draw_inflation(layout, tissue):
    box = layout.box()
    box.label(text="Inflation")
    box.label(text=f"Construction: {str(tissue.inflation_mode).title()} (from domain)")
    for key in _inflation_fields(tissue):
        box.prop(tissue, key)


def _inflation_fields(tissue):
    common = ["inflation_amount"]
    curve = ["profile_width", "profile_power", "profile_segments", "endpoint_taper"]
    surface = ["minimum_amount", "field_attribute", "field_power"]
    if tissue.base_domain == "POINT":
        return common + ["axis_scale"]
    return common + (curve if tissue.base_domain == "CURVE" else surface)


def _draw_relaxation(layout, tissue):
    box = layout.box()
    box.label(text="Relaxation")
    if tissue.relaxation_mode == "NONE":
        box.prop(tissue, "relaxation_mode")
        return
    fields = ("relaxation_mode", "sagginess", "gravity")
    fields += () if _is_surface_static(tissue) else ("sag_limit",)
    for key in fields:
        box.prop(tissue, key)
    if _is_surface_static(tissue):
        step = 0.0015 * float(tissue.sagginess) / 0.58
        box.label(text=f"Gravity step: {step:.6f}")
        box.label(text="Amount sets volume and size-dependent load", icon="INFO")
        box.label(text="Shape retention sets envelope tension", icon="INFO")


def _is_surface_static(tissue):
    return tissue.base_domain == "SURFACE" and tissue.relaxation_mode == "STATIC_PBD"


def _draw_material(layout, tissue):
    if tissue.relaxation_mode == "NONE" or (tissue.relaxation_mode == "GEOMETRIC" and tissue.base_domain != "POINT"):
        return
    box = layout.box()
    box.label(text="Material")
    box.prop(tissue, "shape_retention")
    if tissue.relaxation_mode == "STATIC_PBD":
        box.prop(tissue, "volume_retention")
    if _is_surface_static(tissue):
        box.prop(tissue, "surface_slack")


def _draw_solver(layout, tissue):
    if tissue.relaxation_mode != "STATIC_PBD":
        if tissue.relaxation_mode == "GEOMETRIC" and tissue.base_domain == "POINT":
            layout.prop(tissue, "iterations")
        return
    box = layout.box()
    box.label(text="Solver")
    for key in ("iterations", "constraint_passes", "tolerance"):
        box.prop(tissue, key)
    effective = _effective_tolerance(tissue)
    if effective < float(tissue.tolerance):
        box.label(text=f"Effective tolerance: {effective:.3g}", icon="INFO")


def _effective_tolerance(tissue):
    step = 0.0015 * float(tissue.sagginess) / 0.58
    return float(tissue.tolerance) if step <= 0.0 else min(float(tissue.tolerance), step * 0.01)


def _draw_attachments(layout, tissue):
    box = layout.box()
    box.label(text="Attachments")
    box.operator("af.add_soft_tissue_attachment", icon="ADD")
    if _is_surface_static(tissue):
        box.label(text="Backing is structurally fixed; overlapping masks stay pinned.", icon="INFO")
    for index, row in enumerate(tissue.attachments):
        _draw_attachment_row(box, tissue, row, index)


def _draw_attachment_row(box, tissue, row, index):
    col = box.column(align=True)
    col.prop(row, "mask_attribute")
    col.operator("af.select_soft_tissue_attachment_mask", icon="VIEWZOOM").index = index
    col.operator("af.remove_soft_tissue_attachment", icon="REMOVE").index = index
    controls = col.column(align=True)
    controls.enabled = tissue.relaxation_mode != "NONE" and not (_is_surface_static(tissue) and row.mask_attribute.upper() == "BACKING")
    controls.prop(row, "mode")
    tether = controls.column(align=True)
    tether.enabled = effective_tissue_target(tissue).kind.value != "NONE"
    if row.mode == "SOFT" or row.feather > 0:
        tether.prop(row, "strength")
    tether.prop(row, "feather")
    tether.prop(row, "normal_offset")


def _draw_actions(layout, tissue):
    row = layout.row(align=True)
    row.operator("af.recompute_soft_tissue", icon="FILE_REFRESH")
    row.operator("af.rebind_soft_tissue", icon="LINKED")
    row = layout.row(align=True)
    row.operator("af.select_soft_tissue_base", icon="RESTRICT_SELECT_OFF")
    row.operator("af.duplicate_soft_tissue_snapshot", icon="DUPLICATE")
    layout.prop(tissue, "show_rest")


def _draw_status(layout, tissue):
    milliseconds, iterations, displacement, error = soft_tissue_diagnostic(tissue)
    box = layout.box()
    box.label(text=f"Status: {soft_tissue_status(tissue)}")
    report = soft_tissue_solve_report(tissue)
    if report["status"] == "ITERATION_LIMIT":
        box.label(text="Iteration limit reached; output is current but unconverged.", icon="ERROR")
    box.label(text=f"{milliseconds:.1f} ms, {iterations} iterations")
    box.label(text=f"Max displacement: {displacement:.6g}")
    if error:
        box.label(text=error, icon="ERROR")
