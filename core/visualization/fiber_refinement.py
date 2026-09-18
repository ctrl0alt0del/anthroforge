from collections import deque
from dataclasses import dataclass, field
from math import isfinite
import os
from time import monotonic

import bpy
from bpy.app.handlers import persistent

from ..deps.dirty_hints import dirty_hints_for
from ..deps.runtime_trace import (activate_request_telemetry, restore_request_telemetry,
                                  telemetry_cache_snapshot, telemetry_count,
                                  telemetry_timing)
from ..vcp.fiber_collision import _collider_stamp
from ..vcp.fiber_anchor_preflight import (anchor_preflight_summary,
                                           preflight_fiber_hard_anchors)
from ..vcp.fiber_engine import FiberTermination
from ..vcp.fiber_progressive import begin_fiber_solve, publish_fiber_cache
from ..vcp.fiber_v2_runtime import (clear_v3_runtime_warm_cache,
                                    retain_v3_warm_state)
from ..vcp.v3.batch import V3BatchCoordinator
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
from .fiber_engine_migration import (claim_engine_migration, clear_engine_migration,
                                     commit_engine_migration, migration_owned,
                                     pending_engine_points, prepare_engine_migration,
                                     rollback_engine_migration, write_engine_provenance)
from .fiber_sync_helpers import mark_fiber_output_current, mark_fiber_output_stale, persisted_fiber_points


_SLICE_MS = 12.0
_TIMER_INTERVAL = 0.001
_ASYNC_POLL_INTERVAL = 0.005
_DRAW_INTERVAL = 0.05
_JOBS = {}
_QUEUE = deque()
_V3_BATCH = V3BatchCoordinator()
_BATCH_COMMITS = None
_LAST_V3_BATCH_REPORT = None
_LAST_BATCH_PRIORITY_REFRESH = 0.0
_TIMER_ARMED = False
_PAUSED = []
_GROUPS = {}
_GROUP_COUNTER = 0
_GROUP_LIMIT = 32


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
    last_geometry_check: float = 0.0
    group_token: str = ""


@dataclass
class FiberRefinementGroup:
    token: str
    scene_uid: int
    root_uid: int
    root_name: str
    scene_name: str
    targets: tuple
    pending: set = field(default_factory=set)
    committed: set = field(default_factory=set)
    failures: dict = field(default_factory=dict)
    done: bool = False


def request_fiber_refinement(root, scene, fiber, show_preview=False, quality="FINAL", group_token=""):
    if root is None or scene is None or fiber is None:
        return RefinementRequest(False, "Fiber refinement context is unavailable.")
    key = _job_key(scene, root, fiber.id)
    preflight = _hard_anchor_preflight(root, scene, fiber, quality)
    if show_preview and preflight is not None and not preflight.valid:
        preflight = _repair_current_preflight(root, scene, fiber, preflight)
    if preflight is not None and not preflight.valid:
        return _reject_anchor_preflight(key, root, scene, fiber, preflight, show_preview)
    session = _prepared_session(root, scene, fiber, quality)
    if session.invalid_reason:
        _abort_request(key, root, scene, fiber, session)
        return RefinementRequest(False, session.invalid_reason)
    return _launch_refinement(key, root, scene, fiber, session, show_preview, group_token)


def request_fiber_refinement_group(root, scene, fiber_ids, quality="FINAL"):
    group = _new_refinement_group(root, scene, fiber_ids)
    fibers = {str(row.id): row for row in root.af_vcp_system.fibers}
    for fiber_id in group.targets:
        fiber = fibers.get(fiber_id)
        request = None if fiber is None else request_fiber_refinement(
            root, scene, fiber, show_preview=False, quality=quality, group_token=group.token)
        if request is None or not request.ok: _group_member_done(group.token, fiber_id, False, _request_error(request))
    _finish_group_if_ready(group)
    return group.token


def fiber_refinement_group_state(token):
    group = _GROUPS.get(str(token or ""))
    if group is None: return None
    return {"token": group.token, "targets": group.targets, "pending": tuple(sorted(group.pending)),
            "committed": tuple(sorted(group.committed)), "failures": dict(group.failures),
            "done": bool(group.done)}


