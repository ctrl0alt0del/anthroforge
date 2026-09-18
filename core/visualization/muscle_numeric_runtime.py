"""Blender capture and publication around the backend-neutral Muscle batch."""

from dataclasses import dataclass

import numpy as np
from mathutils import Vector

from ..perf_trace import perf_time, perf_timer
from ..vcp.muscle_numeric import MuscleNumericSpec, execute_muscle_batch, make_muscle_request
from ..vcp.muscle_surface import validate_anchor_structure
from ..vcp.muscle_inflation_state import inflation_control_initialized, migrate_inflation_control
from ..vcp.runtime_state import muscle_inflation_ctrl_world, set_muscle_inflation_ctrl_world


@dataclass(frozen=True)
class MuscleNumericWork:
    muscle: object
    base_obj: object
    infl_obj: object
    request: object = None
    stale: bool = False


def capture_muscle_work(sync, vis_col, root, scene, vcp, muscle):
    migrate_inflation_control(muscle)
    base, inflated = sync._ensure_muscle_meshes(vis_col, root, muscle.id)
    branched = _safe_branched_request(root, scene, muscle)
    payload = None if branched is not None else _numeric_input(sync, root, scene, muscle)
    stale = payload is None and sync._source_output_stale(root, scene, muscle)
    initialize = _initialize_control(muscle)
    try: request = branched if branched is not None else (None if payload is None else _make_request(muscle, payload, initialize))
    except (TypeError, ValueError): request = None
    return MuscleNumericWork(muscle, base, inflated, request, stale)


def _safe_branched_request(root, scene, muscle):
    try:
        return _branched_request(root, scene, muscle)
    except (ValueError, StopIteration):
        return None


def _branched_request(root, scene, muscle):
    if muscle.surface_source_mode != "FIBER_SURFACE":
        return None
    surface = next((s for s in root.af_vcp_system.fiber_surfaces if s.id == muscle.fiber_surface_id), None)
    if surface is None or surface.construction_mode != "BRANCHED_LOFT":
        return None
    from .branched_surface_capture import capture_assembly
    from ..vcp.branched_numeric import BranchedMuscleRequest
    assembly = capture_assembly(root, scene, surface)
    settings = (muscle, *(b.settings for b in surface.branches))
    grids = (assembly.main, *(b.grid for b in assembly.branches))
    specs = tuple(_numeric_spec(s, surface, g.shape[1], False, False, _initialize_control(s))
                  for s, g in zip(settings, grids))
    return BranchedMuscleRequest(muscle.id, assembly, specs)


def execute_muscle_work(scene, work):
    requests = tuple(item.request for item in work if item.request is not None)
    started = perf_timer()
    result = execute_muscle_batch(requests)
    perf_time(scene, "muscle_numeric_batch", started)
    return result


def publish_muscle_work(sync, vis_col, root, scene, vcp, work, batch):
    results = iter(batch.results)
    for item in work:
        result = next(results) if item.request is not None else None
        _publish_one(sync, vis_col, root, scene, vcp, item, result, batch)


def _numeric_input(sync, root, scene, muscle):
    if str(getattr(muscle, "surface_source_mode", "LEGACY_FIBERS")) == "FIBER_SURFACE":
        return _surface_input(sync, root, scene, muscle)
    return _legacy_input(sync, root, scene, muscle)


def _legacy_input(sync, root, scene, muscle):
    fibers, missing = sync._collect_fiber_props(root, muscle)
    if missing or not fibers or (len(fibers) > 1 and not validate_anchor_structure(fibers)[0]):
        return None
    points = sync._collect_points_with_fallback(root, scene, muscle, fibers)
    if not points or len(points) < 2:
        return None
    return points, int(fibers[0].node_count), True, sync._closed_u(fibers), muscle


def _surface_input(sync, root, scene, muscle):
    payload = sync._fiber_surface_input(root, scene, muscle)
    if payload is None:
        return None
    points, closed_u, config = payload
    return points, len(points[0]), False, closed_u, config


def _make_request(muscle, payload, initialize=False):
    points, target, densify, closed_u, config = payload
    spec = _numeric_spec(muscle, config, target, densify, closed_u, initialize)
    return make_muscle_request(muscle.id, np.asarray(points, dtype=np.float64), spec)


