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


def _draw_indent(row, depth):
    if depth <= 0:
        return
    indent = row.row(align=True)
    indent.ui_units_x = depth * 1.2
    indent.label(text="")


def _draw_expand_toggle(row, scene, scp_id, has_children, collapsed):
    if has_children:
        icon = "TRIA_RIGHT" if collapsed else "TRIA_DOWN"
        op = row.operator("af.toggle_scp_collapse", text="", icon=icon, emboss=False)
        op.scp_id = scp_id
    else:
        row.label(text="", icon="DOT")


def _draw_visibility_toggle(row, scp_id, isolated_id):
    active = bool(isolated_id and isolated_id == scp_id)
    hidden = bool(isolated_id and isolated_id != scp_id)
    op = row.operator("af.toggle_scp_visibility", text="", icon="HIDE_ON" if hidden else "HIDE_OFF", depress=active)
    op.scp_id = scp_id


def _draw_row_actions(row, scp, selected_ids, depth, isolated_id):
    label = scp.name if scp.name else scp.id
    op = row.operator("af.select_scp_in_tree", text=label, emboss=True, depress=(scp.id in selected_ids))
    op.scp_id = scp.id
    _draw_visibility_toggle(row, scp.id, isolated_id)
    if depth > 0:
        promote_op = row.operator("af.promote_scp_in_tree", text="", icon="TRIA_UP", emboss=False)
        promote_op.scp_id = scp.id
    copy_op = row.operator("af.copy_scp_in_tree", text="", icon="DUPLICATE", emboss=False)
    copy_op.scp_id = scp.id
    delete_op = row.operator("af.delete_scp_in_tree", text="", icon="TRASH", emboss=False)
    delete_op.scp_id = scp.id


def _draw_children(layout, scene, children, children_map, depth, active_id, isolated_id, selected_ids, visited):
    for child in children:
        _draw_node(layout, scene, child, children_map, depth + 1, active_id, isolated_id, selected_ids, visited)


def _draw_node(layout, scene, scp, children_map, depth, active_id, isolated_id, selected_ids, visited):
    if scp.id in visited:
        return
    visited.add(scp.id)
    children = children_map.get(scp.id, [])
    has_children = len(children) > 0
    collapsed = is_collapsed(scene, scp.id)
    row = layout.row(align=True)
    _draw_indent(row, depth)
    _draw_expand_toggle(row, scene, scp.id, has_children, collapsed)
    _draw_row_actions(row, scp, selected_ids, depth, isolated_id)
    if has_children and not collapsed:
        _draw_children(layout, scene, children, children_map, depth, active_id, isolated_id, selected_ids, visited)


def draw_tree_section(layout, scene, root, active_scp_id, isolated_scp_id, selected_scp_ids):
    roots, children_map = _build_tree(root)
    visited = set()

    if not roots:
        layout.label(text="No SCPs")
        return

    for scp in roots:
        _draw_node(layout, scene, scp, children_map, 0, active_scp_id, isolated_scp_id, selected_scp_ids, visited)