def cancel_fiber_refinement_group(token):
    group = _GROUPS.get(str(token or ""))
    if group is None or group.done: return False
    for key, job in tuple(_JOBS.items()):
        if _job_group_token(job) == group.token: _terminate_job(job, FiberTermination.CANCELLED, True, stale=True)
    for fiber_id in tuple(group.pending): _group_member_done(group.token, fiber_id, False, "CANCELLED")
    return True


def _new_refinement_group(root, scene, fiber_ids):
    global _GROUP_COUNTER
    _GROUP_COUNTER += 1; token = f"fiber-group-{_GROUP_COUNTER}"
    targets = tuple(sorted({str(value) for value in fiber_ids if str(value or "")}))
    group = FiberRefinementGroup(token, _id_uid(scene), _id_uid(root), root.name, scene.name,
                                 targets, pending=set(targets))
    _GROUPS[token] = group; _trim_groups(); return group


def _request_error(request):
    return "MISSING_FIBER" if request is None else str(request.error or "REQUEST_FAILED")


def _launch_refinement(key, root, scene, fiber, session, show_preview, group_token=""):
    _supersede_job(key)
    job = _new_job(key, scene, root, fiber, session, group_token)
    mark_fiber_output_stale(scene, root.name, fiber.id)
    proxy = _initial_proxy(job, show_preview)
    return _start_or_finish(job, proxy)


def _hard_anchor_preflight(root, scene, fiber, quality):
    sync = register_fiber_sync()
    return preflight_fiber_hard_anchors(root, scene, fiber, sync._solver,
                                        _depsgraph(scene), quality)


def _repair_current_preflight(root, scene, fiber, result):
    from ..vcp.fiber_pin_repair import repair_current_preflight_pins
    sync = register_fiber_sync(); depsgraph = _depsgraph(scene)
    return repair_current_preflight_pins(root, scene, fiber, result, sync._solver, depsgraph)


def _reject_anchor_preflight(key, root, scene, fiber, result, show_preview=False):
    job = _JOBS.get(key)
    if job is not None:
        _terminate_job(job, FiberTermination.CANCELLED, mark_unknown=False, stale=False)
    rollback_engine_migration(fiber)
    if show_preview: _show_invalid_anchor_preview(root, scene, fiber, result)
    mark_fiber_output_stale(scene, root.name, fiber.id)
    summary = anchor_preflight_summary(result)
    set_fiber_invalid_reason(fiber, summary)
    set_fiber_recompute_status(fiber, FiberTermination.INVALID_ATTACHMENT.value)
    set_fiber_not_converged(fiber, True)
    return RefinementRequest(False, summary)


def _show_invalid_anchor_preview(root, scene, fiber, result):
    source = persisted_fiber_points(scene, root.name, fiber.id) or ()
    points = _warped_anchor_preview(source, getattr(result, "anchors", ()), fiber)
    if not points: return None
    proxy = register_fiber_sync().apply_points(root, scene, fiber, points, commit=False)
    if proxy is not None: proxy["af_fiber_display_mode"] = "FAILED_PREVIEW"
    return proxy


def _warped_anchor_preview(source, anchors, fiber):
    if str(getattr(fiber, "topology_mode", "OPEN")) != "OPEN": return ()
    if len(source) < 2 or len(anchors) < 2: return ()
    from mathutils import Vector
    from ..vcp.v3.warm import _pin_indices
    rows = [point.copy() for point in source]
    pins = _pin_indices(anchors, len(rows))
    deltas = [Vector(anchor.point) - rows[index] for index, anchor in zip(pins, anchors)]
    for span in range(len(pins) - 1): _warp_anchor_span(rows, pins, deltas, span)
    for index, anchor in zip(pins, anchors): rows[index] = Vector(anchor.point)
    return rows


def _warp_anchor_span(points, pins, deltas, span):
    first, second = int(pins[span]), int(pins[span + 1])
    count = max(1, second - first); low, high = deltas[span], deltas[span + 1]
    for index in range(first, second + 1):
        factor = (index - first) / count
        points[index] += (1.0 - factor) * low + factor * high


