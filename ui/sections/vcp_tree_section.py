import json


def _fiber_mode(fiber):
    topo = str(getattr(fiber, "topology_mode", "OPEN") or "OPEN")
    gen = str(getattr(fiber, "generation_mode", "SOLVED") or "SOLVED")
    return topo if topo != "LOOP" else ("DERIVED" if gen == "DERIVED" else "LOOP")


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
    blobs = list(v.blobs)

    by_muscle = {}
    free_fibers = []

    muscle_ids = {m.id for m in muscles}
    for f in fibers:
        if f.muscle_id and f.muscle_id in muscle_ids:
            by_muscle.setdefault(f.muscle_id, []).append(f)
        else:
            free_fibers.append(f)

    return muscles, by_muscle, free_fibers, blobs


def _draw_indent(row, depth):
    if depth <= 0:
        return
    indent = row.row(align=True)
    indent.ui_units_x = depth * 1.2
    indent.label(text="")


def _draw_select_op(row, node_id, node_type, label, selected):
    op = row.operator("af.select_vcp_in_tree", text=label, emboss=True, depress=selected)
    op.node_id = node_id
    op.node_type = node_type


def _draw_delete_op(row, node_id, node_type):
    op = row.operator("af.delete_vcp_in_tree", text="", icon="TRASH", emboss=False)
    op.node_id = node_id
    op.node_type = node_type


def _draw_right_hint(row, text):
    right = row.row(align=True)
    right.alignment = "RIGHT"
    right.enabled = False
    right.label(text=text)


def _fiber_hint(fiber):
    if _fiber_mode(fiber) == "DERIVED":
        return f"driver {fiber.driver_fiber_id or '?'}"
    if _fiber_mode(fiber) == "LOOP":
        return f"{len(getattr(fiber, 'loop_anchors', ())) or 0} anchors"
    a = fiber.a_parent_id if fiber.a_parent_id else "?"
    b = fiber.b_parent_id if fiber.b_parent_id else "?"
    return f"{a} -> {b}"


def _draw_fiber_row(layout, fiber, depth, selected_fiber_ids):
    row = layout.row(align=True)
    _draw_indent(row, depth)
    row.label(text="", icon="CURVE_DATA")
    label = fiber.name if getattr(fiber, "name", "") else fiber.id
    _draw_select_op(row, fiber.id, "FIBER", label, fiber.id in selected_fiber_ids)
    _draw_delete_op(row, fiber.id, "FIBER")
    _draw_right_hint(row, _fiber_hint(fiber))


def _draw_blob_row(layout, blob, selected_blob_ids):
    row = layout.row(align=True)
    row.label(text="", icon="META_BALL")
    _draw_select_op(row, blob.id, "BLOB", blob.name or blob.id, blob.id in selected_blob_ids)
    _draw_right_hint(row, "BLOB")


def _draw_muscle_toggle(row, node_key, collapsed):
    icon = "TRIA_RIGHT" if collapsed else "TRIA_DOWN"
    op = row.operator("af.toggle_vcp_collapse", text="", icon=icon, emboss=False)
    op.node_key = node_key


def _draw_muscle_children(layout, children, selected_fiber_ids):
    for fiber in children:
        _draw_fiber_row(layout, fiber, depth=1, selected_fiber_ids=selected_fiber_ids)


def _draw_muscle_node(layout, scene, muscle, by_muscle, selected_muscle_ids, selected_fiber_ids):
    node_key = f"MUSCLE:{muscle.id}"
    collapsed = _is_collapsed(scene, node_key)
    children = by_muscle.get(muscle.id, [])
    row = layout.row(align=True)
    _draw_muscle_toggle(row, node_key, collapsed)
    _draw_select_op(row, muscle.id, "MUSCLE", muscle.name or muscle.id, muscle.id in selected_muscle_ids)
    _draw_delete_op(row, muscle.id, "MUSCLE")
    _draw_right_hint(row, "MUSCLE")
    if not collapsed:
        _draw_muscle_children(layout, children, selected_fiber_ids)


def _draw_blob_rows(layout, blobs, selected_blob_ids):
    for blob in blobs:
        _draw_blob_row(layout, blob, selected_blob_ids)


def draw_vcp_tree_section(layout, scene, root, selected_fiber_ids, selected_muscle_ids, selected_blob_ids):
    muscles, by_muscle, free_fibers, blobs = _build_vcp_tree(root)
    if not muscles and not free_fibers and not blobs:
        layout.label(text="No VCPs")
        return
    for m in muscles:
        _draw_muscle_node(layout, scene, m, by_muscle, selected_muscle_ids, selected_fiber_ids)
    for f in free_fibers:
        _draw_fiber_row(layout, f, depth=0, selected_fiber_ids=selected_fiber_ids)
    if blobs:
        layout.separator()
        _draw_blob_rows(layout, blobs, selected_blob_ids)
