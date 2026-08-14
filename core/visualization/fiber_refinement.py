from collections import deque
from dataclasses import dataclass
from math import isfinite
from time import monotonic

import bpy
from bpy.app.handlers import persistent

from ..deps.dirty_hints import dirty_hints_for
from ..deps.runtime_trace import activate_request_telemetry, restore_request_telemetry, telemetry_cache_snapshot
from ..vcp.fiber_collision import _collider_stamp
from ..vcp.fiber_engine import FiberTermination
from ..vcp.fiber_progressive import begin_fiber_solve, publish_fiber_cache
from ..vcp.runtime_state import (
    fiber_recompute_status,
    set_fiber_active_colliders,
    set_fiber_eps_disp,
    set_fiber_eps_pen,
    set_fiber_invalid_reason,
    set_fiber_not_converged,
    set_fiber_planner_ms,
    set_fiber_recompute_ms,
    set_fiber_recompute_status,
    set_fiber_refine_ms,
    set_fiber_route_mode,
)
from .fiber_sync import register_fiber_sync
from .fiber_sync_helpers import mark_fiber_output_current, mark_fiber_output_stale, persisted_fiber_points


_SLICE_MS = 12.0
_TIMER_INTERVAL = 0.01
_DRAW_INTERVAL = 0.05
_JOBS = {}
_QUEUE = deque()
_TIMER_ARMED = False
_PAUSED = []


@dataclass
class RefinementRequest:
    ok: bool
    error: str = ""
    proxy: object = None
    job: object = None


@dataclass
class FiberRefinementJob:
    key: tuple
    scene_name: str
    root_name: str
    scene_uid: int
    root_uid: int
    fiber_uid: int
    fiber_id: str
    signature: tuple
    geometry_signature: tuple
    session: object
    proxy_name: str = ""
    last_apply: float = 0.0
    last_generation: int = -1
    token: int = 0
    previous_status: str = "UNKNOWN"
    output_committed: bool = False
    previous_points: tuple = ()
    retain_preview: bool = False


def request_fiber_refinement(root, scene, fiber, show_preview=False, quality="FINAL"):
    if root is None or scene is None or fiber is None:
        return RefinementRequest(False, "Fiber refinement context is unavailable.")
    key = _job_key(scene, root, fiber.id)
    session = begin_fiber_solve(
        register_fiber_sync()._solver, root, fiber, scene, _depsgraph(scene), quality)
    if session.invalid_reason:
        _abort_request(key, root, scene, fiber)
        return RefinementRequest(False, session.invalid_reason)
    _supersede_job(key)
    job = _new_job(key, scene, root, fiber, session)
    mark_fiber_output_stale(scene, root.name, fiber.id)
    proxy = _initial_proxy(job, show_preview)
    return _start_or_finish(job, proxy)


def cancel_fiber_refinement(scene, fiber_id, mark_unknown=True):
    keys = [key for key in tuple(_JOBS) if key[0] == _id_uid(scene) and key[2] == str(fiber_id)]
    for key in keys:
        _terminate_key(key, FiberTermination.CANCELLED, mark_unknown)
    return bool(keys)


def fiber_refinement_state(scene, fiber_id):
    key = next((key for key in _JOBS if key[0] == _id_uid(scene) and key[2] == str(fiber_id)), None)
    if key is not None:
        return "REFINING"
    fiber = _fiber_for_scene(scene, fiber_id)
    return "UNKNOWN" if fiber is None else fiber_recompute_status(fiber)


def shutdown_fiber_refinements(mark_unknown=False):
    global _TIMER_ARMED
    for key in tuple(_JOBS):
        _terminate_key(key, FiberTermination.CANCELLED, mark_unknown)
    _QUEUE.clear()
    _drop_timer()
    _TIMER_ARMED = False


def drain_fiber_refinements(max_slices=100000):
    global _TIMER_ARMED
    _drop_timer()
    _TIMER_ARMED = bool(_QUEUE)
    count = 0
    while _QUEUE and count < int(max_slices):
        _flush_one()
        count += 1
    return not _QUEUE


def _new_job(key, scene, root, fiber, session):
    token = _next_token(fiber)
    previous = _displayed_points(scene, root.name, fiber.id)
    retain = bool(previous and fiber.use_surface_routing and
                  not _planner_preview_visible(scene, root.name, fiber.id))
    job = FiberRefinementJob(key, scene.name, root.name, _id_uid(scene), _id_uid(root),
                             _id_pointer(fiber), fiber.id, _fiber_signature(fiber),
                             _geometry_signature(session), session, token=token,
                             previous_status=fiber_recompute_status(fiber),
                             previous_points=previous,
                             retain_preview=retain)
    _claim_pending_version(fiber, token)
    job.last_apply, job.last_generation = monotonic(), session.generation
    return job


