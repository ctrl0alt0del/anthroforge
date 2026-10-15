from ...app.queries.root import root_for_context
from ...adapters.draft_skin.bounds import model_length, final_muscle


def draw_model(layout, context, running):
    root = root_for_context(context)
    box = layout.box(); box.label(text="Gap Filling")
    box.enabled = not running
    settings = root.af_draft_skin_settings
    box.prop(settings, "gap_limit_percent")
    box.prop(settings, "gap_strength_percent", slider=True)
    _distance_label(box, context, root, settings.gap_limit_percent)
    _draw_active(layout, context, root)


def _draw_active(layout, context, root):
    from ...app.queries.vcp import active_entity
    role, identity = active_entity(context)
    collection = {"MUSCLE": "muscles", "FIBER": "fibers", "BLOB": "blobs", "SOFT_TISSUE": "soft_tissues"}.get(role)
    if collection is None:
        return
    record = next((item for item in getattr(root.af_vcp_system, collection) if item.id == identity), None)
    if record is None:
        return
    muscle = getattr(record, "muscle_id", "") if role == "FIBER" else ""
    if muscle:
        record = final_muscle(root, context.scene, muscle) or record
    draw_contributor(layout, context, record)


def draw_contributor(layout, context, record):
    box = layout.box(); box.label(text="Draft Skin Gap Filling")
    box.prop(record, "skin_gap_mode")
    root = root_for_context(context)
    if record.skin_gap_mode == "OVERRIDE":
        box.prop(record, "skin_gap_limit_percent")
        box.prop(record, "skin_gap_strength_percent", slider=True)
        limit = record.skin_gap_limit_percent
    else:
        settings = root.af_draft_skin_settings; limit = settings.gap_limit_percent
        box.label(text=f"Model: {limit:.4g}% gap, {settings.gap_strength_percent:.4g}% strength")
    _distance_label(box, context, root, limit)


def _distance_label(layout, context, root, percent):
    length = model_length(root, context)
    if not length:
        return
    distance = length * percent / 100
    layout.label(text=f"Resolved limit: {distance:.5g} scene units", icon="INFO")
