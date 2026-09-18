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
    error: str = ""


def capture_muscle_work(sync, vis_col, root, scene, vcp, muscle):
    if muscle.inflation_mode == "SECTION_PROFILE":
        return _capture_profile_work(sync, vis_col, root, scene, muscle)
    if muscle.inflation_mode not in ("CTRL_POINT", "DISTRIBUTED"):
        return _invalid_mode_work(sync, vis_col, root, muscle)
    migrate_inflation_control(muscle)
    base, inflated = sync._ensure_muscle_meshes(vis_col, root, muscle.id)
    payload = _numeric_input(sync, root, scene, muscle)
    stale = payload is None and sync._source_output_stale(root, scene, muscle)
    initialize = _initialize_control(muscle)
    try: request = None if payload is None else _make_request(muscle, payload, initialize)
    except (TypeError, ValueError): request = None
    return MuscleNumericWork(muscle, base, inflated, request, stale)


def _invalid_mode_work(sync, vis_col, root, muscle):
    base = sync._find_muscle_proxy(vis_col, root.name, muscle.id)
    inflated = sync._find_muscle_proxy(vis_col, root.name, muscle.id, "INFL")
    return MuscleNumericWork(muscle, base, inflated, error="PROFILE_MODE_UNSUPPORTED: " + muscle.inflation_mode)


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
    if muscle.inflation_mode == "SECTION_PROFILE":
        from ..vcp.muscle_section_profile import profile_from_muscle
        values["section_profile"] = profile_from_muscle(muscle)
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
        closed_v=bool(muscle.closed_v), flip_normals=bool(muscle.flip_normals), control_world=(0., 0., 0.) if muscle.inflation_mode == "SECTION_PROFILE" else muscle_inflation_ctrl_world(muscle))


def _initialize_control(muscle):
    return str(muscle.inflation_mode) == "CTRL_POINT" and not inflation_control_initialized(muscle)


def _publish_one(sync, vis_col, root, scene, vcp, work, result, batch):
    error = work.error or (result.error if result else "")
    work.muscle["_af_rt_section_profile_error"] = error
    if work.muscle.inflation_mode == "SECTION_PROFILE":
        sync._remove_inflation_ctrl_for_muscle(vis_col, root.name, work.muscle.id)
    if error:
        return _publish_error(sync, vcp, work, error)
    if work.request is None:
        return _publish_missing(sync, vcp, work)
    if result is None or result.error:
        return sync._clear_muscle_meshes(vcp, work.muscle.id, work.base_obj, work.infl_obj)
    if _profile_unchanged(sync, vis_col, root, work, result):
        return
    _publish_valid(sync, vis_col, root, scene, vcp, work, result, batch)


def _profile_unchanged(sync, vis_col, root, work, result):
    if work.muscle.inflation_mode != "SECTION_PROFILE" or sync._find_inflation_ctrl(vis_col, root.name, work.muscle.id):
        return False
    for obj, values in ((work.base_obj, result.base_vertices), (work.infl_obj, result.inflated_vertices)):
        if obj is None or obj.get("af_muscle_output_state") != "CURRENT" or not mesh_matches(obj, values, result.faces):
            return False
    return True


def mesh_matches(obj, values, faces):
    import numpy as np
    actual = np.empty(len(obj.data.vertices)*3, dtype=np.float32)
    obj.data.vertices.foreach_get("co", actual)
    return (np.array_equal(actual.reshape(-1, 3), np.asarray(values, dtype=np.float32)) and
            np.array_equal([tuple(face.vertices) for face in obj.data.polygons], faces))


def _publish_missing(sync, vcp, work):
    if work.stale:
        return sync._retain_stale_muscle(work.base_obj, work.infl_obj)
    sync._clear_muscle_meshes(vcp, work.muscle.id, work.base_obj, work.infl_obj)


def _publish_valid(sync, vis_col, root, scene, vcp, work, result, batch):
    from dataclasses import replace
    if work.base_obj is None or work.infl_obj is None:
        base, inflated = sync._ensure_muscle_meshes(vis_col, root, work.muscle.id)
        work = replace(work, base_obj=base, infl_obj=inflated)
    sync._update_mesh(work.base_obj, result.base_vertices, result.faces)
    _sync_control(sync, vis_col, root, scene, vcp, work, result)
    sync._update_mesh(work.infl_obj, result.inflated_vertices, result.faces)
    _mark_valid(sync, vcp, work, batch)


def _sync_control(sync, vis_col, root, scene, vcp, work, result):
    ensure = sync._selected_muscle_id(vcp, root, scene) == work.muscle.id
    rows = result.base_vertices.reshape((result.row_count, result.column_count, 3))
    if work.request.spec.initialize_control: _store_initial_control(work.muscle, rows)
    points = [[Vector(point) for point in row] for row in rows] if ensure and work.muscle.inflation_mode == "CTRL_POINT" else ()
    sync._sync_inflation_control(vis_col, root, work.muscle, work.base_obj, points, ensure)


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


def _capture_profile_work(sync, vis_col, root, scene, muscle):
    from .muscle_profile_capture import capture_target
    from ..vcp.muscle_section_profile import profile_from_muscle
    base, inflated = sync._find_muscle_proxy(vis_col, root.name, muscle.id), sync._find_muscle_proxy(vis_col, root.name, muscle.id, "INFL")
    try:
        profile_from_muscle(muscle)
        target = capture_target(root, scene, muscle.id)
        if not target.eligible:
            raise ValueError("; ".join(target.reasons))
        request = _make_request(muscle, target.payload)
        return MuscleNumericWork(muscle, base, inflated, request)
    except (ValueError, TypeError) as error:
        return MuscleNumericWork(muscle, base, inflated, error=str(error))


def _publish_error(sync, vcp, work, error):
    if "PROFILE_BASE_NOT_CURRENT" in error:
        return sync._retain_stale_muscle(work.base_obj, work.infl_obj)
    for obj in (work.base_obj, work.infl_obj):
        if obj is not None:
            sync._update_mesh(obj, [], [])
    sync._set_output_state((work.base_obj, work.infl_obj), "INVALID")
