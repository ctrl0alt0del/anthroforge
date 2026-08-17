"""V2.1 hybrid planner-reuse and linear-first CCD experiment."""

from collections import OrderedDict
from dataclasses import dataclass, replace
from time import perf_counter

import numpy as np

from . import solver as p5
from . import solver_p6 as p6
from . import solver_p61 as p61
from .collision import (build_triangle_snapshot, cached_native_collision_world,
                        validate_static_clearance)
from .contracts import V2Diagnostics, V2Termination, V2Topology
from .planner import V2PlannerDiagnostics, _anchor_contact, plan_reference_v43


V2_SOLVER_V21_VERSION = "fiber-v2.1-solver-1"
_ROUTE_CACHE_LIMIT = 128
_ROUTE_CACHE = OrderedDict()


@dataclass(frozen=True)
class _RouteRecord:
    signature: str
    anchors: tuple
    planner: object


@dataclass(frozen=True)
class V21Trace(p61.V2Package61Trace):
    planner_reused: bool = False
    exact_route_hit: bool = False
    reuse_validation_ms: float = 0.0
    planner_full_runs: int = 0
    direct_probes: int = 0
    direct_full_steps: int = 0
    curved_recoveries: int = 0


def clear_v21_route_cache():
    _ROUTE_CACHE.clear()


def v21_route_cache_stats():
    return {"entries": len(_ROUTE_CACHE), "limit": _ROUTE_CACHE_LIMIT}


def solve_v21(request, snapshot=None, contact_weight=p5.DEFAULT_CONTACT_WEIGHT):
    started = perf_counter(); triangle = snapshot or build_triangle_snapshot(request.colliders)
    planner, route_trace = _planner(request, triangle)
    if not planner.succeeded:
        return _failed(request, planner, started, contact_weight, route_trace)
    state = _state(request, planner, triangle, contact_weight, route_trace)
    termination, message = _solve_state(state)
    return _finish(state, termination, message, started)


def _planner(request, snapshot):
    key = _lineage_key(request); record = _cache_get(key)
    if record and record.signature == request.signature():
        return _exact_reuse(record.planner), (True, True, 0.0, 0)
    reused, elapsed = _try_reuse(request, snapshot, record)
    if reused is not None:
        _cache_put(key, request, reused); return reused, (True, False, elapsed, 0)
    planner, full_runs = _full_plan(request, snapshot)
    if planner.succeeded:
        _cache_put(key, request, planner)
    return planner, (False, False, elapsed, full_runs)


def _full_plan(request, snapshot):
    if _wide_direct(request):
        return plan_reference_v43(request, snapshot, owner_contact_factor=8.0), 1
    first = plan_reference_v43(request, snapshot)
    if not first.succeeded or first.mode.value != "ROADMAP":
        return first, 1
    second = plan_reference_v43(request, snapshot, owner_contact_factor=8.0)
    return replace(second, diagnostics=p5._merged_planner_diagnostics(first, second)), 2


def _wide_direct(request):
    if not request.colliders:
        return True
    points = np.asarray([anchor.point for anchor in request.anchors], dtype=np.float64)
    edges = _anchor_edges(len(points), request.settings.topology is V2Topology.CYCLIC)
    owners = tuple((request.anchors[a].owner_id, request.anchors[b].owner_id) for a, b in edges)
    span = max(8.0 * request.collision_policy.collision_radius, 1.0e-7)
    clearance = request.collision_policy.collision_radius - request.tolerances.clearance_slack
    return all(cached_native_collision_world(request.colliders).validate(points, edges, owners, span, clearance).clear)


def _anchor_edges(count, cyclic):
    limit = count if cyclic else max(0, count - 1)
    return tuple((index, (index + 1) % count) for index in range(limit))


def _lineage_key(request):
    anchors = tuple((a.owner_id, a.role.value, a.authored_index) for a in request.anchors)
    colliders = tuple((c.collider_id, c.owner_id, c.generation, len(c.vertices), len(c.triangles)) for c in request.colliders)
    settings = (request.settings.topology.value, request.settings.quality.value, request.settings.node_count)
    symmetry = (request.symmetry_mode, request.symmetry_axis, request.symmetry_origin)
    return request.scene_id, request.root_id, request.source_revision, settings, anchors, colliders, symmetry, request.collision_policy


def _cache_get(key):
    record = _ROUTE_CACHE.get(key)
    if record is not None:
        _ROUTE_CACHE.move_to_end(key)
    return record


def _cache_put(key, request, planner):
    anchors = tuple(tuple(anchor.point) for anchor in request.anchors)
    _ROUTE_CACHE[key] = _RouteRecord(request.signature(), anchors, planner)
    _ROUTE_CACHE.move_to_end(key)
    while len(_ROUTE_CACHE) > _ROUTE_CACHE_LIMIT:
        _ROUTE_CACHE.popitem(last=False)


def _exact_reuse(planner):
    diagnostics = replace(planner.diagnostics, planner_ms=0.0, handoff_ms=0.0)
    return replace(planner, diagnostics=diagnostics, message="exact validated corridor cache hit")


def _try_reuse(request, snapshot, record):
    if record is None or request.settings.topology is V2Topology.CYCLIC:
        return None, 0.0
    if len(record.anchors) != len(request.anchors) or not _surface_reuse_allowed(request, record):
        return None, 0.0
    started = perf_counter(); planner = _warped_planner(request, snapshot, record)
    return planner, p5._elapsed(started)


def _surface_reuse_allowed(request, record):
    if record.planner.mode.value != "SURFACE":
        return True
    current = tuple(tuple(anchor.point) for anchor in request.anchors)
    return current == record.anchors