def _initial_proxy(job, show_preview):
    root, scene, fiber = _resolved_job_data(job)
    proxy = _find_proxy(scene, root.name, fiber.id)
    if show_preview or proxy is None:
        proxy = register_fiber_sync().apply_points(
            root, scene, fiber, job.session.preview, bake=False, commit=False)
    job.proxy_name = "" if proxy is None else proxy.name
    return proxy


def _start_or_finish(job, proxy):
    if job.session.done:
        result = job.session.result()
        _apply_progress(job, result)
        _finish_job(job, result)
        return RefinementRequest(True, proxy=proxy)
    _mark_refining(job.session.fiber)
    _JOBS[job.key] = job
    _QUEUE.append(job.key)
    _arm_timer()
    return RefinementRequest(True, proxy=proxy, job=job)


def _arm_timer():
    global _TIMER_ARMED
    if _TIMER_ARMED:
        return
    _TIMER_ARMED = True
    bpy.app.timers.register(_flush_one, first_interval=0.0)


def _flush_one():
    global _TIMER_ARMED
    if not _QUEUE:
        _TIMER_ARMED = False
        return None
    key = _QUEUE.popleft()
    job = _JOBS.get(key)
    if job is not None:
        _advance_job(job)
    if key in _JOBS:
        _QUEUE.append(key)
    _TIMER_ARMED = bool(_QUEUE)
    return _TIMER_INTERVAL if _QUEUE else None


def _advance_job(job):
    reason = _invalid_job_reason(job)
    if reason:
        _terminate_job(job, reason, mark_unknown=True, stale=True)
        return
    previous = activate_request_telemetry(job.session.telemetry)
    try:
        _advance_active_job(job)
    finally:
        restore_request_telemetry(previous)


def _advance_active_job(job):
    result = job.session.step(_SLICE_MS)
    _apply_progress(job, result)
    if result.done:
        _finish_job(job, result)


def _apply_progress(job, result):
    if not _valid_job(job):
        return
    now = monotonic()
    changed_level = job.last_generation != job.session.generation
    if not (result.done or changed_level or now - job.last_apply >= _DRAW_INTERVAL):
        return
    root, scene, fiber = _resolved_job_data(job)
    if _planner_preview_result(result):
        _apply_planner_result(job, result, root, scene, fiber, now)
        return
    _apply_refined_geometry(job, result, root, scene, fiber, now)


def _apply_refined_geometry(job, result, root, scene, fiber, now):
    commit = bool(result.done and _commit_allowed(job, result))
    if _retain_safe_preview(job, commit, now):
        return
    proxy = register_fiber_sync().apply_points(root, scene, fiber, result.points,
                                               bake=result.done, commit=commit)
    None if proxy is None else proxy.pop("af_fiber_display_mode", None)
    job.output_committed = bool(result.done and commit and proxy is not None)
    job.proxy_name = "" if proxy is None else proxy.name
    job.last_apply, job.last_generation = now, job.session.generation


def _apply_planner_preview(job, result, root, scene, fiber, now):
    proxy = register_fiber_sync().apply_points(
        root, scene, fiber, result.points, bake=False, commit=False)
    if proxy is not None:
        proxy["af_fiber_display_mode"] = "PLANNER_PREVIEW"
        proxy["af_fiber_output_state"] = "STALE"
    job.proxy_name = "" if proxy is None else proxy.name
    job.last_apply, job.last_generation = now, job.session.generation


def _apply_planner_result(job, result, root, scene, fiber, now):
    if str(result.termination_reason) == FiberTermination.PLANNER_PREVIEW.value:
        _apply_planner_preview(job, result, root, scene, fiber, now)
        return
    restored = _restore_fiber_output(
        root, scene, fiber, stale=True, fallback=job.previous_points)
    proxy = restored or _find_proxy(scene, root.name, fiber.id)
    if restored is None and proxy is not None:
        register_fiber_sync()._clear_curve_points(proxy)
    job.proxy_name = "" if proxy is None else proxy.name
    job.last_apply, job.last_generation = now, job.session.generation


def _retain_safe_preview(job, commit, now):
    if not job.retain_preview or commit:
        return False
    job.last_apply, job.last_generation = now, job.session.generation
    return True