def _prepared_session(root, scene, fiber, quality):
    from ..vcp.fiber_engine_registry import selection_for_fiber
    _retain_previous_v3_warm(root, scene, fiber)
    selection = selection_for_fiber(fiber)
    prepare_engine_migration(root, scene, fiber, selection)
    return begin_fiber_solve(register_fiber_sync()._solver, root, fiber, scene,
                             _depsgraph(scene), quality, selection=selection)


def _retain_previous_v3_warm(root, scene, fiber):
    job = _JOBS.get(_job_key(scene, root, fiber.id))
    if job is not None: retain_v3_warm_state(job.session)


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
    _V3_BATCH.clear()
    _QUEUE.clear()
    _GROUPS.clear()
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


def _new_job(key, scene, root, fiber, session, group_token=""):
    token = _next_token(fiber); previous = _displayed_points(scene, root.name, fiber.id)
    retain = bool(previous and fiber.use_surface_routing and
                  not _planner_preview_visible(scene, root.name, fiber.id) and
                  not tuple(getattr(session, "warm_seed", ()) or ()))
    job = FiberRefinementJob(key, scene.name, root.name, _id_uid(scene), _id_uid(root),
                             _id_pointer(fiber), fiber.id, _fiber_signature(fiber),
                             _geometry_signature(session), session, token=token,
                             previous_status=fiber_recompute_status(fiber),
                             previous_points=previous,
                             retain_preview=retain, group_token=str(group_token or ""))
    claim_engine_migration(fiber, token)
    job.last_apply, job.last_generation = monotonic(), session.generation
    job.last_geometry_check = job.last_apply
    return job


def _initial_proxy(job, show_preview):
    root, scene, fiber = _resolved_job_data(job)
    proxy = _find_proxy(scene, root.name, fiber.id)
    if job.retain_preview:
        job.proxy_name = "" if proxy is None else proxy.name
        return proxy
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
    _register_batch_job(job)
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
    key = _QUEUE[0]
    job = _JOBS.get(key)
    _flush_v3_batch() if _batch_job_enabled(job) else _flush_serial_key(key)
    _TIMER_ARMED = bool(_QUEUE)
    return _refinement_interval()


def _refinement_interval():
    if not _QUEUE: return None
    return _ASYNC_POLL_INTERVAL if _V3_BATCH.async_pending else _TIMER_INTERVAL


def _flush_serial_key(key):
    _QUEUE.popleft()
    job = _JOBS.get(key)
    if job is not None: _advance_job(job)
    if key in _JOBS: _QUEUE.append(key)


def _flush_v3_batch():
    global _LAST_V3_BATCH_REPORT
    report = None; _refresh_batch_priorities(); _begin_batch_publication()
    try: report = _V3_BATCH.step(_SLICE_MS, _advance_batch_key)
    except Exception as error: _fail_v3_batch(error)
    finally: _end_batch_publication()
    if report is None: return
    _LAST_V3_BATCH_REPORT = report
    _record_batch_report(report); _rotate_batch_keys(report.selected)


def _fail_v3_batch(error):
    for key in tuple(_V3_BATCH.entries):
        job = _JOBS.get(key)
        if job is None: continue
        job.session.runtime_error = f"V3 batch executor failed: {error}"
        _terminate_job(job, FiberTermination.UNSAFE_OUTPUT, mark_unknown=False, stale=True)


def _advance_batch_key(key):
    job = _JOBS.get(key)
    if job is not None: _advance_job(job)


def _rotate_batch_keys(keys):
    for key in keys:
        while key in _QUEUE: _QUEUE.remove(key)
        if key in _JOBS: _QUEUE.append(key)


def _record_batch_report(report):
    count = max(1, len(report.selected))
    for key in report.selected:
        job = _JOBS.get(key)
        if job is None: continue
        telemetry_timing("v3_batch_wall_share", report.elapsed_ms / count, job.session.telemetry)
        telemetry_timing("v3_batch_native_share", report.native_ms / count, job.session.telemetry)
        telemetry_count("v3_batch_parallel_step", int(report.workers > 1), job.session.telemetry)


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
    _apply_progress(job, result, known_valid=True)
    if result.done:
        _finish_job(job, result)


