import json


def _is_collapsed(scene, key):
    raw = (scene.af_vcp_tree_collapsed_json or "").strip()
    try:
        data = json.loads(raw) if raw else {}
    except Exception:
        data = {}
    return bool(data.get(key, False))


def _build_vcp_tree(root):
    v = root.af_vcp_system
    muscles = list(v.muscles)
    fibers = list(v.fibers)

    by_muscle = {}
    free_fibers = []

    muscle_ids = {m.id for m in muscles}
    for f in fibers:
        if f.muscle_id and f.muscle_id in muscle_ids:
            by_muscle.setdefault(f.muscle_id, []).append(f)
        else:
            free_fibers.append(f)

    return muscles, by_muscle, free_fibers


def _draw_fiber_row(layout, fiber, depth, active_id, active_type):
    row = layout.row(align=True)

    if depth > 0:
        indent = row.row(align=True)
        indent.ui_units_x = depth * 1.2
        indent.label(text="")

    row.label(text="", icon="CURVE_DATA")

    op = row.operator(
        "af.select_vcp_in_tree",
        text=fiber.id,
        emboss=True,
        depress=(active_type == "FIBER" and active_id == fiber.id),
    )
    op.node_id = fiber.id
    op.node_type = "FIBER"

    # Right-side compact endpoint info
    a = fiber.a_parent_id if fiber.a_parent_id else "?"
    b = fiber.b_parent_id if fiber.b_parent_id else "?"
    right = row.row(align=True)
    right.alignment = "RIGHT"
    right.enabled = False
    right.label(text=f"{a} -> {b}")


def _draw_muscle_node(layout, scene, muscle, by_muscle, active_id, active_type):
    node_key = f"MUSCLE:{muscle.id}"
    collapsed = _is_collapsed(scene, node_key)
    children = by_muscle.get(muscle.id, [])

    row = layout.row(align=True)

    icon = "TRIA_RIGHT" if collapsed else "TRIA_DOWN"
    op = row.operator("af.toggle_vcp_collapse", text="", icon=icon, emboss=False)
    op.node_key = node_key

    op = row.operator(
        "af.select_vcp_in_tree",
        text=muscle.name or muscle.id,
        emboss=True,
        depress=(active_type == "MUSCLE" and active_id == muscle.id),
    )
    op.node_id = muscle.id
    op.node_type = "MUSCLE"

    right = row.row(align=True)
    right.alignment = "RIGHT"
    right.enabled = False
    right.label(text="MUSCLE")

    if not collapsed:
        for f in children:
            _draw_fiber_row(layout, f, depth=1, active_id=active_id, active_type=active_type)


def draw_vcp_tree_section(layout, scene, root):
    v = root.af_vcp_system
    active_id = v.active_vcp_id
    active_type = v.active_vcp_type

    muscles, by_muscle, free_fibers = _build_vcp_tree(root)

    if not muscles and not free_fibers:
        layout.label(text="No VCPs")
        return

    for m in muscles:
        _draw_muscle_node(layout, scene, m, by_muscle, active_id, active_type)

    for f in free_fibers:
        _draw_fiber_row(layout, f, depth=0, active_id=active_id, active_type=active_type)
