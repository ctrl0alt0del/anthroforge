"""Native section controls and current prepared-chart provenance."""
import bpy
from ...app.use_cases.muscle_profile import inspect
from ...core.authoring.profile_config import MODES


def mode_menu(layout, muscle):
    layout.menu("AF_MT_MuscleProfileMode", text=muscle.inflation_mode.replace("_", " ").title())


def draw_mode_options(layout, context):
    from ...operators.muscle_profile import _muscle, MODE_ITEMS
    root, muscle = _muscle(context, "")
    target, _ = inspect(root, context.scene, muscle.id)
    for mode, label, _ in MODE_ITEMS:
        row = layout.row()
        row.enabled = mode != "section_profile" or target.eligible
        op = row.operator("af.muscle_profile_mode", text=label)
        op.mode, op.muscle_id = mode, muscle.id
    for reason in target.reasons:
        layout.label(text=reason, icon="ERROR")


def draw_profile(layout, muscle):
    target, state = inspect(muscle.id_data, bpy.context.scene, muscle.id)
    for message in (*state["reasons"], state["profile_error"]):
        if message:
            layout.label(text=message, icon="ERROR")
    if state["profile_state"] == "uninitialized":
        row = layout.row(); row.enabled = target.eligible
        op = row.operator("af.muscle_profile_mode", text="Initialize Profile")
        op.mode, op.muscle_id = "section_profile", muscle.id
    controls = layout.column()
    controls.enabled = target.eligible and muscle.inflation_enabled and state["profile_state"] == "valid"
    _controls(controls, muscle)
    _reset(layout, muscle, target.eligible)
    _chart(layout, target, muscle.id_data)


def _reset(layout, muscle, eligible):
    row = layout.row()
    row.enabled = eligible
    row.operator("af.muscle_profile_reset", text="Reset Profile...").muscle_id = muscle.id


def _controls(layout, muscle):
    row = layout.row(align=True)
    row.prop(muscle, "section_direction", text="Direction")
    row.operator("af.muscle_profile_side", text="Swap Side").muscle_id = muscle.id
    row = layout.row()
    for label in ("Along", "Depth (world units)", "Peak (0–1)"):
        row.label(text=label)
    for index in range(4):
        row = layout.row(align=True)
        row.label(text=f"{(index+1)*20}%")
        row.prop(muscle, "section_depths", index=index, text="")
        row.prop(muscle, "section_peaks", index=index, text="")
    layout.prop(muscle, "section_roundness")
    layout.operator("af.muscle_profile_scale", text="Scale Depths...").muscle_id = muscle.id


def _chart(layout, target, root):
    from ...core.units import physical_scale_label
    layout.label(text="Start → End follows prepared fiber point order")
    if target.chart:
        for label, row in (("First", target.chart[0]), ("Last", target.chart[-1])):
            mirror = " (mirrored row)" if row["mirrored"] else ""
            layout.label(text=f"{label}: {row['fiber_id']} {row['name']}{mirror}")
    layout.label(text=physical_scale_label(root))
