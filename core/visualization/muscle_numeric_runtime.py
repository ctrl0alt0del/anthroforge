"""Blender capture and publication around the backend-neutral Muscle batch."""

from dataclasses import dataclass, replace

import numpy as np
from mathutils import Vector

from ..perf_trace import perf_time, perf_timer
from ..vcp.muscle_numeric import MuscleNumericSpec, execute_muscle_batch, make_muscle_request
from ..vcp.muscle_surface import validate_anchor_structure
from ..vcp.muscle_inflation_state import inflation_control_initialized, migrate_inflation_control
from ..vcp.runtime_state import muscle_inflation_ctrl_world, set_muscle_inflation_ctrl_world
from ..vcp.muscle_output_domain import capture as capture_domain
from ..vcp.muscle_envelope import faces_for


@dataclass(frozen=True)
class MuscleNumericWork:
    muscle: object
    base_obj: object
    infl_obj: object
    request: object = None
    stale: bool = False
    error: str = ""


def capture_muscle_work(sync, vis_col, root, scene, vcp, muscle):
    if getattr(muscle, 'envelope_sides', '') == 'BOTH_SIDES':
        return _capture_envelope_work(sync, vis_col, root, scene, muscle)
    error = _domain_error(muscle) or _branched_mode_error(root, muscle)
    if error:
        return _invalid_mode_work(sync, vis_col, root, muscle, error)
    if muscle.inflation_mode == "SECTION_PROFILE":
        return _capture_profile_work(sync, vis_col, root, scene, muscle)
    if muscle.inflation_mode not in ("CTRL_POINT", "DISTRIBUTED"):
        return _invalid_mode_work(sync, vis_col, root, muscle)
    return _capture_legacy_work(sync, vis_col, root, scene, muscle)


def _domain_error(muscle):
    try:
        capture_domain(muscle)
        return ''
    except (ValueError, np.linalg.LinAlgError) as error:
        return 'DOMAIN_CONFIGURATION_INVALID: '+str(error)


def _capture_legacy_work(sync, vis_col, root, scene, muscle):
    migrate_inflation_control(muscle)
    base, inflated = sync._ensure_muscle_meshes(vis_col, root, muscle.id)
    branched = _safe_branched_request(root, scene, muscle)
    payload = None if branched is not None else _numeric_input(sync, root, scene, muscle)
    stale = payload is None and sync._source_output_stale(root, scene, muscle)
    initialize = _initialize_control(muscle)
    try: request = branched if branched is not None else (None if payload is None else _make_request(muscle, payload, initialize))
    except (TypeError, ValueError): request = None
    return MuscleNumericWork(muscle, base, inflated, request, stale)


def _invalid_mode_work(sync, vis_col, root, muscle, error=""):
    base = sync._find_muscle_proxy(vis_col, root.name, muscle.id)
    inflated = sync._find_muscle_proxy(vis_col, root.name, muscle.id, "INFL")
    return MuscleNumericWork(muscle, base, inflated, error=error or "PROFILE_MODE_UNSUPPORTED: " + muscle.inflation_mode)


def _branched_mode_error(root, muscle):
    from .branch_control import branch_surface
    from ..vcp.prepared_inflation import validate_prepared_mode
    surface = branch_surface(root, muscle)
    if surface is not None:
        try:
            for settings in (muscle, *(b.settings for b in surface.branches)):
                validate_prepared_mode(settings.inflation_mode)
        except ValueError as error:
            return str(error)
    return ""


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
    assembly = capture_assembly(root, scene, surface)
    return _make_branched_request(muscle, surface, assembly)


def _make_branched_request(muscle, surface, assembly, envelope=True):
    from ..vcp.branched_numeric import BranchedMuscleRequest
    from ..vcp.prepared_inflation import validate_prepared_mode
    settings = (muscle, *(b.settings for b in surface.branches))
    for part in settings: validate_prepared_mode(part.inflation_mode)
    grids = (assembly.main, *(b.grid for b in assembly.branches))
    specs = tuple(_numeric_spec(s, surface, g.shape[1], False, False, _initialize_control(s))
                  for s, g in zip(settings, grids))
    from .muscle_envelope_storage import attach
    request = BranchedMuscleRequest(muscle.id, assembly, specs, capture_domain(muscle))
    return attach(request, muscle) if envelope else request


def execute_muscle_work(scene, work):
    requests = tuple(item.request for item in work if item.request is not None)
    started = perf_timer()
    result = execute_muscle_batch(requests)
    perf_time(scene, "muscle_numeric_batch", started)
    return result


def publish_muscle_work(sync, vis_col, root, scene, vcp, work, batch):
    results, published = iter(batch.results), set()
    for item in work:
        result = next(results) if item.request is not None else None
        _publish_one(sync, vis_col, root, scene, vcp, item, result, batch)
        if result is not None and not item.error and not result.error:
            published.add(item.muscle.id)
    return published


