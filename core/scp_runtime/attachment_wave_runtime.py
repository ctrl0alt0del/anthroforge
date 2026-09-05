"""Production capture, native execution, validation, and commit for attachments."""

from dataclasses import dataclass
from time import perf_counter

from mathutils import Matrix, Vector
import numpy as np

from ..deps.runtime_trace import trace_line
from ..shortcuts.session_state import suppress_next_depsgraph_ids
from ..utils import update_scene_view_layer
from ..vcp.attachment_wave import AttachmentExecutorKind
from ..vcp.attachment_wave_native import (attachment_executor_stats, attachment_wave_status,
                                          execute_attachment_wave)
from ..vcp.runtime_state import (fiber_recompute_status, set_fiber_invalid_reason,
                                 set_fiber_recompute_status)
from ..visualization.fiber_sync import register_fiber_sync
from .attachment_wave_capture import (attachment_request_current, attachment_surface_cache_stats,
                                      capture_attachment_wave, plan_attachment_waves)
from .common import is_matrix_close, mark_applied_matrix, matrix_flat16


_LAST_REPORTS = {}


@dataclass(frozen=True)
class AttachmentWaveRuntimeReport:
    changed_scps: tuple = ()
    failed_scps: tuple = ()
    handled_fibers: tuple = ()
    failed_fibers: tuple = ()
    capture_ms: float = 0.0
    native_ms: float = 0.0
    commit_ms: float = 0.0
    fallback_reason: str = ""
    telemetry: tuple = ()


class _StaleAttachmentWave(RuntimeError):
    pass


def apply_attachment_wave(sync, root, scene, scps, targets, parents, fibers=(), blocked=(), backsolve=None, executor=None):
    kind = executor or AttachmentExecutorKind.NATIVE_WAVE
    if kind == AttachmentExecutorKind.NATIVE_WAVE and not attachment_wave_status():
        return _serial_fallback(sync, root, scene, scps, targets, parents, fibers,
                                blocked, backsolve, 0.0, "NATIVE_ATTACHMENT_UNAVAILABLE")
    return _staged_wave(sync, root, scene, scps, targets, parents, fibers,
                        blocked, backsolve, kind)


def _staged_wave(sync, root, scene, scps, targets, parents, fibers, blocked, backsolve, kind):
    started = perf_counter()
    waves, issues = plan_attachment_waves(scps, targets, parents, blocked)
    state = _wave_state(blocked, issues)
    state["graph"] = _elapsed(started)
    try:
        for wave in waves: _advance_scp_wave(root, scene, scps, wave, backsolve, kind, state)
        _advance_fiber_phase(root, scene, scps, fibers, kind, state)
    except _StaleAttachmentWave:
        return _record(root, _state_report(state, "STALE_CAPTURE"))
    except (AttributeError, OSError, RuntimeError, ValueError) as error:
        return _serial_fallback(sync, root, scene, scps, targets, parents, fibers,
                                blocked, backsolve, state["capture"], f"NATIVE_ERROR:{error}")
    return _record(root, _state_report(state))


def _wave_state(blocked, issues):
    failed = {str(row[0]) for row in issues}
    return {"blocked": set(blocked or ()), "failed_scps": failed, "changed": set(),
            "handled": set(), "failed": set(), "capture": 0.0, "native": 0.0,
            "commit": 0.0, "graph": 0.0, "telemetry": []}


def _advance_scp_wave(root, scene, scps, wave, backsolve, kind, state):
    active = tuple(sid for sid in wave if sid not in state["blocked"])
    if not active: return
    outcome, result = _run_native_phase(root, scene, scps, active, (), (), backsolve,
                                        kind, state, active)
    started = perf_counter(); changed = _commit_scps(root, scene, outcome, result)
    state["commit"] += _elapsed(started); state["changed"] |= set(changed)
    _record_scp_failures(scps, outcome, result, state)
    if changed: suppress_next_depsgraph_ids(changed)