def _apply_progress(job, result, known_valid=False):
    if not known_valid and not _valid_job(job):
        return
    if _async_native_pending(job, result): return
    now = monotonic()
    changed_level = not _is_v3_job(job) and job.last_generation != job.session.generation
    if not (result.done or changed_level or now - job.last_apply >= _DRAW_INTERVAL):
        return
    root, scene, fiber = _resolved_job_data(job)
    if _planner_preview_result(result):
        _apply_planner_result(job, result, root, scene, fiber, now)
        return
    _apply_refined_geometry(job, result, root, scene, fiber, now)


def _async_native_pending(job, result):
    if result.done or not _is_v3_job(job): return False
    core = getattr(job.session, "core_session", None)
    run = getattr(core, "native_run", None)
    return bool(run is not None and getattr(run, "async_task", 0))


def _apply_refined_geometry(job, result, root, scene, fiber, now):
    commit = bool(result.done and _commit_allowed(job, result))
    if _retain_safe_preview(job, commit, now):
        return
    proxy = register_fiber_sync().apply_points(root, scene, fiber, result.points,
                                               bake=_job_bake(job, result), commit=commit)
    _set_refinement_display(proxy, result)
    job.output_committed = bool(result.done and commit and proxy is not None)
    job.proxy_name = "" if proxy is None else proxy.name
    job.last_apply, job.last_generation = now, job.session.generation


def _set_refinement_display(proxy, result):
    if proxy is None: return
    mode = str(getattr(result, "display_mode", "") or "")
    if mode: proxy["af_fiber_display_mode"] = mode; proxy["af_fiber_output_state"] = "STALE"
    else: proxy.pop("af_fiber_display_mode", None)


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
    reason = _invalid_job_reason(job, force_geometry=True)
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
    _refresh_node_attachments(job, result) if committed else None
    _publish_commit_identity(job, result) if committed else None
    _finish_pending_version(job, committed)
    _publish_result_cache(job, result) if committed else None
    telemetry_cache_snapshot(getattr(job.session, "telemetry", None))
    _detach_job(job)
    _finish_group_member(job, committed, result)
    _sync_final(job) if committed and not _job_group_token(job) else None


def _publish_commit_identity(job, result):
    root, scene, fiber = _owned_job_data(job)
    proxy = _find_proxy(scene, root.name, fiber.id) if root and scene and fiber else None
    _commit_provenance(job, result, fiber, proxy)


def _refresh_node_attachments(job, result):
    root, scene, fiber = _owned_job_data(job)
    if root is None or scene is None or fiber is None: return False
    from .fiber_node_attachment_runtime import capture_committed_fiber_node_attachments
    return capture_committed_fiber_node_attachments(root, scene, fiber, result.points)


def _publish_result_cache(job, result):
    engine = str(getattr(result, "engine", "V1"))
    if engine == "V1": publish_fiber_cache(job.session, result)
    if engine == "V3": retain_v3_warm_state(job.session, result)
    if engine != "V3": _clear_job_v3_warm(job)


def _clear_job_v3_warm(job):
    root, scene, fiber = _owned_job_data(job)
    if root is not None and scene is not None and fiber is not None:
        clear_v3_runtime_warm_cache(scene, root, {fiber.id})


def _keep_failed_preview(job, result):
    if getattr(job, "retain_preview", False):
        return _mark_retained_failed_preview(job)
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


def _mark_retained_failed_preview(job):
    root, scene, fiber = _owned_job_data(job)
    proxy = _find_proxy(scene, root.name, fiber.id) if root and scene and fiber else None
    if proxy is None:
        return False
    proxy["af_fiber_display_mode"] = "FAILED_PREVIEW"
    mark_fiber_output_stale(scene, root.name, fiber.id)
    return True