def _numeric_input(sync, root, scene, muscle):
    if str(getattr(muscle, "surface_source_mode", "LEGACY_FIBERS")) == "FIBER_SURFACE":
        return _surface_input(sync, root, scene, muscle)
    return _legacy_input(sync, root, scene, muscle)


def _legacy_input(sync, root, scene, muscle):
    fibers, missing = sync._collect_fiber_props(root, muscle)
    from ..vcp.free_path import is_free
    if any(is_free(f) for f in fibers): return _free_legacy_input(sync, root, scene, muscle, fibers, missing)
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
    return points, len(points[0]), False, closed_u, config, _free_source(root, config)


def _make_request(muscle, payload, initialize=False, envelope=True):
    points, target, densify, closed_u, config = payload[:5]
    spec = _numeric_spec(muscle, config, target, densify, closed_u, initialize)
    if len(payload) > 5 and payload[5]:
        from dataclasses import replace
        spec = replace(spec, preserve_samples=True)
    from .muscle_envelope_storage import attach
    request = make_muscle_request(muscle.id, np.asarray(points, dtype=np.float64), spec, output_domain=capture_domain(muscle))
    return attach(request, muscle) if envelope else request


def _free_source(root, source):
    from ..vcp.free_path import is_free
    wanted = {ref.fiber_id for ref in source.fiber_refs}
    return any(is_free(f) for f in root.af_vcp_system.fibers if f.id in wanted)


def _free_legacy_input(sync, root, scene, muscle, fibers, missing):
    from ..vcp.free_surface import prepare_rows
    if missing or len(fibers) < 2: return None
    points = sync._collect_points_with_fallback(root, scene, muscle, fibers)
    if not points or len({f.topology_mode for f in fibers}) != 1: return None
    closed = sync._closed_u(fibers); rows = prepare_rows(points, closed, multiplier=4)
    return rows, len(rows[0]), False, closed, muscle, True


def _numeric_spec(muscle, config, target, densify, closed_u, initialize=False):
    from ..vcp.height_smoothing import capture
    values = _topology_values(config, target, densify, closed_u)
    values.update(_inflation_values(muscle))
    values["initialize_control"] = bool(initialize)
    values['smoothing'] = capture(muscle)
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
    if (work.muscle.inflation_mode == "SECTION_PROFILE" and work.request is not None and work.request.envelope is None) or error.startswith("PROFILE_"):
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
    if work.request.envelope is not None: return False
    if work.muscle.inflation_mode != "SECTION_PROFILE" or sync._find_inflation_ctrl(vis_col, root.name, work.muscle.id):
        return False
    for obj, values in ((work.base_obj, result.base_vertices), (work.infl_obj, result.inflated_vertices)):
        if obj is None or obj.get("af_muscle_output_state") != "CURRENT" or not mesh_matches(obj, values, faces_for(result, obj == work.infl_obj)):
            return False
    return True