def _finish_job(job, result=None):
    reason = _invalid_job_reason(job)
    if reason:
        _terminate_job(job, reason, mark_unknown=True, stale=True)
        return
    result = result or job.session.result()
    _store_result(_owned_job_data(job)[2], result)
    if _planner_preview_result(result):
        _finish_planner_preview_job(job)
        return
    _finish_refined_job(job, result)


def _finish_refined_job(job, result):
    committed = bool(job.output_committed and _commit_allowed(job, result))
    kept = bool(not committed and _keep_failed_preview(job, result))
    _restore_previous_output(job, stale=True) if not committed and not kept else None
    _finish_pending_version(job, committed)
    publish_fiber_cache(job.session, result) if committed else None
    telemetry_cache_snapshot(getattr(job.session, "telemetry", None))
    _detach_job(job)
    _sync_final(job) if committed else None


def _keep_failed_preview(job, result):
    root, scene, fiber = _owned_job_data(job)
    points = _failed_preview_points(job, result, fiber)
    if root is None or scene is None or fiber is None or not points:
        return False
    proxy = register_fiber_sync().apply_points(root, scene, fiber, points, commit=False)
    if proxy is None:
        return False
    proxy["af_fiber_display_mode"] = "FAILED_PREVIEW"
    mark_fiber_output_stale(scene, root.name, fiber.id)
    job.proxy_name = proxy.name
    return True


def _failed_preview_points(job, result, fiber):
    if fiber is None or str(getattr(job.session, "quality", "FINAL")) != "INTERACTIVE":
        return ()
    if _pending_version(fiber) == 2 or getattr(result, "invalid_reason", ""):
        return ()
    points = tuple(getattr(result, "points", ()) or ())
    expected = int(getattr(job.session, "params", {}).get("node_count", 0))
    finite = all(all(isfinite(float(value)) for value in point) for point in points)
    return points if len(points) == expected and finite else ()


def _finish_planner_preview_job(job):
    _finish_pending_version(job, False)
    telemetry_cache_snapshot(getattr(job.session, "telemetry", None))
    _detach_job(job)


def _planner_preview_result(result):
    reasons = (FiberTermination.PLANNER_PREVIEW.value,
               FiberTermination.NO_FEASIBLE_PATH.value)
    return str(getattr(result, "termination_reason", "")) in reasons


def _commit_allowed(job, result):
    if not (_valid_job(job) and result.done and not result.invalid_reason):
        return False
    fiber = _owned_job_data(job)[2]
    if _pending_version(fiber) == 2 and not result.converged:
        return False
    expected = int(job.session.params.get("node_count", 0))
    finite = all(all(isfinite(float(value)) for value in point) for point in result.points)
    valid = len(result.points) == expected and finite and _result_safe(fiber, result)
    return bool(valid and _surface_route_clear(job, result))


def _result_safe(fiber, result):
    if int(getattr(fiber, "solver_version", 1) or 1) >= 2:
        return bool(result.converged and float(result.max_pen) < 1.0e-5)
    if not _requires_collision_truth(fiber):
        return True
    return float(result.max_pen) < 1.0e-5


def _requires_collision_truth(fiber):
    return bool(getattr(fiber, "use_segment_collisions", False) or
                len(tuple(getattr(fiber, "mid_touches", ()) or ())))


def _surface_route_clear(job, result):
    fiber = _owned_job_data(job)[2]
    if fiber is None or not fiber.use_surface_routing:
        return True
    if len(fiber.mid_touches):
        return True
    owner = str(fiber.a_parent_id or "")
    if not owner or owner != str(fiber.b_parent_id or ""):
        return True
    collider = job.session.oracle.collider_by_id(owner)
    if collider is None:
        return True
    return _owner_surface_curve_clear(job, result.points, collider)


def _owner_surface_curve_clear(job, points, collider):
    if any(job.session.oracle.push_out_point(p, (collider,))[1] >= 1.0e-5 for p in points[1:-1]):
        return False
    hits = job.session.oracle.segment_hit_samples
    return not any(hits(a, b, (collider,)) for a, b in zip(points[:-1], points[1:]))


def _finish_pending_version(job, committed):
    fiber = _owned_job_data(job)[2]
    if fiber is None or not _job_owns_pending(job, fiber):
        return
    if committed:
        _set_solver_version(fiber, 2)
    _clear_pending_version(fiber)


