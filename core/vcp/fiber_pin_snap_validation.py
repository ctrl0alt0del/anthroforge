"""Native collision and local-exit qualification for authored Fiber pins."""
from dataclasses import replace
import numpy as np
from . import fiber_pin_repair as repair
from .v2 import planner as planner
from .v2.planner_anchor_access import _anchor_candidates, _validated_candidates


def triangle_components(triangles):
    links = {}
    for index, triangle in enumerate(triangles):
        for vertex in triangle: links.setdefault(int(vertex), set()).add(index)
    remaining = set(range(len(triangles))); groups = []
    while remaining:
        pending = [min(remaining)]; remaining.remove(pending[0]); group = []
        while pending:
            index = pending.pop(); group.append(index)
            neighbors = set().union(*(links[int(v)] for v in triangles[index])) & remaining
            pending.extend(sorted(neighbors)); remaining.difference_update(neighbors)
        groups.append(tuple(sorted(group)))
    return tuple(groups)


def component_worlds(colliders, owner):
    worlds = []
    for source in colliders:
        if source.owner_id != owner: continue
        for index, faces in enumerate(triangle_components(source.triangles)):
            part = replace(source, collider_id=source.collider_id + '|PIN_PART' + str(index),
                           triangles=np.asarray(source.triangles)[list(faces)],
                           generation=(*source.generation, 'PIN_PART', index))
            worlds.append(planner.cached_native_collision_world((part,)))
    return tuple(worlds)


def qualification_reason(search, row):
    frame = repair.resolve_surface_frame(search.obj, row['raw'], search.runtime)
    if frame is None: return 'SURFACE_PICK_FAILED'
    normal = np.asarray(frame['normal_world']) * search.outward_sign
    outside = np.asarray(row['point']) + normal * search.guard * 2
    for world in search.parts:
        _near, _normal, distance, _owner, inside = world.nearest(np.asarray([outside]))
        if inside[0] and distance[0] > search.guard * .5: return 'BURIED_OWNER_SURFACE'
    if repair._invalid_indices(search.state.native_world, (row,), search.owner, search.threshold):
        return 'ANCHOR_BLOCKED'
    return '' if has_exit(search, row) else 'NO_LOCAL_PIN_EXIT'


def has_exit(search, row):
    anchor = replace(search.anchor, point=tuple(row['point']))
    samples = _anchor_candidates(search.state, anchor, oblique=True)
    candidates = _validated_candidates(search.state, anchor, samples, validate_edges)
    if not candidates: candidates = broad_exits(search, anchor)
    if not candidates: return False
    points = np.asarray(candidates); free = np.ones(len(points), dtype=bool)
    for world in search.parts:
        _near, _normal, distance, _owner, inside = world.nearest(points)
        free &= ~np.asarray(inside) & (np.asarray(distance) >= search.threshold)
    return bool(np.any(free))


def validate_edges(state, points, edges, owners):
    """Same collision rules without building an unused planner graph-edge cache."""
    threshold = state.request.collision_policy.collision_radius - state.request.tolerances.clearance_slack
    span = planner._state_contact_span(state)
    return planner.validate_native_owner_chords(state.request, state.native_world,
                                               points, edges, owners, span, threshold).clear


def broad_exits(search, anchor):
    k = np.arange(256); z = 1 - 2 * (k + .5) / len(k); angle = k * np.pi * (3 - np.sqrt(5))
    directions = np.column_stack((np.sqrt(1-z*z)*np.cos(angle), np.sqrt(1-z*z)*np.sin(angle), z))
    radius = max(search.radius, search.state.request.tolerances.numeric_floor, 1e-7)
    ends = np.vstack([np.asarray(anchor.point) + directions * radius * scale for scale in (2, 4)])
    points = np.vstack([anchor.point, ends]); edges = tuple((0, i) for i in range(1, len(points)))
    clear = validate_edges(search.state, points, edges, ((anchor.owner_id, ''),) * len(edges))
    nodes = tuple((b, b) for _a, b in edges)
    free = validate_edges(search.state, points, nodes, (('', ''),) * len(nodes))
    return tuple(ends[np.asarray(clear, dtype=bool) & np.asarray(free, dtype=bool)])