def _numeric_spec(muscle, config, target, densify, closed_u, initialize=False):
    values = _topology_values(config, target, densify, closed_u)
    values.update(_inflation_values(muscle))
    values["initialize_control"] = bool(initialize)
    return MuscleNumericSpec(**values)


def _topology_values(config, target, densify, closed_u):
    close = bool(getattr(config, "close_across_fibers", getattr(config, "closed_v", False)))
    return dict(target_count=int(target), densify=bool(densify), closed_u=bool(closed_u),
                close_across_fibers=close, topology_flip_normals=bool(getattr(config, "flip_normals", False)))


def _inflation_values(muscle):
    return dict(inflation_enabled=bool(muscle.inflation_enabled), inflation_mode=str(muscle.inflation_mode),
        inflation_max_value=float(muscle.inflation_max_value), inflation_falloff_type=str(muscle.inflation_falloff_type),
        inflation_falloff_radius=float(muscle.inflation_falloff_radius), inflation_direction_depth=float(muscle.inflation_direction_depth),
        inflation_boundary_strength=float(muscle.inflation_boundary_strength), inflation_boundary_band=float(muscle.inflation_boundary_band),
        inflation_boundary_power=float(muscle.inflation_boundary_power), inflation_length_taper_band=float(muscle.inflation_length_taper_band),
        closed_v=bool(muscle.closed_v), flip_normals=bool(muscle.flip_normals), control_world=muscle_inflation_ctrl_world(muscle))


def _initialize_control(muscle):
    return str(muscle.inflation_mode) == "CTRL_POINT" and not inflation_control_initialized(muscle)


def _publish_one(sync, vis_col, root, scene, vcp, work, result, batch):
    if work.request is None:
        return _publish_missing(sync, vcp, work)
    if result is None or result.error:
        return sync._clear_muscle_meshes(vcp, work.muscle.id, work.base_obj, work.infl_obj)
    _publish_valid(sync, vis_col, root, scene, vcp, work, result, batch)


def _publish_missing(sync, vcp, work):
    if work.stale:
        return sync._retain_stale_muscle(work.base_obj, work.infl_obj)
    sync._clear_muscle_meshes(vcp, work.muscle.id, work.base_obj, work.infl_obj)


def _publish_valid(sync, vis_col, root, scene, vcp, work, result, batch):
    sync._update_mesh(work.base_obj, result.base_vertices, result.faces)
    _sync_control(sync, vis_col, root, scene, vcp, work, result)
    sync._update_mesh(work.infl_obj, result.inflated_vertices, result.faces)
    _mark_valid(sync, vcp, work, batch)


def _sync_control(sync, vis_col, root, scene, vcp, work, result):
    from .branch_control import selected_part
    ensure = sync._selected_muscle_id(vcp, root, scene) == work.muscle.id
    settings, key, index = selected_part(root, work.muscle)
    rows, spec = _part_control(work.request, result, index)
    if spec.initialize_control: _store_initial_control(settings, rows)
    points = [[Vector(point) for point in row] for row in rows] if ensure else ()
    ctrl = sync._sync_inflation_control(vis_col, root, settings, work.base_obj, points, ensure)
    if ctrl is not None: ctrl['af_muscle_branch_id'] = key


def _part_control(request, result, index):
    if hasattr(request, 'assembly'):
        rows = request.assembly.main if index == 0 else request.assembly.branches[index-1].grid
        return rows, request.part_specs[index]
    return _control_rows(request, result), request.spec


def _control_rows(request, result):
    if hasattr(request, "assembly"):
        return request.assembly.main
    return result.base_vertices.reshape((result.row_count, result.column_count, 3))


def _store_initial_control(muscle, rows):
    point = rows[len(rows) // 2, len(rows[0]) // 2]
    set_muscle_inflation_ctrl_world(muscle, tuple(float(value) for value in point))


def _mark_valid(sync, vcp, work, batch):
    objects = work.base_obj, work.infl_obj
    sync._set_output_state(objects, "CURRENT")
    sync._set_muscle_active_materials(vcp, work.muscle.id, *objects)
    for obj in objects:
        obj["af_muscle_numeric_backend"] = batch.backend
        obj["af_muscle_numeric_batch_ms"] = float(batch.elapsed_ms)
