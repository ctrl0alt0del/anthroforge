"""Planner-span-guided surface smoothing on the qualified V2.4 engine."""

from dataclasses import dataclass, replace
from time import perf_counter

import numpy as np

from . import solver as p5
from . import solver_v21 as v21
from . import solver_v22 as v22
from . import solver_v23 as v23
from . import solver_v24 as v24
from .contracts import V2Termination, V2Topology
from .planner import V2PlannerBranch


V2_SOLVER_V25_BRANCH2_VERSION = "fiber-v2.5-span-controller-3"
SPAN_CONTACT_WEIGHT = 1000.0
_SURFACE_BRANCHES = (V2PlannerBranch.SURFACE_BRIDGE,)


@dataclass(frozen=True)
class V25Branch2Trace(v24.V24Trace):
    branch2_active: bool = False
    branch2_spans: int = 0
    policy_ms: float = 0.0
    line_search_fractions: tuple = ()
    recovery_enabled: bool = False
    acquired_max_turn: float = 0.0
    acquired_p95_turn: float = 0.0


def solve_v25_branch2(request, snapshot=None, contact_weight=SPAN_CONTACT_WEIGHT,
                       preview=False):
    started = perf_counter(); signature, signature_ms = v22._timed_signature(request)
    try:
        world, world_ms = v24._world(request)
        triangle, hit, snapshot_ms = v24._snapshot(request, snapshot, world.closed_flags)
    except (OSError, RuntimeError, ValueError, AttributeError) as error:
        return _versioned(v24._unavailable(request, signature, started, contact_weight, error))
    return _solve(request, triangle, world, signature, signature_ms, hit,
                  snapshot_ms, world_ms, started, contact_weight, preview)


def _solve(request, triangle, world, signature, signature_ms, hit, snapshot_ms,
           world_ms, started, weight, preview):
    planner, route, policy = v23._planner(request, triangle, world, signature, bool(preview), v24._ROUTE_CACHE)
    if not planner.succeeded:
        failed = v24._failed(request, planner, started, weight, route, policy, signature,
                             signature_ms, hit, snapshot_ms, world_ms, world.closed_flags)
        return _versioned(failed)
    state = v24._state(request, planner, triangle, weight, route, world, signature,
                       signature_ms, hit, policy, snapshot_ms, world_ms)
    return _solve_state(state, started)


def _solve_state(state, started):
    if not _eligible(state):
        termination, message = v21._solve_state(state)
        return _versioned(v24._finish(state, termination, message, started), state)
    before = perf_counter(); _configure(state)
    state.v25_policy_ms = p5._elapsed(before)
    termination, message = _iterate_surface(state)
    return _finish(state, termination, message, started)


def _eligible(state):
    return bool(state.request.settings.topology is V2Topology.OPEN and
                any(span.branch in _SURFACE_BRANCHES for span in state.planner.spans))


def _configure(state):
    state.v25_spans = tuple(span for span in state.planner.spans
                            if span.branch in _SURFACE_BRANCHES)
    state.v25_surface_spans = tuple(span for span in state.planner.spans
                                    if span.branch in _surface_policy_branches())
    state.v25_owner_worlds = _owner_worlds(state)
    state.surface_candidate_policy = _surface_candidate
    state.v25_line_fractions = []
    state.v25_recovery = False; state.v25_turns = (0.0, 0.0)
    if _all_surface_bridges(state):
        state.structural_settings = _bridge_settings(state)
        state.proximal_weight = 0.01


def _owner_worlds(state):
    owners = {span.owner_id for span in state.v25_surface_spans if span.owner_id}
    return {owner: p5.cached_native_collision_world(p5._owner_colliders(state.request, owner))
            for owner in owners}


def _all_surface_bridges(state):
    spans = tuple(state.planner.spans)
    return bool(spans and all(span.branch is V2PlannerBranch.SURFACE_BRIDGE for span in spans))


def _bridge_settings(state):
    settings = state.request.settings
    return replace(settings, length_weight=4.0 * settings.length_weight,
                   curvature_weight=0.25 * settings.curvature_weight)


def _surface_candidate(state):
    output = np.asarray(state.structural).copy()
    for span in state.v25_surface_spans:
        _apply_surface_span(state, output, span)
    p5._restore_pins(output, state.pins)
    return output


def _apply_surface_span(state, output, span):
    indices = _span_indices(span, len(output)); world = state.v25_owner_worlds.get(span.owner_id)
    if world is None or not len(indices):
        return
    current = state.points[indices]
    closest, normals, distances, _ids, contained = world.nearest(current)
    directions = p5._contact_directions(current, closest, normals, distances, contained)
    output[indices] = _surface_step(state, indices, directions, distances, span.branch)


def _surface_step(state, indices, directions, distances, branch):
    current = state.points[indices]; delta = state.structural[indices] - current
    normal = np.sum(delta * directions, axis=1)[:, None] * directions
    tangent = delta - normal; radius = state.request.collision_policy.collision_radius
    shell = (float(_shell_factor(branch) * radius) - distances)[:, None] * directions
    return current + tangent + shell


def _shell_factor(branch):
    return 3.0 if branch is V2PlannerBranch.SURFACE_BRIDGE else 1.5


def _surface_policy_branches():
    return V2PlannerBranch.SURFACE_BRIDGE, V2PlannerBranch.SURFACE_MESH