def _failed_preview_points(job, result, fiber):
    if fiber is None or str(getattr(job.session, "quality", "FINAL")) != "INTERACTIVE":
        return ()
    if getattr(result, "invalid_reason", ""):
        return ()
    points = tuple(getattr(result, "points", ()) or ())
    expected = int(getattr(job.session, "params", {}).get("node_count", 0))
    finite = all(all(isfinite(float(value)) for value in point) for point in points)
    failed = str(getattr(result, "termination_reason", "")) in {
        FiberTermination.BLOCKED.value, FiberTermination.NO_FEASIBLE_PATH.value}
    valid_count = len(points) >= 2 if failed else len(points) == expected
    return points if valid_count and finite else ()


def _job_bake(job, result):
    quality = str(getattr(job.session, "quality", "INTERACTIVE") or "INTERACTIVE")
    return bool(result.done and quality == "FINAL")


def _finish_planner_preview_job(job):
    _finish_pending_version(job, False)
    telemetry_cache_snapshot(getattr(job.session, "telemetry", None))
    _detach_job(job)
    _group_member_done(_job_group_token(job), job.fiber_id, False, "PLANNER_PREVIEW")


def _planner_preview_result(result):
    return str(getattr(result, "termination_reason", "")) == FiberTermination.PLANNER_PREVIEW.value


def _commit_allowed(job, result):
    if not (_valid_job(job, force_geometry=True) and result.done and not result.invalid_reason):
        return False
    if not _termination_committable(result):
        return False
    fiber = _owned_job_data(job)[2]
    if _pending_version(fiber) in (2, 3) and not _validated_result(result):
        return False
    expected = int(job.session.params.get("node_count", 0))
    finite = all(all(isfinite(float(value)) for value in point) for point in result.points)
    valid = len(result.points) == expected and finite and _result_safe(fiber, result)
    return bool(valid and _surface_route_clear(job, result))


def _termination_committable(result):
    if str(getattr(result, "engine", "V1")) not in {"V2", "V3"}:
        return True
    allowed = {FiberTermination.CONVERGED.value, FiberTermination.STALLED.value,
               FiberTermination.BUDGET_EXHAUSTED.value}
    return str(getattr(result, "termination_reason", "")) in allowed


def _result_safe(fiber, result):
    if str(getattr(result, "engine", "V1")) in {"V2", "V3"}:
        return _validated_result(result)
    if not _requires_collision_truth(fiber):
        return True
    return float(result.max_pen) < 1.0e-5


def _validated_result(result):
    return bool(getattr(result, "validated", False))


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
    if fiber is None or not migration_owned(fiber, job.token):
        return
    if committed:
        commit_engine_migration(fiber, job.session.selection, job.token)
    else:
        rollback_engine_migration(fiber, job.token)


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
    pending = pending_engine_points(fiber)
    if pending:
        return _vector_points(pending)
    return persisted_fiber_points(scene, root_name, fiber.id)


def _vector_points(points):
    from mathutils import Vector
    return [Vector(row) for row in points]


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
    clear_engine_migration(fiber)


def _claim_pending_version(fiber, token):
    claim_engine_migration(fiber, token)


def _job_owns_pending(job, fiber):
    return migration_owned(fiber, job.token)


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
    if getattr(result, "engine_version", "") and reason:
        return reason
    return "CONVERGED" if result.converged else "NOT_CONVERGED"


def _sync_final(job):
    root, scene, fiber = _owned_job_data(job)
    if root is None or scene is None or fiber is None:
        return
    if _BATCH_COMMITS is not None:
        _BATCH_COMMITS.append((root, scene, fiber.id))
        return
    _sync_fiber_group(root, scene, {fiber.id})


def _sync_fiber_group(root, scene, fiber_ids):
    ids = set(fiber_ids)
    payload = {"solved_fiber_ids": sorted(ids)}
    _sync_scene()(root=root, scene=scene, dirty_hints=dirty_hints_for("FIBER", ids),
                  source="fiber_refinement", event_type="FIBER_SOLVE_READY", payload=payload)


def _finish_group_member(job, committed, result):
    token = _job_group_token(job)
    if not token: return
    reason = str(getattr(result, "termination_reason", "") or "FAILED")
    _group_member_done(token, job.fiber_id, committed, reason)


def _job_group_token(job):
    return str(getattr(job, "group_token", "") or "")


