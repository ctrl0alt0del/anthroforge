"""Atomic Fiber engine migration snapshots and provenance."""

import json

from ..vcp.fiber_engine_selection import FiberEngineKind
from ..vcp.prop_update_guard import suppress_vcp_prop_updates
from ..vcp.runtime_state import (fiber_active_colliders, fiber_eps_disp, fiber_eps_pen,
                                 fiber_invalid_reason, fiber_not_converged, fiber_planner_ms,
                                 fiber_recompute_ms, fiber_recompute_status, fiber_refine_ms,
                                 fiber_route_mode)
from .fiber_sync_helpers import persisted_fiber_points
from ..vcp.free_path import is_free


_PENDING_KEYS = ("af_pending_solver_version", "af_pending_solver_token",
                 "af_pending_solver_previous_version", "af_pending_solver_points_json",
                 "af_pending_solver_diagnostics_json")


def prepare_engine_migration(root, scene, fiber, selection):
    if is_free(fiber): return False
    if not selection.valid:
        return False
    target, current = _engine_number(selection.actual), _stored_version(fiber)
    if target == current or _pending_version(fiber):
        return False
    _save_legacy_once(root, scene, fiber, current, target)
    _save_pending(root, scene, fiber, current, target)
    return True


def claim_engine_migration(fiber, token):
    if _pending_version(fiber):
        fiber["af_pending_solver_token"] = int(token)


def migration_owned(fiber, token):
    return bool(_pending_version(fiber) and
                int(fiber.get("af_pending_solver_token", 0) or 0) == int(token))


def commit_engine_migration(fiber, selection, token=0):
    if is_free(fiber): return False
    if token and _pending_version(fiber) and not migration_owned(fiber, token):
        return False
    _set_version(fiber, _engine_number(selection.actual))
    clear_engine_migration(fiber)
    return True


def rollback_engine_migration(fiber, token=0):
    if is_free(fiber): return False
    if token and not migration_owned(fiber, token):
        return False
    previous = int(fiber.get("af_pending_solver_previous_version", 0) or 0)
    if previous:
        _set_version(fiber, previous)
    clear_engine_migration(fiber)
    return bool(previous)


def pending_engine_points(fiber):
    return _decoded_points(fiber.get("af_pending_solver_points_json", ""))


def clear_engine_migration(fiber):
    for key in _PENDING_KEYS:
        try:
            del fiber[key]
        except Exception:
            pass


def write_engine_provenance(proxy, selection, engine_version, backend_version=""):
    if proxy is None or not selection.valid:
        return
    proxy["af_fiber_output_engine"] = selection.actual.value
    proxy["af_fiber_output_engine_version"] = str(engine_version or "")
    proxy["af_fiber_output_backend_version"] = str(backend_version or "")
    proxy["af_fiber_requested_engine"] = selection.requested.value
    proxy["af_fiber_engine_selection_source"] = selection.source
    proxy["af_fiber_engine_fallback_reason"] = selection.fallback_reason


def _save_pending(root, scene, fiber, current, target):
    points = persisted_fiber_points(scene, root.name, fiber.id) or ()
    fiber["af_pending_solver_previous_version"] = int(current)
    fiber["af_pending_solver_version"] = int(target)
    fiber["af_pending_solver_points_json"] = _encoded_points(points)
    fiber["af_pending_solver_diagnostics_json"] = json.dumps(_diagnostics(fiber))


def _save_legacy_once(root, scene, fiber, current, target):
    if current != 1 or target not in (2, 3) or str(getattr(fiber, "legacy_points_json", "") or ""):
        return
    points = persisted_fiber_points(scene, root.name, fiber.id) or ()
    fiber.legacy_points_json = _encoded_points(points)
    fiber.legacy_diagnostics_json = json.dumps(_diagnostics(fiber))
    fiber.legacy_status = fiber_recompute_status(fiber)
    fiber.legacy_eps_disp, fiber.legacy_eps_pen = fiber_eps_disp(fiber), fiber_eps_pen(fiber)


def _diagnostics(fiber):
    return {"status": fiber_recompute_status(fiber), "eps_disp": fiber_eps_disp(fiber),
            "eps_pen": fiber_eps_pen(fiber), "route": fiber_route_mode(fiber),
            "planner_ms": fiber_planner_ms(fiber), "refine_ms": fiber_refine_ms(fiber),
            "recompute_ms": fiber_recompute_ms(fiber), "active": fiber_active_colliders(fiber),
            "invalid": fiber_invalid_reason(fiber), "not_converged": fiber_not_converged(fiber)}


def _set_version(fiber, value):
    with suppress_vcp_prop_updates():
        fiber.solver_version = int(value)


def _engine_number(engine):
    return {FiberEngineKind.V1: 1, FiberEngineKind.V2: 2, FiberEngineKind.V3: 3}[engine]


def _stored_version(fiber):
    return max(1, int(getattr(fiber, "solver_version", 1) or 1))


def _pending_version(fiber):
    return int(fiber.get("af_pending_solver_version", 0) or 0)


def _encoded_points(points):
    return json.dumps([[float(value) for value in point[:3]] for point in points])


def _decoded_points(raw):
    try:
        return tuple(tuple(float(value) for value in row[:3]) for row in json.loads(str(raw or "")))
    except Exception:
        return ()
