from dataclasses import dataclass
from time import monotonic

import bpy
from bpy.app.handlers import persistent

from ..deps.dirty_hints import dirty_hints_for
from ..vcp.fiber_collision import _collider_stamp
from ..vcp.fiber_progressive import begin_fiber_solve
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


_SLICE_MS = 12.0
_TIMER_INTERVAL = 0.01
_DRAW_INTERVAL = 0.05
_JOBS = {}
_QUEUE = []
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
    fiber_id: str
    signature: tuple
    geometry_signature: tuple
    session: object
    proxy_name: str = ""
    last_apply: float = 0.0
    last_generation: int = -1


def request_fiber_refinement(root, scene, fiber, show_preview=False):
    if root is None or scene is None or fiber is None:
        return RefinementRequest(False, "Fiber refinement context is unavailable.")
    key = _job_key(scene, root, fiber.id)
    _drop_job(key, mark_unknown=False)
    session = begin_fiber_solve(register_fiber_sync()._solver, root, fiber, scene, _depsgraph(scene))
    if session.invalid_reason:
        return RefinementRequest(False, session.invalid_reason)
    job = _new_job(key, scene, root, fiber, session)
    proxy = _initial_proxy(job, show_preview)
    return _start_or_finish(job, proxy)


def cancel_fiber_refinement(scene, fiber_id, mark_unknown=True):
    keys = [key for key in tuple(_JOBS) if key[0] == _scene_name(scene) and key[2] == str(fiber_id)]
    for key in keys:
        _drop_job(key, mark_unknown=mark_unknown)
    return bool(keys)


def fiber_refinement_state(scene, fiber_id):
    key = next((key for key in _JOBS if key[0] == _scene_name(scene) and key[2] == str(fiber_id)), None)
    if key is not None:
        return "REFINING"
    fiber = _fiber_for_scene(scene, fiber_id)
    return "UNKNOWN" if fiber is None else fiber_recompute_status(fiber)


def shutdown_fiber_refinements(mark_unknown=False):
    global _TIMER_ARMED
    for key in tuple(_JOBS):
        _drop_job(key, mark_unknown=mark_unknown)
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
    job = FiberRefinementJob(key, scene.name, root.name, fiber.id, _fiber_signature(fiber),
                             _geometry_signature(session), session)
    job.last_apply, job.last_generation = monotonic(), session.generation
    return job


def _initial_proxy(job, show_preview):
    root, scene, fiber = _resolved_job_data(job)
    proxy = _find_proxy(scene, root.name, fiber.id)
    if show_preview or proxy is None:
        proxy = register_fiber_sync().apply_points(root, scene, fiber, job.session.preview, bake=False)
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
    key = _QUEUE.pop(0)
    job = _JOBS.get(key)
    if job is not None:
        _advance_job(job)
    if key in _JOBS:
        _QUEUE.append(key)
    _TIMER_ARMED = bool(_QUEUE)
    return _TIMER_INTERVAL if _QUEUE else None


def _advance_job(job):
    if not _valid_job(job):
        _drop_job(job.key, mark_unknown=True)
        return
    result = job.session.step(_SLICE_MS)
    _apply_progress(job, result)
    if result.done:
        _finish_job(job, result)


def _apply_progress(job, result):
    now = monotonic()
    changed_level = job.last_generation != job.session.generation
    if not (result.done or changed_level or now - job.last_apply >= _DRAW_INTERVAL):
        return
    root, scene, fiber = _resolved_job_data(job)
    proxy = register_fiber_sync().apply_points(root, scene, fiber, result.points, bake=result.done)
    job.proxy_name = "" if proxy is None else proxy.name
    job.last_apply, job.last_generation = now, job.session.generation


def _finish_job(job, result=None):
    result = result or job.session.result()
    _store_result(job.session.fiber, result)
    _drop_job(job.key, mark_unknown=False)
    _sync_final(job)


def _store_result(fiber, result):
    set_fiber_not_converged(fiber, not result.converged)
    set_fiber_recompute_status(fiber, "CONVERGED" if result.converged else "NOT_CONVERGED")
    set_fiber_recompute_ms(fiber, result.planner_ms + result.refine_ms)
    set_fiber_eps_disp(fiber, result.max_disp)
    set_fiber_eps_pen(fiber, result.max_pen)
    set_fiber_route_mode(fiber, result.mode)
    set_fiber_planner_ms(fiber, result.planner_ms)
    set_fiber_refine_ms(fiber, result.refine_ms)
    set_fiber_active_colliders(fiber, result.active_count)
    set_fiber_invalid_reason(fiber, result.invalid_reason)


def _sync_final(job):
    root, scene, fiber = _resolved_job_data(job)
    if root is None or scene is None or fiber is None:
        return
    payload = {"solved_fiber_ids": [fiber.id]}
    _sync_scene()(root=root, scene=scene, dirty_hints=dirty_hints_for("FIBER", {fiber.id}),
                  source="fiber_refinement", event_type="FIBER_SOLVE_READY", payload=payload)


def _drop_job(key, mark_unknown=False):
    job = _JOBS.pop(key, None)
    while key in _QUEUE:
        _QUEUE.remove(key)
    if job is not None and mark_unknown:
        fiber = _resolved_job_data(job)[2]
        None if fiber is None else set_fiber_recompute_status(fiber, "UNKNOWN")


def _valid_job(job):
    root, scene, fiber = _resolved_job_data(job)
    if root is None or scene is None or fiber is None:
        return False
    if _fiber_signature(fiber) != job.signature:
        return False
    return _current_geometry_signature(job.session) == job.geometry_signature


def _resolved_job_data(job):
    scene = bpy.data.scenes.get(job.scene_name)
    root = None if scene is None else scene.objects.get(job.root_name)
    fibers = () if root is None else root.af_vcp_system.fibers
    fiber = next((item for item in fibers if item.id == job.fiber_id), None)
    return root, scene, fiber


def _fiber_signature(fiber):
    fields = ("a_parent_id", "a_attach_param", "b_parent_id", "b_attach_param", "node_count",
              "iterations_bake", "use_surface_routing", "use_segment_collisions",
              "bend_stiffness", "stretch_stiffness", "topology_mode")
    values = tuple(getattr(fiber, name, None) for name in fields)
    touches = tuple((item.parent_id, item.attach_param, float(item.normal_offset)) for item in fiber.mid_touches)
    anchors = tuple((item.parent_id, item.attach_param) for item in fiber.loop_anchors)
    return values, touches, anchors


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
        if job.scene_name == _scene_name(scene) and _job_geometry_updated(job, depsgraph):
            _drop_job(job.key, mark_unknown=True)


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


def _mark_refining(fiber):
    set_fiber_not_converged(fiber, False)
    set_fiber_recompute_status(fiber, "REFINING")
    set_fiber_invalid_reason(fiber, "")
    try:
        fiber["af_prefer_bake"] = False
    except Exception:
        pass


def _job_key(scene, root, fiber_id):
    return _scene_name(scene), str(root.name), str(fiber_id)


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
    _PAUSED = [(job.scene_name, job.root_name, job.fiber_id) for job in _JOBS.values()]
    shutdown_fiber_refinements(mark_unknown=False)


@persistent
def _on_history_post(_dummy):
    if _PAUSED and not bpy.app.timers.is_registered(_resume_paused):
        bpy.app.timers.register(_resume_paused, first_interval=0.0)


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