def _group_member_done(token, fiber_id, committed, reason):
    group = _GROUPS.get(str(token or ""))
    if group is None or group.done: return
    fiber_id = str(fiber_id); group.pending.discard(fiber_id)
    if committed: group.committed.add(fiber_id)
    else: group.failures[fiber_id] = str(reason or "FAILED")
    _finish_group_if_ready(group)


def _finish_group_if_ready(group):
    if group is None or group.done or group.pending: return
    group.done = True; root, scene = _group_data(group)
    if root is not None and scene is not None and group.committed:
        _sync_fiber_group(root, scene, group.committed)


def _group_data(group):
    scene = bpy.data.scenes.get(group.scene_name)
    root = None if scene is None else scene.objects.get(group.root_name)
    if scene is None or root is None: return None, None
    if _id_uid(scene) != group.scene_uid or _id_uid(root) != group.root_uid: return None, None
    return root, scene


def _trim_groups():
    completed = [key for key, group in _GROUPS.items() if group.done]
    while len(_GROUPS) > _GROUP_LIMIT and completed: _GROUPS.pop(completed.pop(0), None)


def _begin_batch_publication():
    global _BATCH_COMMITS
    _BATCH_COMMITS = []
    register_fiber_sync().begin_point_batch()


def _end_batch_publication():
    global _BATCH_COMMITS
    rows, _BATCH_COMMITS = tuple(_BATCH_COMMITS or ()), None
    register_fiber_sync().end_point_batch()
    for root, scene, ids in _group_batch_commits(rows):
        _sync_fiber_group(root, scene, ids)


def _group_batch_commits(rows):
    groups = {}
    for root, scene, fiber_id in rows:
        key = (_id_uid(scene), _id_uid(root))
        groups.setdefault(key, [root, scene, set()])[2].add(fiber_id)
    return tuple(groups.values())


def _abort_request(key, root, scene, fiber, session):
    job = _JOBS.get(key)
    if job is not None:
        _terminate_job(job, FiberTermination.CANCELLED, mark_unknown=False, stale=False)
    _restore_fiber_output(root, scene, fiber, stale=_request_failure_stale(session))
    rollback_engine_migration(fiber)
    _record_request_failure(fiber, session)


def _request_failure_stale(session):
    reason = str(getattr(session, "termination_reason", "") or "")
    return reason == FiberTermination.INVALID_ATTACHMENT.value


def _record_request_failure(fiber, session):
    reason = str(getattr(session, "termination_reason", "") or FiberTermination.INVALID_CONFIGURATION.value)
    set_fiber_invalid_reason(fiber, str(getattr(session, "invalid_reason", "") or reason))
    set_fiber_recompute_status(fiber, reason)
    set_fiber_not_converged(fiber, True)


def _supersede_job(key):
    job = _JOBS.get(key)
    if job is None:
        return None
    _mark_terminated(job, FiberTermination.SUPERSEDED)
    _detach_job(job)
    _group_member_done(_job_group_token(job), job.fiber_id, False, FiberTermination.SUPERSEDED.value)
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
        rollback_engine_migration(fiber, job.token)
    _restore_job_status(job, fiber, mark_unknown)
    _mark_terminated(job, reason)
    _detach_job(job)
    _group_member_done(_job_group_token(job), job.fiber_id, False, FiberTermination(reason).value)


def _restore_job_status(job, fiber, mark_unknown):
    if fiber is None:
        return
    status = "UNKNOWN" if mark_unknown else job.previous_status
    set_fiber_recompute_status(fiber, status)


def _mark_terminated(job, reason):
    cancel = getattr(job.session, "cancel", None)
    if callable(cancel): cancel()
    job.session.termination_reason = FiberTermination(reason).value
    job.session.converged = False
    job.session.done = True


def _detach_job(job):
    if _JOBS.get(job.key) is not job:
        return
    _JOBS.pop(job.key, None)
    _V3_BATCH.remove(job.key)
    while job.key in _QUEUE:
        _QUEUE.remove(job.key)


def _register_batch_job(job):
    if _batch_candidate(job): _V3_BATCH.add(job.key, job.session, _job_priority(job))


