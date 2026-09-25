"""Preallocate bounded Free-containing derived output; never simplify a path."""
import numpy as np
from mathutils import Vector
from ..vcp.free_path import is_free, decode, point_indices
from ..vcp.free_surface import prepare_rows, branch_budget, check_budget
from ..vcp.branched_surface import BranchInput
from ..vcp.fiber_surface import _average_row_step, _row_inserts
from .muscle_sync_runtime import collect_fiber_points


def _routes(root, scene, fibers, replacements):
    values = []
    for fiber in fibers:
        row = replacements.get(fiber.id)
        if row is None:
            cached = collect_fiber_points(root, scene, [fiber]); row = cached[0] if cached else None
        if row is None: raise ValueError('Dependent Fiber geometry is unavailable: ' + fiber.id)
        values.append(np.asarray(row))
    return values


def _ordinary(rows, closed=False, close=False):
    prepared = prepare_rows(rows, closed, densify=False)
    step = _average_row_step(prepared); n = len(prepared[0])
    m = len(rows) + sum(_row_inserts(a, b, step, 3 if closed else 0) for a, b in zip(prepared, prepared[1:]))
    return m * n, 2 * (m if close else m - 1) * (n if closed else n - 1)


def _branch(root, scene, surface, replacements, payloads):
    from .branched_surface_capture import source_surface, source_fibers, _boundary, _root_indices
    fibers = source_fibers(root, source_surface(root, surface.main_surface_id)); rows = _routes(root, scene, fibers, replacements)
    branches = []
    for connection in surface.branches:
        side = _boundary(fibers, connection.boundary_fiber_id); parent = fibers[side]
        keys = [r.point_id for r in connection.roots]; payload = payloads.get(parent.id)
        indices = point_indices(payload or decode(parent.free_path_json), keys) if payload or is_free(parent) else _root_indices(root, scene, parent, list(map(Vector, rows[side])), keys)
        children = source_fibers(root, source_surface(root, connection.surface_id))
        curves = _routes(root, scene, children, replacements)
        curves = tuple(row if child.a_point_id == key else row[::-1] for child, key, row in zip(children, keys, curves))
        branches.append(BranchInput(connection.id, side, indices, curves, connection.width, connection.fullness))
    return branch_budget(rows, branches)


def _surface(root, scene, surface, fibers, replacements, payloads):
    if surface.construction_mode == 'BRANCHED_LOFT': return _branch(root, scene, surface, replacements, payloads)
    rows = _routes(root, scene, fibers, replacements)
    if surface.construction_mode == 'LOOP_PATCH':
        level = surface.patch_resolution; triangles = max(1, len(rows[0]) - 2)
        return triangles * (level + 1) * (level + 2) // 2, triangles * level * level
    from ..vcp.free_surface_stations import resolve, prepare
    stations = resolve(surface, fibers, payloads)
    if stations:
        prepared = prepare(rows, stations)
        return len(prepared)*len(prepared[0]), 2*(len(prepared)-1)*(len(prepared[0])-1)
    return _ordinary(rows, fibers[0].topology_mode == 'LOOP', surface.close_across_fibers)


def validate_outputs(root, scene, replacements, payloads=None):
    from .free_output_verification import affected_surfaces
    system = root.af_vcp_system; lookup = {f.id: f for f in system.fibers}; payloads = payloads or {}
    counts = {}
    for surface in affected_surfaces(root, set(replacements)):
        fibers = [lookup[r.fiber_id] for r in surface.fiber_refs if r.fiber_id in lookup]
        counts[surface.id] = _surface(root, scene, surface, fibers, replacements, payloads)
        check_budget(*counts[surface.id], multiplier=2)
    for muscle in system.muscles:
        values = counts.get(muscle.fiber_surface_id)
        if muscle.surface_source_mode != 'FIBER_SURFACE': values = _legacy(root, scene, muscle, lookup, replacements)
        if values is not None: check_budget(*values, multiplier=4)


def _legacy(root, scene, muscle, lookup, replacements):
    fibers = [lookup[r.fiber_id] for r in muscle.fiber_refs if r.fiber_id in lookup]
    if not set(replacements).intersection(f.id for f in fibers) or len(fibers) < 2: return None
    return _ordinary(_routes(root, scene, fibers, replacements), fibers[0].topology_mode == 'LOOP', muscle.closed_v)