def _restore_previous_output(job, stale=False):
    root, scene, fiber = _owned_job_data(job)
    if root is None or fiber is None:
        return
    fallback = job.previous_points if job.retain_preview and _pending_version(fiber) != 2 else ()
    _restore_fiber_output(root, scene, fiber, stale=stale, fallback=fallback)


def _restore_fiber_output(root, scene, fiber, stale=False, fallback=()):
    points = list(fallback or ()) or _rollback_points(scene, root.name, fiber)
    if not points:
        return None
    proxy = register_fiber_sync().apply_points(root, scene, fiber, points, commit=False)
    if proxy is not None:
        proxy.pop("af_fiber_display_mode", None)
    if stale:
        mark_fiber_output_stale(scene, root.name, fiber.id)
    else:
        mark_fiber_output_current(proxy, increment=False)
    return proxy


def _rollback_points(scene, root_name, fiber):
    raw = str(getattr(fiber, "legacy_points_json", "") or "") if _pending_version(fiber) == 2 else ""
    if raw:
        return _json_points(raw)
    return persisted_fiber_points(scene, root_name, fiber.id)


def _json_points(raw):
    import json
    from mathutils import Vector
    try:
        return [Vector(tuple(float(value) for value in row[:3])) for row in json.loads(raw)]
    except Exception:
        return None


def _set_solver_version(fiber, version):
    from ..vcp.prop_update_guard import suppress_vcp_prop_updates
    with suppress_vcp_prop_updates():
        fiber.solver_version = int(version)


def _pending_version(fiber):
    try:
        return int(fiber.get("af_pending_solver_version", 0) or 0)
    except Exception:
        return 0


def _clear_pending_version(fiber):
    for key in ("af_pending_solver_version", "af_pending_solver_token"):
        try:
            del fiber[key]
        except Exception:
            pass


def _claim_pending_version(fiber, token):
    if _pending_version(fiber) == 2:
        fiber["af_pending_solver_token"] = int(token)


def _job_owns_pending(job, fiber):
    if _pending_version(fiber) != 2:
        return False
    return int(fiber.get("af_pending_solver_token", 0) or 0) == job.token


def _next_token(fiber):
    token = int(fiber.get("af_fiber_request_token", 0)) + 1
    fiber["af_fiber_request_token"] = token
    return token


def _store_result(fiber, result):
    set_fiber_not_converged(fiber, not result.converged)
    set_fiber_recompute_status(fiber, _result_status(result))
    set_fiber_recompute_ms(fiber, result.planner_ms + result.refine_ms)
    set_fiber_eps_disp(fiber, result.max_disp)
    set_fiber_eps_pen(fiber, result.max_pen)
    set_fiber_route_mode(fiber, result.mode)
    set_fiber_planner_ms(fiber, result.planner_ms)
    set_fiber_refine_ms(fiber, result.refine_ms)
    set_fiber_active_colliders(fiber, result.active_count)
    set_fiber_invalid_reason(fiber, result.invalid_reason)


def _result_status(result):
    reason = str(getattr(result, "termination_reason", ""))
    if reason in (FiberTermination.PLANNER_PREVIEW.value,
                  FiberTermination.NO_FEASIBLE_PATH.value):
        return reason
    return "CONVERGED" if result.converged else "NOT_CONVERGED"


def _sync_final(job):
    root, scene, fiber = _owned_job_data(job)
    if root is None or scene is None or fiber is None:
        return
    payload = {"solved_fiber_ids": [fiber.id]}
    _sync_scene()(root=root, scene=scene, dirty_hints=dirty_hints_for("FIBER", {fiber.id}),
                  source="fiber_refinement", event_type="FIBER_SOLVE_READY", payload=payload)


def _abort_request(key, root, scene, fiber):
    job = _JOBS.get(key)
    if job is not None:
        _terminate_job(job, FiberTermination.CANCELLED, mark_unknown=True, stale=True)
        return
    _restore_fiber_output(root, scene, fiber, stale=True)
    _clear_pending_version(fiber)


def _supersede_job(key):
    job = _JOBS.get(key)
    if job is None:
        return None
    _mark_terminated(job, FiberTermination.SUPERSEDED)
    _detach_job(job)
    return job


def _terminate_key(key, reason, mark_unknown):
    job = _JOBS.get(key)
    if job is not None:
        _terminate_job(job, reason, mark_unknown)


