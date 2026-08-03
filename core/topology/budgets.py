from collections import defaultdict

import numpy as np

from .model import TopologyBudgetRegion, TopologyDensityField


def explicit_rules(rules):
    return tuple(rule for rule in rules if rule.mode == "SUBTREE_BUDGET")


def rule_map(rules):
    return {rule.scp_id: rule for rule in rules}


def ancestor_ids(scp_id, rules):
    values, lookup, current = [], rule_map(rules), str(scp_id)
    while current in lookup and lookup[current].parent_id not in values:
        current = lookup[current].parent_id
        if current:
            values.append(current)
    return tuple(values)


def nearest_explicit_parent(rule, rules):
    explicit = {item.scp_id for item in explicit_rules(rules)}
    return next((sid for sid in ancestor_ids(rule.scp_id, rules) if sid in explicit), "")


def explicit_children(rules):
    values = defaultdict(list)
    for rule in explicit_rules(rules):
        values[nearest_explicit_parent(rule, rules)].append(rule)
    return values


def density_errors(rules, total_quads):
    errors, children = [], explicit_children(rules)
    for rule in explicit_rules(rules):
        reserved = sum(item.subtree_quads for item in children.get(rule.scp_id, ()))
        if reserved > rule.subtree_quads:
            errors.append(f"{rule.scp_id} child budgets {reserved} exceed {rule.subtree_quads}.")
    top = sum(item.subtree_quads for item in children.get("", ()))
    if top > int(total_quads):
        errors.append(f"Top-level SCP budgets {top} exceed total {int(total_quads)}.")
    return tuple(errors)


def owner_subtree(owner_index, rule, rules):
    lookup = {item.scp_index: item.scp_id for item in rules}
    owner = lookup.get(int(owner_index), "")
    return owner == rule.scp_id or rule.scp_id in ancestor_ids(owner, rules)


def build_regions(rules, total_quads, owner_indices, vertex_areas):
    errors = density_errors(rules, total_quads)
    if errors:
        raise ValueError(" ".join(errors))
    regions = _explicit_regions(rules, owner_indices, vertex_areas)
    return (*regions, _root_region(rules, total_quads, owner_indices, vertex_areas))


def _explicit_regions(rules, owners, areas):
    children, result = explicit_children(rules), []
    for rule in explicit_rules(rules):
        nested = tuple(item.scp_id for item in children.get(rule.scp_id, ()))
        indices = _exclusive_indices(rule, nested, rules, owners)
        budget = rule.subtree_quads - sum(item.subtree_quads for item in children.get(rule.scp_id, ()))
        result.append(TopologyBudgetRegion(rule.scp_id, rule.subtree_quads, budget,
                                           tuple(indices), float(np.sum(areas[indices]))))
    return tuple(result)


def _exclusive_indices(rule, nested, rules, owners):
    inside = np.asarray([owner_subtree(value, rule, rules) for value in owners])
    for child_id in nested:
        child = next(item for item in rules if item.scp_id == child_id)
        inside &= ~np.asarray([owner_subtree(value, child, rules) for value in owners])
    return np.flatnonzero(inside)


def _root_region(rules, total, owners, areas):
    top = explicit_children(rules).get("", ())
    inside = np.zeros(len(owners), dtype=bool)
    for rule in top:
        inside |= np.asarray([owner_subtree(value, rule, rules) for value in owners])
    indices = np.flatnonzero(~inside)
    budget = int(total) - sum(item.subtree_quads for item in top)
    return TopologyBudgetRegion("", int(total), budget, tuple(indices), float(np.sum(areas[indices])))


def density_field(regions, vertex_count):
    values, warnings = np.zeros(int(vertex_count), dtype=np.float64), []
    for region in regions:
        _assign_region(values, region, warnings)
    positive = values[values > 0]
    values[values <= 0] = float(np.median(positive)) if len(positive) else 1.0
    return TopologyDensityField(values, tuple(regions), tuple(warnings))


def _assign_region(values, region, warnings):
    if not region.owner_indices or region.area <= 0 or region.exclusive_quads <= 0:
        warnings.append(f"Topology density region {region.scp_id or 'root'} has no usable area.")
        return
    edge = np.sqrt(region.area / float(region.exclusive_quads))
    values[np.asarray(region.owner_indices, dtype=np.int64)] = edge


def smooth_target_lengths(values, triangles, areas, regions, iterations=8):
    result, neighbors = np.asarray(values, dtype=np.float64).copy(), _neighbors(len(values), triangles)
    for _unused in range(int(iterations)):
        result = _smooth_log_step(result, neighbors)
        result = _correct_regions(result, areas, regions)
    return result


def _neighbors(count, triangles):
    values = [set() for _ in range(int(count))]
    for face in np.asarray(triangles):
        for first, second in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            values[int(first)].add(int(second)); values[int(second)].add(int(first))
    return values


def _smooth_log_step(values, neighbors):
    logs, result = np.log(np.maximum(values, 1.0e-12)), values.copy()
    for index, linked in enumerate(neighbors):
        if linked:
            result[index] = np.exp(0.65 * logs[index] + 0.35 * np.mean(logs[list(linked)]))
    return result


def _correct_regions(values, areas, regions):
    result = values.copy()
    for region in regions:
        indices = np.asarray(region.owner_indices, dtype=np.int64)
        if not len(indices) or region.exclusive_quads <= 0:
            continue
        predicted = np.sum(areas[indices] / np.maximum(result[indices] ** 2, 1.0e-20))
        result[indices] *= np.sqrt(predicted / float(region.exclusive_quads))
    return result