def _span_indices(span, count):
    stop = min(int(count), int(span.first_edge + span.edge_count + 1))
    return np.arange(int(span.first_edge), stop, dtype=np.int64)


def _iterate_surface(state):
    for _trial in range(state.request.settings.max_accepted_steps):
        state.trials += 1; candidate = state.v21_first if _trial == 0 else p5._candidate(state)
        if p5._step_converged(state):
            return V2Termination.CONVERGED, "surface span fixed point"
        accepted, fraction, step = _accept_surface(state, candidate)
        if not accepted:
            return _surface_stop(step)
        if _trial == 0:
            state.v25_turns = _surface_turn_metrics(state); state.v25_recovery = _needs_recovery(state.v25_turns)
        if fraction >= 1.0 - 1.0e-12 and p5._step_converged(state):
            return V2Termination.CONVERGED, "surface span fixed point"
    return V2Termination.BUDGET_EXHAUSTED, "accepted-step cap exhausted"


def _accept_surface(state, candidate):
    envelope = p5._waypoint_envelope(state.points, (candidate,)); before = perf_counter()
    step = p5._safe_step_p51(state, state.points, candidate, envelope)
    state.ccd_ms += p5._elapsed(before); p5._absorb_ccd(state, step)
    if not step.valid or step.safe_step <= 1.0e-12:
        state.rejected += 1; return False, 0.0, step
    fraction = _descent_fraction(state, candidate, p5._backed_fraction(step.safe_step))
    return _accept_fraction(state, candidate, fraction), fraction, step


def _descent_fraction(state, candidate, safe):
    current = p5._merit(state, state.points); floor = 1.0e-12 * max(1.0, abs(current))
    for depth in range(9 if state.v25_recovery else 1):
        fraction = float(safe) * (0.5 ** depth)
        proposed = p5._interpolate(state.points, candidate, fraction)
        p5._restore_pins(proposed, state.pins)
        if p5._merit(state, proposed) <= current - floor:
            return fraction
    return 0.0


def _surface_turn_metrics(state):
    values = _turn_values(state.points); mask = _branch2_mask(state, state.v25_spans)[1:-1]
    selected = values[mask] if len(values) == len(mask) else values
    if not len(selected):
        return 0.0, 0.0
    return float(np.max(selected)), float(np.percentile(selected, 95.0))


def _turn_values(points):
    edges = np.diff(np.asarray(points), axis=0); lengths = np.linalg.norm(edges, axis=1)
    unit = edges / np.maximum(lengths[:, None], 1.0e-30)
    dots = np.sum(unit[:-1] * unit[1:], axis=1)
    return np.degrees(np.arccos(np.clip(dots, -1.0, 1.0)))


def _needs_recovery(metrics):
    maximum, p95 = metrics
    return bool(maximum >= 70.0 or p95 >= 35.0)


def _accept_fraction(state, candidate, fraction):
    state.v25_line_fractions.append(float(fraction))
    if fraction <= 0.0:
        state.rejected += 1; return False
    proposed = p5._interpolate(state.points, candidate, fraction)
    p5._restore_pins(proposed, state.pins); state.last_step = p5._normalized_step(state, proposed)
    state.points = proposed; state.accepted.append(float(p5._merit(state, proposed)))
    return True


def _surface_stop(step):
    if not step.valid and step.reason.value == "BACKEND_UNAVAILABLE":
        return V2Termination.BACKEND_UNAVAILABLE, "native collision backend unavailable"
    if step.safe_step <= 1.0e-12:
        return V2Termination.BLOCKED, "surface span motion is CCD-blocked"
    return V2Termination.STALLED, "surface span has no decreasing feasible step"


def _finish(state, termination, message, started):
    checked = p5._timed_validation(state, state.points); diagnostics = p5._diagnostics(state, checked)
    validated = bool(checked.valid and np.isfinite(state.points).all())
    if not validated:
        termination, message = V2Termination.UNSAFE_OUTPUT, "final independent validation failed"
    result = p5._result(state.request, state.planner, state.points, diagnostics,
                        termination, validated, message, V2_SOLVER_V25_BRANCH2_VERSION)
    return p5.V2Package5Result(result, state.planner, _trace(state, started))


def _trace(state, started):
    base = v24._trace(state, started)
    return V25Branch2Trace(**vars(base), branch2_active=True,
                           branch2_spans=len(state.v25_spans),
                           policy_ms=float(state.v25_policy_ms),
                           line_search_fractions=tuple(state.v25_line_fractions),
                           recovery_enabled=bool(state.v25_recovery),
                           acquired_max_turn=float(state.v25_turns[0]),
                           acquired_p95_turn=float(state.v25_turns[1]))


def _versioned(package, state=None):
    result = replace(package.result, engine_version=V2_SOLVER_V25_BRANCH2_VERSION)
    active = bool(state and _eligible(state)); count = _surface_span_count(state) if active else 0
    trace = V25Branch2Trace(**vars(package.trace), branch2_active=active, branch2_spans=count)
    return replace(package, result=result, trace=trace)


def _surface_span_count(state):
    if state is None:
        return 0
    return sum(span.branch in _SURFACE_BRANCHES for span in state.planner.spans)


def _branch2_mask(state, spans):
    mask = np.zeros(len(state.points), dtype=bool)
    for span in spans:
        mask[_span_indices(span, len(mask))] = True
    return mask
