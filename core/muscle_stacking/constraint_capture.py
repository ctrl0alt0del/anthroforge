"""Blender capture of exact structural constraints on the canonical material mesh."""
from dataclasses import replace
import numpy as np
from .constraints import chart, fixed_indices
from .constraint_sources import structural
from .constraint_layout import ordinary


def apply(root, scene, muscle, request, domains):
    if not domains: return domains
    from ..visualization.muscle_profile_capture import find_target
    _, source = find_target(root, muscle.id)
    rows = branched(root, scene, source, request) if hasattr(request, 'assembly') else regular(root, scene, source, request, domains[0].material)
    count = len(domains[0].material.vertices); fixed_indices(rows, count)
    pins = np.asarray(sorted({r.indices[j] for r in rows for j,w in enumerate(r.weights) if w == 1}), dtype=np.int64)
    return tuple(replace(d, material=replace(d.material, fixed=pins, constraints=rows)) for d in domains)


def regular(root, scene, source, request, material):
    from ..visualization.muscle_profile_capture import current_rows
    from ..visualization.muscle_sync_runtime import expanded_rows_with_provenance
    fibers, rows = current_rows(root, scene, source)
    expanded, tags = expanded_rows_with_provenance(root, source, rows, fibers)
    lookup = {f.id: f for f in fibers}; fibers = [lookup[t['fiber_id']] for t in tags]
    across, along, knots, grid = ordinary(source, fibers, expanded, request)
    if grid.size != material.vertices.size or not np.allclose(grid.reshape(-1, 3), material.vertices, atol=5e-6, rtol=2e-6):
        raise ValueError('STACK_CONSTRAINT_LAYOUT_MISMATCH')
    mapping = np.arange(grid.size//3).reshape(grid.shape[:2])
    if request.spec.closed_u: mapping, along = np.c_[mapping, mapping[:, 0]], np.r_[along, 1.]
    queries, labels = samples(fibers, expanded, knots, across)
    return chart(np.arange(len(grid)), along, mapping, queries, labels)


def samples(fibers, rows, knots, across, reverse=()):
    queries, labels = [], []
    for r, (fiber, points, stations, u) in enumerate(zip(fibers, rows, knots, across)):
        for index, identity, role in structural(fiber, len(points)):
            index = len(points)-1-index if reverse and reverse[r] else index
            queries.append((float(u), float(stations[index])))
            labels.append(f'{fiber.id}:{identity}:{role}')
    return np.asarray(queries, dtype=float).reshape(-1, 2), labels


def branched(root, scene, source, request):
    from ..visualization.branched_surface_capture import source_surface, source_fibers
    from ..visualization.muscle_sync_runtime import collect_fiber_points
    from ..vcp.free_surface_stations import resolve
    from ..vcp.branched_surface import row_stations
    a = request.assembly; main_source = source_surface(root, source.main_surface_id)
    fibers = source_fibers(root, main_source); routes = collect_fiber_points(root, scene, fibers)
    knots = row_stations(routes, resolve(main_source, fibers)); u = np.linspace(0, 1, len(fibers))
    queries, labels = samples(fibers, routes, knots, u)
    axis = np.unique(np.r_[u, np.linspace(0, 1, 17)])
    mapping = np.arange(a.main.size//3).reshape(a.main.shape[:2])
    result = list(chart(axis, a.along, mapping, queries, labels)); count = a.main.size//3
    for connection, branch in zip(source.branches, a.branches):
        values, count = branch_constraints(root, connection, branch, a, count); result.extend(values)
    return tuple(result)


def branch_constraints(root, connection, branch, assembly, count):
    from ..visualization.branched_surface_capture import source_surface, source_fibers
    from ..vcp.branched_surface import row_stations, _branch_map
    fibers = source_fibers(root, source_surface(root, connection.surface_id))
    reverse = tuple(f.b_point_id == r.point_id for f, r in zip(fibers, connection.roots))
    knots = row_stations(branch.connection.fibers, branch.connection.stations)
    u = branch.source_across
    if len(u) != len(fibers): raise ValueError('STACK_BRANCH_ROOT_PROVENANCE_UNAVAILABLE')
    queries, labels = samples(fibers, branch.connection.fibers, knots, u, reverse)
    mapping, added = _branch_map(assembly.main, branch.grid, branch, count)
    return chart(branch.across, branch.along, mapping.reshape(branch.grid.shape[:2]), queries, labels), count+len(added)
