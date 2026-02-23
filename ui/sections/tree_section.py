from ..tree_state import is_collapsed


def _build_tree(root):
    scps = list(root.af_scp_system.scps)
    valid_ids = {s.id for s in scps}
    children_map = {}
    roots = []

    for scp in scps:
        pid = scp.parent_id if scp.parent_id in valid_ids else ""
        if pid:
            children_map.setdefault(pid, []).append(scp)
        else:
            roots.append(scp)

    return roots, children_map


def _draw_node(layout, scene, scp, children_map, depth, active_id, visited):
    if scp.id in visited:
        return
    visited.add(scp.id)

    children = children_map.get(scp.id, [])
    has_children = len(children) > 0
    collapsed = is_collapsed(scene, scp.id)

    row = layout.row(align=True)

    if depth > 0:
        indent = row.row(align=True)
        indent.ui_units_x = depth * 1.2
        indent.label(text="")

    if has_children:
        icon = "TRIA_RIGHT" if collapsed else "TRIA_DOWN"
        op = row.operator("af.toggle_scp_collapse", text="", icon=icon, emboss=False)
        op.scp_id = scp.id
    else:
        row.label(text="", icon="DOT")

    op = row.operator(
        "af.select_scp_in_tree",
        text=scp.id,
        emboss=True,
        depress=(scp.id == active_id),
    )
    op.scp_id = scp.id

    del_op = row.operator("af.delete_selected_af_node", text="", icon="TRASH", emboss=False)
    del_op.target_type = "SCP"
    del_op.target_id = scp.id

    right = row.row()
    right.alignment = "RIGHT"
    right.enabled = False  # lighter/grey text look
    right.label(text=scp.shape_type)

    if has_children and not collapsed:
        for child in children:
            _draw_node(layout, scene, child, children_map, depth + 1, active_id, visited)


def draw_tree_section(layout, scene, root, active_scp_id):
    roots, children_map = _build_tree(root)
    visited = set()

    if not roots:
        layout.label(text="No SCPs")
        return

    for scp in roots:
        _draw_node(layout, scene, scp, children_map, 0, active_scp_id, visited)