def _warped_planner(request, snapshot, record):
    points = _warp_reference(record.planner, record.anchors, request.anchors)
    if points is None:
        return None
    contacts = _contacts(request, points, record.planner.pin_indices)
    checked = _reuse_validation(request, snapshot, points, contacts)
    return _reuse_result(record.planner, points, contacts, checked) if checked.valid else None


def _warp_reference(planner, old_anchors, new_anchors):
    points = np.asarray(planner.reference, dtype=np.float64).copy(); pins = planner.pin_indices
    if len(points) < 2 or len(pins) != len(new_anchors):
        return None
    deltas = np.asarray([new.point for new in new_anchors]) - np.asarray(old_anchors)
    for index in range(len(pins) - 1):
        _warp_span(points, pins[index], pins[index + 1], deltas[index], deltas[index + 1])
    for index, anchor in zip(pins, new_anchors):
        points[int(index)] = anchor.point
    return points


def _warp_span(points, first, second, low, high):
    count = max(1, int(second) - int(first))
    for index in range(int(first), int(second) + 1):
        factor = (index - int(first)) / count
        points[index] += (1.0 - factor) * low + factor * high


def _contacts(request, points, pins):
    span = max(8.0 * request.collision_policy.collision_radius, 1.0e-7)
    return tuple(_anchor_contact(points, int(index), anchor.owner_id, span, False)
                 for index, anchor in zip(pins, request.anchors) if anchor.owner_id)


def _reuse_validation(request, snapshot, points, contacts):
    policy, tolerance = request.collision_policy, request.tolerances
    return validate_static_clearance(points, snapshot, policy.collision_radius, contacts,
                                     cyclic=False, slack=tolerance.clearance_slack)


def _reuse_result(planner, points, contacts, checked):
    diagnostics = V2PlannerDiagnostics(candidate_pairs=checked.candidate_pairs,
                                       tested_pairs=checked.tested_pairs)
    values = tuple(tuple(float(value) for value in row) for row in points)
    return replace(planner, reference=values, corridor=values, contacts=contacts,
                   diagnostics=diagnostics, message="validated warped corridor reuse")


def _state(request, planner, snapshot, contact_weight, route_trace, native_world=None):
    state = p6._state(request, p5._solver_planner(request, planner), snapshot, contact_weight)
    state.native_world = native_world
    p5._prepare_contacts(state); first = p5._candidate(state); p61._initialize_dispatch(state)
    state.workload = p61._dispatch_probe(state, first); state.v21_first = first
    state.v21_route_trace = route_trace; state.direct_probes = 0
    state.direct_full_steps = 0; state.curved_recoveries = 0; return state


def _solve_state(state):
    if state.certificates_enabled:
        return p61._iterate_dynamic(state, state.dispatch_candidate)
    return _iterate_light(state, state.v21_first)


def _iterate_light(state, first):
    for trial in range(state.request.settings.max_accepted_steps):
        state.trials += 1; candidate = first if trial == 0 else p5._candidate(state)
        changed = state.contact_changed; accepted, full = _accept_light(state, candidate)
        if accepted and full and not changed and p5._step_converged(state):
            return V2Termination.CONVERGED, "V2.1 light fixed point"
        if not accepted and not changed:
            return V2Termination.BLOCKED, "V2.1 light path is blocked"
    return V2Termination.BUDGET_EXHAUSTED, "accepted-step cap exhausted"


def _accept_light(state, candidate):
    if state.planner.mode.value == "SURFACE" or not state.active:
        return p5._accept_candidate(state, candidate)
    if len(state.active) > 4:
        return p5._accept_candidate(state, candidate)
    direct, envelope = _direct_probe(state, candidate)
    if direct is not None:
        return direct
    state.curved_recoveries += 1
    return p5._accept_waypoints(state, p5._curved_waypoints(state, candidate), envelope)


def _direct_probe(state, candidate):
    envelope = p5._waypoint_envelope(state.points, (candidate,)); started = perf_counter()
    step = p5._safe_step_p51(state, state.points, candidate, envelope)
    state.ccd_ms += p5._elapsed(started); p5._absorb_ccd(state, step); state.direct_probes += 1
    proposed, full = p5._ccd_proposal(state.points, candidate, step)
    if proposed is None or not full:
        return None, envelope
    state.direct_full_steps += 1
    return p5._accept_unvalidated(state, proposed, True), envelope


def _finish(state, termination, message, started):
    checked = p5._timed_validation(state, state.points); diagnostics = p5._diagnostics(state, checked)
    validated = bool(checked.valid and np.isfinite(state.points).all())
    if not validated:
        termination, message = V2Termination.UNSAFE_OUTPUT, "final independent validation failed"
    result = p5._result(state.request, state.planner, state.points, diagnostics,
                        termination, validated, message, V2_SOLVER_V21_VERSION)
    return p5.V2Package5Result(result, state.planner, _trace(state, started))


def _trace(state, started):
    base = p61._trace(state, started); reused, exact, validation, full = state.v21_route_trace
    return V21Trace(**vars(base), planner_reused=reused, exact_route_hit=exact,
                    reuse_validation_ms=validation, planner_full_runs=full,
                    direct_probes=state.direct_probes, direct_full_steps=state.direct_full_steps,
                    curved_recoveries=state.curved_recoveries)


def _failed(request, planner, started, contact_weight, route_trace):
    result = p5._result(request, planner, (), V2Diagnostics(), planner.termination, False,
                        planner.message, V2_SOLVER_V21_VERSION)
    reused, exact, validation, full = route_trace
    trace = V21Trace(total_ms=p5._elapsed(started), contact_weight=float(contact_weight),
                     planner_reused=reused, exact_route_hit=exact,
                     reuse_validation_ms=validation, planner_full_runs=full)
    return p5.V2Package5Result(result, planner, trace)