def _advance_fiber_phase(root, scene, scps, fibers, kind, state):
    if not fibers: return
    outcome, result = _run_native_phase(root, scene, scps, (), (), fibers, None,
                                        kind, state, None)
    handled, failed, write_ms, refresh_ms = _commit_fibers(root, scene, outcome, result)
    state["commit"] += write_ms + refresh_ms; state["handled"] |= handled; state["failed"] |= failed
    state["telemetry"].append((("phase", "FIBER_COMMIT"), ("write_ms", write_ms),
                               ("refresh_ms", refresh_ms)))


def _run_native_phase(root, scene, scps, targets, parents, fibers, backsolve, kind, state, limit):
    started = perf_counter(); outcome = capture_attachment_wave(root, scene, scps, targets,
        parents, fibers, state["blocked"], backsolve, limit, state["failed_scps"])
    state["capture"] += _elapsed(started); started = perf_counter()
    result = execute_attachment_wave(outcome.request, kind); state["native"] += _elapsed(started)
    if not attachment_request_current(outcome.request, root, scene): raise _StaleAttachmentWave()
    state["telemetry"].append(tuple(attachment_executor_stats(outcome.request, result).items()))
    return outcome, result


def _record_scp_failures(scps, outcome, result, state):
    failed = {str(row[0]) for row in outcome.scp_issues}
    failed |= {op.child_id for op in outcome.request.scp_operations
               if result.scp_status[op.child_index]}
    state["failed_scps"] |= failed
    state["blocked"] |= _failure_descendants(scps, failed)


def _failure_descendants(scps, failed):
    from .tree import children_map
    kids, values, stack = children_map(scps), set(failed), list(failed)
    while stack:
        for child in kids.get(stack.pop(), ()):
            if child not in values: values.add(child); stack.append(child)
    return values


def _state_report(state, reason=""):
    cache = tuple(attachment_surface_cache_stats().items())
    telemetry = (("graph_ms", state["graph"]), ("phases", tuple(state["telemetry"])),
                 ("surface_cache", cache))
    return AttachmentWaveRuntimeReport(tuple(sorted(state["changed"])),
        tuple(sorted(state["failed_scps"])), tuple(sorted(state["handled"])),
        tuple(sorted(state["failed"])), state["capture"], state["native"],
        state["commit"], reason, telemetry)


def last_attachment_wave_report(root=None):
    return _LAST_REPORTS.get(_runtime_id(root)) if root is not None else dict(_LAST_REPORTS)


def clear_attachment_wave_reports():
    _LAST_REPORTS.clear()


def _commit_scps(root, scene, outcome, result):
    from .common import indexed_geometry_mesh_scp_obj, indexed_transform_scp_obj, scp_object_maps
    changed = set(); request = outcome.request
    objects = scp_object_maps(scene, root.name)
    for operation in request.scp_operations:
        index = operation.child_index
        if result.scp_status[index] or not _finite(result.matrices[index]): continue
        obj = indexed_transform_scp_obj(objects, operation.child_id) or indexed_geometry_mesh_scp_obj(objects, operation.child_id)
        if obj is None: continue
        matrix = Matrix(result.matrices[index].reshape((4, 4)).tolist())
        if is_matrix_close(matrix_flat16(obj.matrix_world), matrix_flat16(matrix), eps=1.0e-7): continue
        obj.matrix_world = matrix; mark_applied_matrix(obj); changed.add(operation.child_id)
    return changed


def _commit_fibers(root, scene, outcome, result):
    sync = register_fiber_sync(); by_id = {str(row.id): row for row in root.af_vcp_system.fibers}
    handled = set(str(row.id) for row in _requested_fibers(root, outcome)); failed = set()
    started = perf_counter(); _write_fibers(sync, root, scene, by_id, outcome, result, failed)
    write_ms = _elapsed(started); started = perf_counter()
    if handled: _refresh_fiber_handles(sync, root, scene, outcome, result, handled, failed)
    return handled, failed, write_ms, _elapsed(started)


def _refresh_fiber_handles(sync, root, scene, outcome, result, handled, failed):
    refresh = getattr(sync, "refresh_propagated_handles", None)
    points = _successful_point_map(outcome, result, failed)
    if refresh is not None and refresh(root, scene, points, handled): return
    sync.refresh_selection(root=root, scene=scene, fiber_ids=handled, sync_handles=True)