def _terminate_job(job, reason, mark_unknown, stale=False):
    if _JOBS.get(job.key) is not job:
        _mark_terminated(job, reason)
        return
    fiber = _owned_job_data(job)[2]
    _restore_previous_output(job, stale=stale)
    if fiber is not None and _job_owns_pending(job, fiber):
        _clear_pending_version(fiber)
    _restore_job_status(job, fiber, mark_unknown)
    _mark_terminated(job, reason)
    _detach_job(job)


def _restore_job_status(job, fiber, mark_unknown):
    if fiber is None:
        return
    status = "UNKNOWN" if mark_unknown else job.previous_status
    set_fiber_recompute_status(fiber, status)


def _mark_terminated(job, reason):
    job.session.termination_reason = FiberTermination(reason).value
    job.session.converged = False
    job.session.done = True


def _detach_job(job):
    if _JOBS.get(job.key) is not job:
        return
    _JOBS.pop(job.key, None)
    while job.key in _QUEUE:
        _QUEUE.remove(job.key)


def _valid_job(job):
    return _invalid_job_reason(job) is None


def _invalid_job_reason(job):
    root, scene, fiber = _owned_job_data(job)
    if root is None or scene is None or fiber is None:
        return FiberTermination.CANCELLED
    if int(fiber.get("af_fiber_request_token", 0)) != job.token:
        return FiberTermination.SUPERSEDED
    if _fiber_signature(fiber) != job.signature:
        return FiberTermination.CANCELLED
    if _current_geometry_signature(job.session) != job.geometry_signature:
        return FiberTermination.CANCELLED
    return None


def _resolved_job_data(job):
    scene = _by_uid(bpy.data.scenes, job.scene_uid)
    root = None if scene is None else _by_uid(scene.objects, job.root_uid)
    vcp = None if root is None else getattr(root, "af_vcp_system", None)
    fibers = () if vcp is None else vcp.fibers
    fiber = next((item for item in fibers if item.id == job.fiber_id), None)
    return root, scene, fiber


def _owned_job_data(job):
    root, scene, fiber = _resolved_job_data(job)
    if fiber is not None and _id_pointer(fiber) != job.fiber_uid:
        fiber = None
    return root, scene, fiber


def _by_uid(values, uid):
    return next((item for item in values if _id_uid(item) == int(uid)), None)


def _fiber_signature(fiber):
    fields = ("a_parent_id", "a_attach_param", "b_parent_id", "b_attach_param", "node_count",
              "iterations_bake", "use_surface_routing", "use_segment_collisions",
              "bend_stiffness", "stretch_stiffness", "topology_mode", "solver_version",
              "collision_radius", "symmetry_mode", "symmetry_axis", "use_warm_start",
              "preview_planner_route")
    values = tuple(_signature_value(getattr(fiber, name, None)) for name in fields)
    values += (tuple(float(value) for value in fiber.symmetry_origin),)
    touches = tuple((item.parent_id, item.attach_param, float(item.normal_offset)) for item in fiber.mid_touches)
    anchors = tuple((item.parent_id, item.attach_param) for item in fiber.loop_anchors)
    return values, touches, anchors


def _signature_value(value):
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    try:
        return tuple(value)
    except TypeError:
        return repr(value)


def _geometry_signature(session):
    return tuple((item["sid"], item["obj"].name, item["stamp"]) for item in session.oracle.colliders())


def _current_geometry_signature(session):
    rows = []
    for item in session.oracle.colliders():
        obj = bpy.data.objects.get(item["obj"].name)
        stamp = None if obj is None else _collider_stamp(obj)
        rows.append((item["sid"], item["obj"].name, stamp))
    return tuple(rows)


@persistent
def _on_depsgraph_update(scene, depsgraph):
    for job in tuple(_JOBS.values()):
        if job.scene_uid == _id_uid(scene) and _job_geometry_updated(job, depsgraph):
            _terminate_job(job, FiberTermination.CANCELLED, mark_unknown=True, stale=True)


def _job_geometry_updated(job, depsgraph):
    changed = {_id_pointer(item.id) for item in depsgraph.updates if _geometry_update(item)}
    for item in job.session.oracle.colliders():
        obj, data = item["obj"], getattr(item["obj"], "data", None)
        if _id_pointer(obj) in changed or _id_pointer(data) in changed:
            return True
    return False


def _geometry_update(update):
    return bool(getattr(update, "is_updated_geometry", False) or
                getattr(update, "is_updated_transform", False))


def _id_pointer(value):
    try:
        return int(value.as_pointer())
    except Exception:
        return 0


def _id_uid(value):
    return int(getattr(value, "session_uid", 0) or _id_pointer(value))


