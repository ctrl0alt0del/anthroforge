try:
    from ...ui.tree_state import toggle_collapsed, toggle_vcp_collapsed
except ImportError:
    from ui.tree_state import toggle_collapsed, toggle_vcp_collapsed


def toggle_scp_tree_node(scene, scp_id):
    if not scp_id:
        return False
    toggle_collapsed(scene, scp_id)
    return True


def toggle_vcp_tree_node(scene, node_key):
    if not node_key:
        return False
    toggle_vcp_collapsed(scene, node_key)
    return True