def mesh_matches(obj, values, faces):
    import numpy as np
    mesh = obj.data
    if len(mesh.vertices) != len(values) or len(mesh.polygons) != len(faces): return False
    actual = np.empty((len(mesh.vertices), 3), dtype=np.float32)
    mesh.vertices.foreach_get("co", actual.ravel())
    if not np.array_equal(actual, np.asarray(values, dtype=np.float32)): return False
    loops = np.empty(len(mesh.loops), dtype=np.int32)
    counts = np.empty(len(mesh.polygons), dtype=np.int32)
    starts = np.empty(len(mesh.polygons), dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", loops)
    mesh.polygons.foreach_get("loop_total", counts); mesh.polygons.foreach_get("loop_start", starts)
    lengths = np.asarray([len(face) for face in faces], dtype=np.int32)
    flat = np.concatenate(faces) if len(faces) else np.empty(0, dtype=np.int32)
    return np.array_equal(counts, lengths) and np.array_equal(starts, np.cumsum(lengths)-lengths) and np.array_equal(loops, flat)


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
    sync._update_mesh(work.infl_obj, result.inflated_vertices, faces_for(result, True))
    _domain_metadata(work, result)
    _envelope_metadata(work, result)
    _mark_valid(sync, vcp, work, batch)
    from ..muscle_pairs.capture import remember
    remember(root, work, result, scene)


def _domain_metadata(work, result):
    from ..authoring.codec import encode
    for obj in (work.base_obj, work.infl_obj):
        obj['af_muscle_domain_plane'] = encode(work.request.output_domain)
        for name, values in _face_metadata(work, result, obj):
            old = obj.data.attributes.get(name)
            if old is not None:
                obj.data.attributes.remove(old)
            if values is not None:
                attribute = obj.data.attributes.new(name=name, type='INT', domain='FACE')
                attribute.data.foreach_set('value', values)


def _sync_control(sync, vis_col, root, scene, vcp, work, result):
    from .muscle_envelope_storage import selected_settings
    ensure = sync._selected_muscle_id(vcp, root, scene) == work.muscle.id
    settings, key, index = selected_settings(root, work.muscle)
    settings.id = work.muscle.id
    spec = work.request.part_specs[index] if hasattr(work.request, 'assembly') else work.request.spec
    if work.request.envelope and work.muscle.envelope_edit_side == 'B': spec = work.request.envelope.secondary[index]
    rows = _part_control(work.request, result, index)[0] if spec.initialize_control or (ensure and settings.inflation_mode == 'CTRL_POINT') else ()
    if spec.initialize_control: _store_initial_control(settings, rows)
    points = [[Vector(point) for point in row] for row in rows] if ensure and settings.inflation_mode == "CTRL_POINT" else ()
    _bind_control(sync, vis_col, root, work.muscle.id, key, work.muscle.envelope_edit_side if work.request.envelope else 'A')
    ctrl = sync._sync_inflation_control(vis_col, root, settings, work.base_obj, points, ensure)
    _bind_control(sync, vis_col, root, work.muscle.id, key, work.muscle.envelope_edit_side if work.request.envelope else 'A')


def _bind_control(sync, vis_col, root, muscle_id, key, side):
    from ..deps.muscle_control_intents import retire_control
    ctrl = sync._find_inflation_ctrl(vis_col, root.name, muscle_id)
    if ctrl is None:
        return
    if str(ctrl.get('af_muscle_branch_id', '')) == key and str(ctrl.get('af_inflation_side', 'A')) == side:
        return
    retire_control(ctrl)
    ctrl['af_muscle_branch_id'], ctrl['af_inflation_side'] = key, side
    ctrl['af_muscle_ctrl_sync_location'] = tuple(ctrl.location)


def _part_control(request, result, index):
    if hasattr(request, 'assembly'):
        rows = request.assembly.main if index == 0 else request.assembly.branches[index-1].grid
        return rows, request.part_specs[index]
    return _control_rows(request, result), request.spec


def _control_rows(request, result):
    if hasattr(request, "assembly"):
        return request.assembly.main
    if request.output_domain is not None:
        from ..vcp.fiber_surface import prepare_loft_rows
        return np.asarray(prepare_loft_rows(request.points, request.spec.target_count, request.spec.closed_u, request.spec.densify))
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
        obj['af_muscle_output_domain'] = str(work.muscle.output_domain_mode)


def _capture_profile_work(sync, vis_col, root, scene, muscle):
    from .muscle_profile_capture import capture_target
    from ..vcp.muscle_section_profile import profile_from_muscle
    base, inflated = sync._find_muscle_proxy(vis_col, root.name, muscle.id), sync._find_muscle_proxy(vis_col, root.name, muscle.id, "INFL")
    try:
        profile_from_muscle(muscle)
        target = capture_target(root, scene, muscle.id, index=sync._object_index)
        if not target.eligible:
            raise ValueError("; ".join(target.reasons))
        request = replace(_make_request(muscle, target.payload), prepared_base=target.prepared_base)
        return MuscleNumericWork(muscle, base, inflated, request)
    except (ValueError, TypeError) as error:
        return MuscleNumericWork(muscle, base, inflated, error=str(error))


def _publish_error(sync, vcp, work, error):
    if all(reason.strip().startswith("PROFILE_BASE_NOT_CURRENT:") for reason in error.split(";")):
        return sync._retain_stale_muscle(work.base_obj, work.infl_obj)
    for obj in (work.base_obj, work.infl_obj):
        if obj is not None:
            sync._update_mesh(obj, [], [])
    sync._set_output_state((work.base_obj, work.infl_obj), "INVALID")


def _face_metadata(work, result, obj):
    if obj == work.infl_obj and result.inflated_faces is not None:
        return (('af_source_face', result.inflated_sources), ('af_muscle_part', result.inflated_parts), ('af_inflation_side', result.inflated_sides))
    return (('af_source_face', result.source_faces), ('af_muscle_part', result.face_parts), ('af_inflation_side', None))


def _capture_envelope_work(sync, vis_col, root, scene, muscle):
    from .muscle_profile_capture import capture_target
    try:
        target = capture_target(root, scene, muscle.id, index=sync._object_index)
        if not target.current or (target.assembly is None and not target.eligible):
            raise ValueError('; '.join(target.reasons))
        request = _make_branched_request(muscle, target.source, target.assembly) if target.assembly else _make_request(muscle, target.payload, _initialize_control(muscle))
        if target.prepared_base is not None: request = replace(request, prepared_base=target.prepared_base)
        base, inflated = sync._ensure_muscle_meshes(vis_col, root, muscle.id)
        return MuscleNumericWork(muscle, base, inflated, request)
    except (ValueError, TypeError) as error:
        return _invalid_mode_work(sync, vis_col, root, muscle, str(error))


def _envelope_metadata(work, result):
    from ..authoring.codec import encode
    work.muscle['_af_rt_envelope_diagnostics'] = encode(result.diagnostics or {})
    work.infl_obj['af_envelope_diagnostics'] = encode(result.diagnostics or {})
    from .muscle_envelope_overlay import arrows
    work.infl_obj['af_envelope_arrows'] = encode(arrows(work, result))
