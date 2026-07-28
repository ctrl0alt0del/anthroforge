from ...core.draft_skin.settings import effective_collagen


def draw_skin_collagen_box(layout, context, scp):
    box = layout.box()
    box.label(text="Draft Skin Collagen")
    box.prop(scp, "skin_collagen_mode", text="Mode")
    mode = str(getattr(scp, "skin_collagen_mode", "AUTO"))
    _draw_value(box, scp, mode)
    box.operator("af.paint_skin_collagen", icon="WPAINT_HLT")
    if mode == "PAINTED":
        _draw_paint_controls(box, context)


def _draw_value(box, scp, mode):
    if mode == "AUTO":
        obj = getattr(scp, "geometry_object_ref", None)
        name = "" if obj is None else obj.name
        value = effective_collagen(mode, scp.skin_collagen, scp.name, name)
        box.label(text=f"Effective Collagen: {value:.3f}", icon="INFO")
        return
    label = "Unpainted Default" if mode == "PAINTED" else "Collagen Amount"
    box.prop(scp, "skin_collagen", text=label, slider=True)


def _draw_paint_controls(box, context):
    unified = context.scene.tool_settings.weight_paint.unified_paint_settings
    box.prop(unified, "weight", text="Brush Weight", slider=True)
    row = box.row(align=True)
    for value, label in ((0.0, "0"), (0.5, "0.5"), (1.0, "1")):
        operator = row.operator("af.set_skin_collagen_brush_weight", text=label)
        operator.weight = value
    box.label(text="Blue 0: tight  |  Red 1: full collagen", icon="INFO")
    _draw_map_actions(box)


def _draw_map_actions(box):
    row = box.row(align=True)
    row.operator("af.fill_skin_collagen", text="Fill Default")
    row.operator("af.clear_skin_collagen", text="Clear Painted Map")
    box.operator("af.finish_skin_collagen_paint", icon="OBJECT_DATAMODE")
