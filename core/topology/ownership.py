from collections import Counter

import numpy as np
from scipy.spatial import cKDTree

from .model import TopologyOwnership


def vertex_areas(vertices, triangles):
    points = np.asarray(vertices)[np.asarray(triangles, dtype=np.int64)]
    areas = 0.5 * np.linalg.norm(np.cross(points[:, 1] - points[:, 0],
                                         points[:, 2] - points[:, 0]), axis=1)
    values = np.zeros(len(vertices), dtype=np.float64)
    for corner in range(3):
        np.add.at(values, np.asarray(triangles)[:, corner], areas / 3.0)
    return values


def assign_ownership(vertices, triangles, sources, rules):
    if not sources or not rules:
        return TopologyOwnership(np.full(len(vertices), -1, dtype=np.int32), len(vertices),
                                 ("Topology ownership has no SCP sources.",))
    nearest = _nearest_sources(vertices, sources)
    owners, fallback = _resolve_sources(vertices, nearest, sources, rules)
    cleaned = clean_islands(owners, triangles, vertex_areas(vertices, triangles))
    warnings = () if not fallback else (f"Used nearest-SCP fallback for {fallback} skin vertices.",)
    return TopologyOwnership(cleaned, fallback, warnings)


def _nearest_sources(vertices, sources):
    points, labels = [], []
    for index, source in enumerate(sources):
        samples = _source_samples(source)
        points.append(samples); labels.extend([index] * len(samples))
    nearest = cKDTree(np.vstack(points)).query(vertices, workers=-1)[1]
    return np.asarray(labels, dtype=np.int32)[nearest]


def _source_samples(source):
    vertices = np.asarray(source.vertices, dtype=np.float64)
    faces = np.asarray(source.triangles, dtype=np.int64)
    return np.vstack((vertices, vertices[faces].mean(axis=1)))


def _resolve_sources(vertices, nearest, sources, rules):
    rule_indices = {rule.scp_id: rule.scp_index for rule in rules}
    trees = _scp_trees(sources)
    owners = np.full(len(vertices), -1, dtype=np.int32)
    for source_index in np.unique(nearest):
        mask = np.flatnonzero(nearest == source_index)
        candidates = tuple(sid for sid in sources[int(source_index)].owner_scp_ids if sid in rule_indices)
        resolved = _resolve_candidates(vertices[mask], candidates, trees, rule_indices)
        owners[mask] = resolved[0]
    owners, extra = _fallback_owners(vertices, owners, trees, rule_indices)
    return owners, extra


def _scp_trees(sources):
    return {source.entity_id: cKDTree(_source_samples(source)) for source in sources
            if source.entity_type == "SCP" and len(source.vertices)}


def _resolve_candidates(points, candidates, trees, indices):
    valid = tuple(sid for sid in candidates if sid in trees)
    if not valid:
        return np.full(len(points), -1, dtype=np.int32), valid
    distances = np.column_stack([trees[sid].query(points, workers=-1)[0] for sid in valid])
    selected = np.argmin(distances, axis=1)
    return np.asarray([indices[valid[index]] for index in selected], dtype=np.int32), valid


def _fallback_owners(vertices, owners, trees, indices):
    missing, ids = np.flatnonzero(owners < 0), tuple(sorted(trees))
    if not len(missing) or not ids:
        return owners, int(len(missing))
    distances = np.column_stack([trees[sid].query(vertices[missing], workers=-1)[0] for sid in ids])
    owners[missing] = np.asarray([indices[ids[index]] for index in np.argmin(distances, axis=1)])
    return owners, int(len(missing))


def clean_islands(owners, triangles, areas, ratio=0.0005):
    values, adjacency = np.asarray(owners).copy(), _adjacency(len(owners), triangles)
    threshold = max(float(np.sum(areas)) * ratio, 0.0)
    for component in _components(values, adjacency):
        if float(np.sum(areas[list(component)])) < threshold:
            _replace_component(values, component, adjacency)
    return values


def _adjacency(count, triangles):
    values = [set() for _ in range(int(count))]
    for face in np.asarray(triangles):
        for first, second in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
            values[int(first)].add(int(second)); values[int(second)].add(int(first))
    return values


def _components(labels, adjacency):
    pending = set(range(len(labels)))
    while pending:
        first = pending.pop(); component, stack = {first}, [first]
        while stack:
            linked = {item for item in adjacency[stack.pop()] if item in pending and labels[item] == labels[first]}
            pending.difference_update(linked); component.update(linked); stack.extend(linked)
        yield component


def _replace_component(labels, component, adjacency):
    boundary = [item for vertex in component for item in adjacency[vertex] if item not in component]
    if not boundary:
        return
    replacement = Counter(int(labels[item]) for item in boundary).most_common(1)[0][0]
    labels[np.asarray(tuple(component), dtype=np.int64)] = replacement