def _mark_refining(fiber):
    set_fiber_not_converged(fiber, False)
    set_fiber_recompute_status(fiber, "REFINING")
    set_fiber_invalid_reason(fiber, "")
    try:
        fiber["af_prefer_bake"] = False
    except Exception:
        pass


def _job_key(scene, root, fiber_id):
    return _id_uid(scene), _id_uid(root), str(fiber_id)


def _scene_name(scene):
    return "" if scene is None else str(getattr(scene, "name", "") or "")


def _fiber_for_scene(scene, fiber_id):
    if scene is None:
        return None
    roots = [obj for obj in scene.objects if obj.get("anthroforge_root")]
    fibers = () if not roots else roots[0].af_vcp_system.fibers
    return next((fiber for fiber in fibers if fiber.id == str(fiber_id)), None)


def _find_proxy(scene, root_name, fiber_id):
    if scene is None:
        return None
    return next((obj for obj in scene.objects if obj.get("af_fiber_proxy") and
                 obj.get("af_root_name") == root_name and obj.get("af_fiber_id") == fiber_id), None)


def _planner_preview_visible(scene, root_name, fiber_id):
    proxy = _find_proxy(scene, root_name, fiber_id)
    return proxy is not None and proxy.get("af_fiber_display_mode") == "PLANNER_PREVIEW"


def _displayed_points(scene, root_name, fiber_id):
    obj = _find_proxy(scene, root_name, fiber_id)
    splines = () if obj is None else tuple(getattr(obj.data, "splines", ()))
    if not splines:
        return ()
    return tuple(obj.matrix_world @ point.co.xyz for point in splines[0].points)


def _depsgraph(scene):
    layer = None if scene is None else scene.view_layers[0]
    None if layer is None else layer.update()
    return None if layer is None else layer.depsgraph


def _sync_scene():
    try:
        from ...app.runtime_api import sync_scene
    except ImportError:
        from app.runtime_api import sync_scene
    return sync_scene


def _drop_timer():
    active = getattr(bpy.app.timers, "is_registered", None)
    cancel = getattr(bpy.app.timers, "unregister", None)
    if callable(active) and callable(cancel) and active(_flush_one):
        cancel(_flush_one)


@persistent
def _on_history_pre(_dummy):
    global _PAUSED
    _PAUSED = []
    shutdown_fiber_refinements(mark_unknown=False)


@persistent
def _on_history_post(_dummy):
    return None


def _resume_paused():
    global _PAUSED
    rows, _PAUSED = tuple(_PAUSED), []
    for scene_name, root_name, fiber_id in rows:
        _resume_one(scene_name, root_name, fiber_id)
    return None


def _resume_one(scene_name, root_name, fiber_id):
    scene = bpy.data.scenes.get(scene_name)
    root = None if scene is None else scene.objects.get(root_name)
    fibers = () if root is None else root.af_vcp_system.fibers
    fiber = next((item for item in fibers if item.id == fiber_id), None)
    if fiber is not None:
        request_fiber_refinement(root, scene, fiber, show_preview=False)


@persistent
def _on_load_pre(_dummy):
    global _PAUSED
    _PAUSED = []
    shutdown_fiber_refinements(mark_unknown=False)
    register_fiber_sync().clear_solver_cache()


def register_fiber_refinement_runtime():
    _append_handler(bpy.app.handlers.load_pre, _on_load_pre)
    _append_handler(bpy.app.handlers.depsgraph_update_post, _on_depsgraph_update)
    for seq in (bpy.app.handlers.undo_pre, bpy.app.handlers.redo_pre):
        _append_handler(seq, _on_history_pre)
    for seq in (bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        _append_handler(seq, _on_history_post)


def unregister_fiber_refinement_runtime():
    shutdown_fiber_refinements(mark_unknown=False)
    _remove_handler(bpy.app.handlers.load_pre, _on_load_pre)
    _remove_handler(bpy.app.handlers.depsgraph_update_post, _on_depsgraph_update)
    for seq in (bpy.app.handlers.undo_pre, bpy.app.handlers.redo_pre):
        _remove_handler(seq, _on_history_pre)
    for seq in (bpy.app.handlers.undo_post, bpy.app.handlers.redo_post):
        _remove_handler(seq, _on_history_post)


def _append_handler(seq, fn):
    if fn not in seq:
        seq.append(fn)


def _remove_handler(seq, fn):
    if fn in seq:
        seq.remove(fn)