def _refresh_batch_priorities():
    global _LAST_BATCH_PRIORITY_REFRESH
    now = monotonic()
    if now - _LAST_BATCH_PRIORITY_REFRESH < _DRAW_INTERVAL: return
    _LAST_BATCH_PRIORITY_REFRESH = now
    for key in tuple(_V3_BATCH.entries):
        job = _JOBS.get(key)
        if job is not None: _V3_BATCH.set_priority(key, _job_priority(job))


def _is_v3_job(job):
    return job is not None and str(getattr(job.session, "engine", "")) == "V3"


def _batch_job_enabled(job):
    if not _batch_candidate(job): return False
    mode = os.environ.get("AF_FIBER_V3_BATCH", "AUTO").upper()
    count = int(getattr(job.session, "params", {}).get("node_count", 0))
    return mode == "1" or count >= 256 or len(_V3_BATCH.entries) >= 4


def _batch_candidate(job):
    return _is_v3_job(job) and os.environ.get("AF_FIBER_V3_BATCH", "AUTO") != "0"


def _job_priority(job):
    root, scene, fiber = _resolved_job_data(job)
    system = None if root is None else getattr(root, "af_vcp_system", None)
    selected = system is not None and system.active_vcp_type == "FIBER"
    if selected and system.active_vcp_id == job.fiber_id: return 8
    proxy = None if scene is None or root is None else _find_proxy(scene, root.name, job.fiber_id)
    return 4 if _proxy_visible(proxy) else 1


def _proxy_visible(proxy):
    if proxy is None: return False
    hidden = getattr(proxy, "hide_get", None)
    return not bool(hidden()) if callable(hidden) else not bool(getattr(proxy, "hide_viewport", False))


def fiber_refinement_batch_stats():
    stats = _V3_BATCH.stats()
    report = _LAST_V3_BATCH_REPORT
    stats["last"] = None if report is None else dict(report.__dict__)
    return stats


def _commit_provenance(job, result, fiber, proxy):
    selection = getattr(job.session, "selection", None)
    if selection is None:
        return
    commit_engine_migration(fiber, selection, job.token)
    write_engine_provenance(proxy, selection, result.engine_version,
                            getattr(result, "backend_version", ""))


def _valid_job(job, force_geometry=False):
    return _invalid_job_reason(job, force_geometry) is None


def _invalid_job_reason(job, force_geometry=False):
    root, scene, fiber = _owned_job_data(job)
    if root is None or scene is None or fiber is None:
        return FiberTermination.CANCELLED
    if int(fiber.get("af_fiber_request_token", 0)) != job.token:
        return FiberTermination.SUPERSEDED
    if _fiber_signature(fiber) != job.signature:
        return FiberTermination.CANCELLED
    if not _job_geometry_current(job, force_geometry):
        return FiberTermination.CANCELLED
    return None


def _job_geometry_current(job, force=False):
    now = monotonic()
    if not force and now - job.last_geometry_check < _DRAW_INTERVAL: return True
    job.last_geometry_check = now
    return _current_geometry_signature(job.session) == job.geometry_signature


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
    from ..vcp.shared_point_storage import endpoint_record
    fields = ("a_parent_id", "a_attach_param", "b_parent_id", "b_attach_param", "node_count",
              "iterations_bake", "use_surface_routing", "use_segment_collisions",
              "bend_stiffness", "stretch_stiffness", "topology_mode", "solver_version",
              "collision_radius", "symmetry_mode", "symmetry_axis", "use_warm_start",
              "preview_planner_route")
    values = tuple(_signature_value(getattr(fiber, name, None)) for name in fields)
    values += (tuple(float(value) for value in fiber.symmetry_origin), tuple(endpoint_record(fiber, s).normal_offset for s in ("a", "b")))
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
        from .sync_runner import schedule_sync_from_dirty_hints
    except ImportError:
        from core.visualization.sync_runner import schedule_sync_from_dirty_hints
    return schedule_sync_from_dirty_hints


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
    from ..vcp.v3.native_controller import shutdown_native_async_controllers
    shutdown_native_async_controllers()
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
