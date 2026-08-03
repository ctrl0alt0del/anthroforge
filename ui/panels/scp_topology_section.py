from ...core.topology.budgets import density_errors
from ...core.topology.model import TopologyDensityRule


def draw_topology_density_box(layout, root, scp):
    box = layout.box()
    box.label(text="Topology Density")
    box.prop(scp, "topology_density_mode", text="Mode")
    if scp.topology_density_mode == "SUBTREE_BUDGET":
        box.prop(scp, "topology_subtree_quads", text="Subtree Quads")
    error = _first_error(root)
    if error:
        box.label(text=error, icon="ERROR")


def _first_error(root):
    if root is None:
        return ""
    rules = tuple(_rule(index, item) for index, item in enumerate(root.af_scp_system.scps))
    errors = density_errors(rules, root.af_topology_settings.target_quad_count)
    return errors[0] if errors else ""


def _rule(index, scp):
    return TopologyDensityRule(index, str(scp.id), str(scp.parent_id),
                               str(scp.topology_density_mode), int(scp.topology_subtree_quads))
