import numpy as np
from scipy.spatial import cKDTree

try:
    from ...core.topology.budgets import build_regions, density_field, explicit_rules, smooth_target_lengths
    from ...core.topology.ownership import assign_ownership, vertex_areas
except ImportError:
    from core.topology.budgets import build_regions, density_field, explicit_rules, smooth_target_lengths
    from core.topology.ownership import assign_ownership, vertex_areas


def build_density(capture):
    ownership = assign_ownership(capture.vertices, capture.triangles,
                                 capture.ownership_sources, capture.density_rules)
    areas = vertex_areas(capture.vertices, capture.triangles)
    regions = build_regions(capture.density_rules, capture.settings.target_quad_count,
                            ownership.owner_indices, areas)
    field = density_field(regions, len(capture.vertices))
    lengths = smooth_target_lengths(field.target_edge_lengths, capture.triangles, areas, regions)
    warnings = (*ownership.warnings, *field.warnings)
    return ownership.owner_indices, lengths, regions, warnings


def has_adaptive_density(capture):
    return bool(explicit_rules(capture.density_rules))


def sample_density(capture, owners, lengths, points):
    indices = cKDTree(capture.vertices).query(np.asarray(points), workers=-1)[1]
    return np.asarray(owners)[indices], np.asarray(lengths)[indices]


def budget_statistics(capture, output_owners, faces, regions):
    face_owners = _face_owners(output_owners, faces)
    values = []
    for region in regions:
        mask = _region_mask(face_owners, region, capture.density_rules)
        values.append({"scp_id": region.scp_id, "requested_subtree_quads": region.requested_quads,
                       "requested_exclusive_quads": region.exclusive_quads,
                       "actual_exclusive_quads": int(np.count_nonzero(mask)), "area": region.area})
    return values


def budget_warnings(statistics, tolerance=0.2):
    warnings = []
    for item in statistics:
        requested = int(item["requested_exclusive_quads"])
        actual = int(item["actual_exclusive_quads"])
        if requested and abs(actual - requested) / requested > tolerance:
            label = item["scp_id"] or "root remainder"
            warnings.append(f"Topology budget for {label} resolved to {actual}/{requested} quads.")
    return tuple(warnings)


def _face_owners(owners, faces):
    values = np.asarray(owners)[np.asarray(faces, dtype=np.int64)]
    return np.asarray([np.bincount(row[row >= 0]).argmax() if np.any(row >= 0) else -1
                       for row in values], dtype=np.int32)


def _region_mask(face_owners, region, rules):
    if region.scp_id == "":
        occupied = set(index for item in regions_for_rules(rules) for index in item)
        return np.asarray([int(value) not in occupied for value in face_owners])
    owner_ids = subtree_owner_indices(region.scp_id, rules)
    child_ids = _nested_override_indices(region.scp_id, rules)
    return np.isin(face_owners, tuple(owner_ids - child_ids))


def regions_for_rules(rules):
    return tuple(subtree_owner_indices(rule.scp_id, rules) for rule in explicit_rules(rules)
                 if not _has_explicit_ancestor(rule, rules))


def subtree_owner_indices(scp_id, rules):
    parents = {rule.scp_id: rule.parent_id for rule in rules}
    return {rule.scp_index for rule in rules if _is_descendant(rule.scp_id, scp_id, parents)}


def _is_descendant(candidate, ancestor, parents):
    current, seen = candidate, set()
    while current and current not in seen:
        if current == ancestor:
            return True
        seen.add(current); current = parents.get(current, "")
    return False


def _has_explicit_ancestor(rule, rules):
    explicit = {item.scp_id for item in explicit_rules(rules)}
    parents, current = {item.scp_id: item.parent_id for item in rules}, rule.parent_id
    while current:
        if current in explicit:
            return True
        current = parents.get(current, "")
    return False


def _nested_override_indices(scp_id, rules):
    direct = [rule for rule in explicit_rules(rules)
              if _nearest_override_parent(rule, rules) == scp_id]
    return set().union(*(subtree_owner_indices(rule.scp_id, rules) for rule in direct)) if direct else set()


def _nearest_override_parent(rule, rules):
    explicit = {item.scp_id for item in explicit_rules(rules)}
    parents, current = {item.scp_id: item.parent_id for item in rules}, rule.parent_id
    while current:
        if current in explicit:
            return current
        current = parents.get(current, "")
    return ""