def _successful_point_map(outcome, result, failed):
    values = {}
    for index, fiber_id in enumerate(outcome.request.fiber_ids):
        if fiber_id not in failed: values[fiber_id] = result.fiber_points[index]
    return values


def _write_fibers(sync, root, scene, by_id, outcome, result, failed):
    sync.begin_point_batch()
    try:
        for index, fiber_id in enumerate(outcome.request.fiber_ids):
            if not _commit_one_fiber(sync, root, scene, by_id.get(fiber_id), result, index): failed.add(fiber_id)
        for fiber_id, error in outcome.fiber_issues: _fail_fiber(by_id.get(fiber_id), error); failed.add(fiber_id)
    finally: sync.end_point_batch()


def _requested_fibers(root, outcome):
    ids = set(outcome.request.fiber_ids) | {row[0] for row in outcome.fiber_issues}
    return tuple(row for row in root.af_vcp_system.fibers if str(row.id) in ids)


def _commit_one_fiber(sync, root, scene, fiber, result, index):
    if fiber is None: return False
    points = result.fiber_points[index]
    if result.fiber_status[index] or not _finite(points) or len(points) != int(fiber.node_count):
        _fail_fiber(fiber, "A Fiber node attachment no longer resolves."); return False
    proxy = sync.apply_points(root, scene, fiber, tuple(Vector(row) for row in points), commit=True)
    if proxy is None: _fail_fiber(fiber, "Fiber proxy is unavailable."); return False
    proxy.pop("af_fiber_display_mode", None); _succeed_fiber(fiber); return True


def _fail_fiber(fiber, error):
    if fiber is None: return
    set_fiber_invalid_reason(fiber, str(error or "Fiber node attachment failed."))
    set_fiber_recompute_status(fiber, "INVALID_ATTACHMENT")


def _succeed_fiber(fiber):
    set_fiber_invalid_reason(fiber, "")
    if fiber_recompute_status(fiber) == "INVALID_ATTACHMENT": set_fiber_recompute_status(fiber, "UNKNOWN")


def _serial_fallback(sync, root, scene, scps, targets, parents, fibers, blocked, backsolve, capture_ms, reason):
    from .attachment_runtime import _apply_attachment_targets
    from ..visualization.fiber_node_attachment_runtime import _apply_fiber_node_attachments_serial
    started = perf_counter(); changed = _apply_attachment_targets(root, scene, scps,
        set(targets), set(parents), set(blocked), dict(backsolve or {}))
    if changed: update_scene_view_layer(scene)
    ids = {str(row.id) for row in fibers}; handled = _apply_fiber_node_attachments_serial(root, scene, ids)
    report = AttachmentWaveRuntimeReport(changed_scps=tuple(sorted(changed)),
        handled_fibers=tuple(sorted(handled)), capture_ms=capture_ms,
        commit_ms=_elapsed(started), fallback_reason=reason)
    return _record(root, report)


def _record(root, report):
    _LAST_REPORTS[_runtime_id(root)] = report
    if _report_relevant(report):
        trace_line("attachment wave " + " ".join(f"{key}={value}" for key, value in _report_values(report).items()))
    return report


def _report_relevant(report):
    return bool(report.changed_scps or report.failed_scps or report.handled_fibers or report.failed_fibers
                or report.fallback_reason)


def _report_values(report):
    return {"capture_ms": round(report.capture_ms, 3), "native_ms": round(report.native_ms, 3),
            "commit_ms": round(report.commit_ms, 3), "scps": len(report.changed_scps),
            "failed_scps": len(report.failed_scps),
            "fibers": len(report.handled_fibers), "failed": len(report.failed_fibers),
            "fallback": report.fallback_reason or "NONE"}


def _runtime_id(value):
    try: return int(getattr(value, "session_uid", 0) or value.as_pointer())
    except Exception: return id(value)


def _finite(values):
    try: return bool(np.isfinite(np.asarray(values, dtype=np.float64)).all())
    except Exception: return False


def _elapsed(started):
    return 1000.0 * max(0.0, perf_counter() - started)
