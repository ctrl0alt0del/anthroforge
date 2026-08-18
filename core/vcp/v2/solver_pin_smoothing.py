"""Collision-safe local smoothing around authored Fiber pins."""

from dataclasses import dataclass, field, replace
from time import perf_counter

import numpy as np

from . import solver as p5
from . import solver_v21 as v21
from . import solver_v22 as v22
from . import solver_v23 as v23
from . import solver_v24 as v24
from .contracts import V2Termination, V2Topology
from .pin_smoothing_geometry import (curvature_energy, smoothing_candidate,
                                     pin_interpolating_candidate, smoothing_windows,
                                     surface_tangent_candidate,
                                     turn_metrics, window_turn_peak)
from .roadmap_corner_geometry import (roadmap_corner_candidate,
                                      roadmap_corner_window)


PIN_SMOOTHING_VERSION = "fiber-v2-pin-smoothing-1"
WINDOW_RADIUS = 4
TURN_THRESHOLD = 12.0
P95_ACTIVATION = 8.0
FIDELITY_WEIGHT = 0.10
RETRACTION_FACTORS = (2.0, 1.5)
FUSE_SECOND_STAGE = True
FUSED_SMOOTH_STRENGTH = 3.0
SURFACE_TANGENT_STRENGTH = 1.5
SURFACE_TURN_THRESHOLD = 45.0
GLOBAL_PIN_STRENGTH = 1.25
GLOBAL_PIN_P95 = 30.0
GLOBAL_PIN_SEGMENTS = 2
GLOBAL_PIN_LIFT = 1.0
ROADMAP_CORNER_RADIUS = 6
ROADMAP_CORNER_TURN = 60.0


@dataclass(frozen=True)
class PinSmoothingTrace(v24.V24Trace):
    retraction_active: bool = False
    retraction_ms: float = 0.0
    retraction_accepted: bool = False
    retraction_safe_fraction: float = 0.0
    owner_max_before: float = 0.0
    owner_max_after: float = 0.0
    retraction_factors: tuple = ()
    retraction_accepted_factors: tuple = ()
    fused_second_stage: bool = False
    smoothing_active: bool = False
    smoothing_ms: float = 0.0
    smoothing_candidate_ms: float = 0.0
    smoothing_nearest_ms: float = 0.0
    smoothing_ccd_ms: float = 0.0
    smoothing_validation_ms: float = 0.0
    smoothing_windows: int = 0
    batch_attempts: int = 0
    batch_accepted: int = 0
    local_attempts: int = 0
    local_accepted: int = 0
    blocked_attempts: int = 0
    smoothing_ccd_pairs: int = 0
    smoothing_ccd_tested: int = 0
    maximum_turn_before: float = 0.0
    maximum_turn_after: float = 0.0
    p95_turn_before: float = 0.0
    p95_turn_after: float = 0.0
    curvature_before: float = 0.0
    curvature_after: float = 0.0
    smoothing_fractions: tuple = ()
    smoothing_accepted_fractions: tuple = ()
    smoothing_limiters: tuple = ()
    surface_tangent_attempts: int = 0
    surface_tangent_accepted: int = 0
    surface_tangent_ms: float = 0.0
    global_pin_attempts: int = 0
    global_pin_accepted: int = 0
    global_pin_ms: float = 0.0
    roadmap_corner_attempts: int = 0
    roadmap_corner_accepted: int = 0
    roadmap_corner_window: tuple = ()


@dataclass
class _State:
    request: object
    planner: object
    snapshot: object
    reference: np.ndarray
    points: np.ndarray
    pins: dict
    windows: tuple
    pair_cache: object
    owner_worlds: dict
    fractions: list = field(default_factory=list)
    accepted_fractions: list = field(default_factory=list)
    accepted: int = 0
    rejected: int = 0
    blocked: int = 0
    batch_attempts: int = 0
    batch_accepted: int = 0
    local_attempts: int = 0
    local_accepted: int = 0
    ccd_pairs: int = 0
    ccd_tested: int = 0
    candidate_ms: float = 0.0
    nearest_ms: float = 0.0
    ccd_ms: float = 0.0
    validation_ms: float = 0.0
    limiters: list = field(default_factory=list)
    retraction_ms: float = 0.0
    retraction_accepted: bool = False
    retraction_fraction: float = 0.0
    owner_max_before: float = 0.0
    owner_max_after: float = 0.0
    retraction_factors: list = field(default_factory=list)
    retraction_accepted_factors: list = field(default_factory=list)
    fused_second_stage: bool = False
    surface_tangent_attempts: int = 0
    surface_tangent_accepted: int = 0
    surface_tangent_ms: float = 0.0
    global_pin_attempts: int = 0
    global_pin_accepted: int = 0
    global_pin_ms: float = 0.0
    roadmap_corner_attempts: int = 0
    roadmap_corner_accepted: int = 0
    roadmap_corner_window: tuple = ()


def solve_pin_smoothing(request, snapshot=None, contact_weight=p5.DEFAULT_CONTACT_WEIGHT, preview=False):
    started = perf_counter(); signature, signature_ms = v22._timed_signature(request)
    resources = _resources(request, snapshot, signature, signature_ms, preview, started, contact_weight)
    if not isinstance(resources, tuple):
        return resources
    planner, route, policy, triangle, world, cache_hit, snapshot_ms, world_ms = resources
    live = v24._state(request, planner, triangle, contact_weight, route, world, signature,
                      signature_ms, cache_hit, policy, snapshot_ms, world_ms)
    termination, message, smoothing = _iterate_live(live)
    return _finish_live(live, termination, message, smoothing, started)


def _resources(request, supplied, signature, signature_ms, preview, started, weight):
    try:
        world, world_ms = v24._world(request); triangle, hit, snap_ms = v24._snapshot(request, supplied, world.closed_flags)
    except (OSError, RuntimeError, ValueError, AttributeError) as error:
        return _versioned(v24._unavailable(request, signature, started, weight, error), started)
    planner, route, policy = v23._planner(request, triangle, world, signature, bool(preview), v24._ROUTE_CACHE)
    if not planner.succeeded:
        base = v24._failed(request, planner, started, weight, route, policy, signature, signature_ms,
                           hit, snap_ms, world_ms, world.closed_flags)
        return _versioned(base, started)
    return planner, route, policy, triangle, world, hit, snap_ms, world_ms


def _iterate_live(live):
    if live.certificates_enabled:
        return _dynamic_live(live)
    smoothing = None
    for trial in range(live.request.settings.max_accepted_steps):
        live.trials += 1; candidate = live.v21_first if trial == 0 else p5._candidate(live)
        changed = live.contact_changed; accepted, full = v21._accept_light(live, candidate)
        if _should_recover(trial, accepted, full) and _recoverable(live) and smoothing is None:
            smoothing = _recover_live(live)
            if smoothing.accepted:
                return V2Termination.STALLED, "partial fixed-point step recovered by pin smoothing", smoothing
        if accepted and full and not changed and p5._step_converged(live):
            return V2Termination.CONVERGED, "V2.4 light fixed point", smoothing
        if not accepted and not changed:
            return _blocked_live(live, smoothing)
    return V2Termination.BUDGET_EXHAUSTED, "accepted-step cap exhausted", smoothing


def _dynamic_live(live):
    termination, message = v21._solve_state(live)
    smoothing = _recover_roadmap(live, termination)
    if smoothing is not None and smoothing.roadmap_corner_accepted:
        return V2Termination.STALLED, "collision-safe roadmap corner recovered", smoothing
    return termination, message, smoothing


def _recover_roadmap(live, termination):
    if not _roadmap_context(live, termination):
        return None
    window = roadmap_corner_window(live.points, live.planner.pin_indices,
                                   live.planner.spans, ROADMAP_CORNER_RADIUS, ROADMAP_CORNER_TURN)
    if window is None:
        return None
    state = _roadmap_state(live, window); candidate = _roadmap_candidate(state, window)
    state.roadmap_corner_accepted = int(_attempt_roadmap(state, candidate)); _merge_live(live, state)
    return state


def _roadmap_context(live, termination):
    names = ("points", "planner", "request", "snapshot")
    return bool(termination is V2Termination.BUDGET_EXHAUSTED and
                all(hasattr(live, name) for name in names))


def _roadmap_state(live, window):
    points = np.asarray(live.points, dtype=np.float64); indices = tuple(live.planner.pin_indices)
    pins = {int(index): np.asarray(anchor.point) for index, anchor in zip(indices, live.request.anchors)}
    state = _State(live.request, live.planner, live.snapshot, points.copy(), points.copy(), pins,
                   (window,), live.pair_cache or p5.V2SweepPairCache(), {})
    state.roadmap_corner_attempts = 1
    state.roadmap_corner_window = (window.left, window.corner, window.right)
    return state


def _roadmap_candidate(state, window):
    started = perf_counter(); candidate = roadmap_corner_candidate(state.points, window)
    p5._restore_pins(candidate, state.pins); state.candidate_ms += p5._elapsed(started)
    return candidate


def _attempt_roadmap(state, candidate):
    if not _roadmap_quality(state.points, candidate, state.reference):
        state.rejected += 1; return False
    envelope = p5._waypoint_envelope(state.points, (candidate,)); started = perf_counter()
    step = p5._safe_step_p51(state, state.points, candidate, envelope)
    state.ccd_ms += p5._elapsed(started); p5._absorb_ccd(state, step); state.limiters.append(_limiter(state))
    if not step.valid or step.safe_step <= 1.0e-12:
        state.rejected += 1; state.blocked += 1; return False
    return _accept_roadmap_fraction(state, candidate, p5._backed_fraction(step.safe_step))


def _accept_roadmap_fraction(state, candidate, safe):
    for depth in range(7):
        fraction = float(safe) * (0.5 ** depth); proposed = p5._interpolate(state.points, candidate, fraction)
        p5._restore_pins(proposed, state.pins)
        if _roadmap_valid(state, proposed):
            state.points = proposed; state.accepted += 1; state.local_accepted += 1
            state.accepted_fractions.append(fraction); return True
    state.rejected += 1; return False


def _roadmap_valid(state, proposed):
    started = perf_counter(); checked = p5._validate(proposed, state.request, state.planner, state.snapshot)
    state.validation_ms += p5._elapsed(started)
    return bool(checked.valid and _roadmap_quality(state.points, proposed, state.reference))


def _roadmap_quality(before, after, reference):
    old, new = turn_metrics(before), turn_metrics(after)
    drop = old[0] - new[0]; required = max(5.0, 0.10 * old[0])
    smoother = curvature_energy(after, reference) < curvature_energy(before, reference)
    return bool(drop >= required and new[2] <= old[2] + 1.0 and smoother)


def _should_recover(trial, accepted, full):
    return bool(int(trial) == 0 and accepted and not full)


def _recoverable(live):
    return bool(live.request.settings.topology is V2Topology.OPEN and
                len(live.planner.pin_indices) >= 2 and
                not _has_roadmap(live.planner) and
                turn_metrics(live.points)[1] >= P95_ACTIVATION)


def _has_roadmap(planner):
    return any(row.branch.value == "ROADMAP" for row in getattr(planner, "spans", ()))


def _blocked_live(live, smoothing):
    return V2Termination.BLOCKED, "V2.4 light path is blocked", smoothing


def _recover_live(live):
    state = _smoothing_state(live); _smooth_global_pins(state)
    if state.global_pin_accepted:
        _merge_live(live, state); return state
    _retract_bridges(state)
    if state.retraction_accepted and not state.fused_second_stage:
        _reset_smoothing_reference(state)
    if not state.fused_second_stage:
        _smooth_surface_boundaries(state)
    if not state.fused_second_stage and not state.surface_tangent_accepted:
        _smooth(state)
    _merge_live(live, state); return state


def _smoothing_state(live):
    points = np.asarray(live.points, dtype=np.float64); indices = tuple(live.planner.pin_indices)
    request = live.request
    pins = {int(index): np.asarray(anchor.point) for index, anchor in zip(indices, request.anchors)}
    windows = smoothing_windows(points, indices, WINDOW_RADIUS, TURN_THRESHOLD)
    owners = _owner_worlds(request, windows, live.planner.spans)
    return _State(request, live.planner, live.snapshot, points.copy(), points.copy(), pins,
                  windows, live.pair_cache or p5.V2SweepPairCache(), owners)


def _merge_live(live, state):
    live.ccd_ms += state.ccd_ms; live.candidate_ms += state.candidate_ms
    live.ccd_pairs += state.ccd_pairs; live.ccd_tested += state.ccd_tested
    if state.accepted:
        live.points = state.points.copy(); live.accepted.append(float(p5._merit(live, live.points)))


def _owner_worlds(request, windows, spans):
    owners = {request.anchors[row.anchor].owner_id for row in windows if request.anchors[row.anchor].owner_id}
    owners.update(row.owner_id for row in spans if row.branch.value == "SURFACE_BRIDGE" and row.owner_id)
    return {owner: p5.cached_native_collision_world(p5._owner_colliders(request, owner))
            for owner in owners}


def _reset_smoothing_reference(state):
    state.reference = state.points.copy(); indices = tuple(state.planner.pin_indices)
    state.windows = smoothing_windows(state.reference, indices, WINDOW_RADIUS, TURN_THRESHOLD)


def _smooth_global_pins(state):
    started = perf_counter()
    if _global_pin_supported(state):
        state.global_pin_attempts = 1; candidate = _global_pin_target(state)
        if _global_candidate_ready(state, candidate):
            state.global_pin_accepted = int(_advance_global_pin(state, candidate))
    state.global_pin_ms = p5._elapsed(started)


def _global_pin_supported(state):
    owner = _global_owner(state); spans = tuple(state.planner.spans)
    return bool(len(state.pins) >= 4 and owner and turn_metrics(state.points)[1] >= GLOBAL_PIN_P95 and
                spans and all(row.branch.value == "SURFACE_BRIDGE" and row.owner_id == owner for row in spans))


def _global_owner(state):
    owners = {row.owner_id for row in state.request.anchors if row.owner_id}
    return next(iter(owners)) if len(owners) == 1 else ""


def _global_pin_target(state):
    target = pin_interpolating_candidate(state.reference, tuple(state.pins), GLOBAL_PIN_STRENGTH)
    world = state.owner_worlds.get(_global_owner(state)); indices = _all_movable(state)
    started = perf_counter(); normals = p5._unit_rows(world.nearest(state.reference[indices])[1])
    delta = target[indices] - state.reference[indices]
    target[indices] = state.reference[indices] + delta - np.sum(delta*normals, axis=1)[:, None]*normals
    p5._restore_pins(target, state.pins); state.nearest_ms += p5._elapsed(started); return target


def _all_movable(state):
    rows = np.arange(len(state.points), dtype=np.int64); pins = np.asarray(tuple(state.pins), dtype=np.int64)
    return rows[~np.isin(rows, pins)]


def _global_candidate_ready(state, candidate):
    return _turns_improve(turn_metrics(state.points), turn_metrics(candidate))


def _global_waypoints(state, candidate):
    world = state.owner_worlds[_global_owner(state)]; nearest = world.nearest(state.points)
    direction = p5._contact_directions(state.points, *nearest[:3], nearest[4]); direction[list(state.pins)] = 0.0
    radius = GLOBAL_PIN_LIFT * state.request.collision_policy.collision_radius; rows = []
    for factor in np.linspace(1.0/GLOBAL_PIN_SEGMENTS, 1.0, GLOBAL_PIN_SEGMENTS):
        row = p5._interpolate(state.points, candidate, factor)
        row += radius*np.sin(np.pi*factor)*direction; p5._restore_pins(row, state.pins); rows.append(row)
    return tuple(rows)


def _advance_global_pin(state, candidate):
    waypoints = _global_waypoints(state, candidate); envelope = p5._waypoint_envelope(state.points, waypoints)
    source = state.points.copy()
    for target in waypoints:
        if not _global_full_step(state, source, target, envelope):
            state.rejected += 1; return False
        source = target
    return _accept_global_pin(state, source)


def _global_full_step(state, source, target, envelope):
    started = perf_counter(); step = p5._safe_step_p51(state, source, target, envelope)
    state.ccd_ms += p5._elapsed(started); p5._absorb_ccd(state, step); state.limiters.append(_limiter(state))
    return bool(step.valid and step.safe_step >= 1.0 - 1.0e-12)


def _accept_global_pin(state, candidate):
    started = perf_counter(); checked = p5._validate(candidate, state.request, state.planner, state.snapshot)
    state.validation_ms += p5._elapsed(started)
    if not checked.valid or not _turns_improve(turn_metrics(state.points), turn_metrics(candidate)):
        state.rejected += 1; return False
    state.points = candidate; state.accepted += 1; state.accepted_fractions.append(1.0); return True


def _retract_bridges(state):
    spans = _bridge_spans(state.planner.spans)
    if not _retraction_supported(spans):
        return
    started = perf_counter(); state.owner_max_before = _bridge_distance(state, state.points, spans)
    first = _retraction_stage(state, spans, float(RETRACTION_FACTORS[0]))
    if first and FUSE_SECOND_STAGE and len(RETRACTION_FACTORS) > 1:
        state.fused_second_stage = _fused_stage(state, spans, float(RETRACTION_FACTORS[1]))
    if first and not state.fused_second_stage:
        for factor in RETRACTION_FACTORS[1:]:
            _retraction_stage(state, spans, float(factor))
    state.owner_max_after = _bridge_distance(state, state.points, spans)
    state.retraction_ms = p5._elapsed(started)


def _bridge_spans(spans):
    return tuple(row for row in spans if row.branch.value == "SURFACE_BRIDGE" and row.owner_id)


def _retraction_supported(spans):
    rows = tuple(spans)
    if not 0 < len(rows) <= 2 or len({row.owner_id for row in rows}) != 1:
        return False
    if max(float(row.lift_factor) for row in rows) < 4.0:
        return False
    return all(left.first_edge + left.edge_count == right.first_edge
               for left, right in zip(rows, rows[1:]))


def _retraction_stage(state, spans, factor):
    state.retraction_factors.append(factor); accepted = state.accepted
    candidate = _bridge_candidate(state, spans, factor); _attempt_retraction(state, candidate, spans)
    if state.accepted > accepted:
        state.retraction_accepted_factors.append(factor)
    return bool(state.accepted > accepted)


def _fused_stage(state, spans, factor):
    state.retraction_factors.append(factor); accepted = state.accepted
    candidate = _bridge_candidate(state, spans, factor); candidate = _smooth_reference(state, candidate)
    _attempt_retraction(state, candidate, spans)
    if state.accepted > accepted:
        state.retraction_accepted_factors.append(factor)
    return bool(state.accepted > accepted)


def _smooth_reference(state, reference):
    indices = tuple(state.planner.pin_indices)
    windows = smoothing_windows(reference, indices, WINDOW_RADIUS, TURN_THRESHOLD)
    target = smoothing_candidate(reference, indices, windows, FUSED_SMOOTH_STRENGTH)
    target = _project_tangent_from(state, target, windows, reference)
    p5._restore_pins(target, state.pins); return target


def _bridge_candidate(state, spans, factor):
    output = state.points.copy()
    for span in spans:
        _retract_span(state, output, span, factor)
    p5._restore_pins(output, state.pins); return output


def _retract_span(state, output, span, factor):
    indices = _span_indices(span, state.pins); world = state.owner_worlds.get(span.owner_id)
    if world is None or not len(indices):
        return
    started = perf_counter(); points = state.points[indices]
    closest, normals, distances, _ids, contained = world.nearest(points)
    direction = p5._contact_directions(points, closest, normals, distances, contained)
    radius = factor * state.request.collision_policy.collision_radius
    output[indices] = closest + radius * direction; state.nearest_ms += p5._elapsed(started)


def _span_indices(span, pins):
    values = np.arange(span.first_edge + 1, span.first_edge + span.edge_count, dtype=np.int64)
    return values[~np.isin(values, np.asarray(tuple(pins), dtype=np.int64))]


def _attempt_retraction(state, candidate, spans):
    envelope = p5._waypoint_envelope(state.points, (candidate,)); started = perf_counter()
    step = p5._safe_step_p51(state, state.points, candidate, envelope)
    state.ccd_ms += p5._elapsed(started); p5._absorb_ccd(state, step); state.limiters.append(_limiter(state))
    if not step.valid or step.safe_step <= 1.0e-12:
        state.blocked += 1; return
    _accept_retraction(state, candidate, spans, p5._backed_fraction(step.safe_step))


def _accept_retraction(state, candidate, spans, safe):
    before_turns = turn_metrics(state.points); before_distance = _bridge_distance(state, state.points, spans)
    for depth in range(7):
        fraction = float(safe) * (0.5 ** depth); proposed = p5._interpolate(state.points, candidate, fraction)
        p5._restore_pins(proposed, state.pins)
        if _retraction_improves(state, proposed, spans, before_distance, before_turns):
            state.points = proposed; state.accepted += 1; state.retraction_accepted = True
            state.retraction_fraction = fraction; state.accepted_fractions.append(fraction); return
    state.rejected += 1


def _retraction_improves(state, proposed, spans, before_distance, before_turns):
    distance = _bridge_distance(state, proposed, spans); turns = turn_metrics(proposed)
    meaningful = distance < before_distance - max(1.0e-7, 0.01 * state.request.collision_policy.collision_radius)
    bounded = turns[0] <= before_turns[0] + 5.0 and turns[1] <= before_turns[1] + 2.0
    return bool(meaningful and bounded and turns[2] <= 1.05 * before_turns[2])


def _bridge_distance(state, points, spans):
    values = []
    for span in spans:
        indices = _span_indices(span, state.pins); world = state.owner_worlds.get(span.owner_id)
        if world is not None and len(indices):
            started = perf_counter(); values.extend(world.nearest(np.asarray(points)[indices])[2])
            state.nearest_ms += p5._elapsed(started)
    return max((float(value) for value in values), default=0.0)


def _smooth(state):
    if not state.windows:
        return
    started = perf_counter(); candidate = _candidate(state, state.windows, global_target=True)
    state.batch_attempts += 1; accepted = _attempt(state, candidate)
    state.batch_accepted += int(accepted)
    if not accepted:
        _smooth_individually(state)
    state.smoothing_ms = p5._elapsed(started)


def _smooth_surface_boundaries(state):
    started = perf_counter()
    for window in state.windows:
        side = _surface_side(state, window)
        if side and window_turn_peak(state.points, window) >= SURFACE_TURN_THRESHOLD:
            state.surface_tangent_attempts += 1
            state.surface_tangent_accepted += int(_attempt_surface_tangent(state, window, side))
    state.surface_tangent_ms = p5._elapsed(started)


def _surface_side(state, window):
    owner = state.request.anchors[window.anchor].owner_id
    incoming = _surface_edge(state.planner.spans, window.pin - 1, owner)
    outgoing = _surface_edge(state.planner.spans, window.pin, owner)
    if incoming == outgoing:
        return ""
    return "incoming" if incoming else "outgoing"


def _surface_edge(spans, edge, owner):
    return any(row.branch.value == "SURFACE_BRIDGE" and row.owner_id == owner and
               row.first_edge <= edge < row.first_edge + row.edge_count for row in spans)


def _attempt_surface_tangent(state, window, side):
    candidate = _surface_tangent_target(state, window, side); state.local_attempts += 1
    if not _surface_turns_improve(turn_metrics(state.points), turn_metrics(candidate)):
        state.rejected += 1; return False
    envelope = p5._waypoint_envelope(state.points, (candidate,)); started = perf_counter()
    step = p5._safe_step_p51(state, state.points, candidate, envelope)
    state.ccd_ms += p5._elapsed(started); p5._absorb_ccd(state, step); state.limiters.append(_limiter(state))
    if not step.valid or step.safe_step <= 1.0e-12:
        state.blocked += 1; return False
    return _accept_surface_tangent(state, candidate, p5._backed_fraction(step.safe_step))


def _surface_tangent_target(state, window, side):
    owner = state.request.anchors[window.anchor].owner_id; world = state.owner_worlds.get(owner)
    started = perf_counter(); normal = _pin_normal(world, state.points, window.pin)
    target = surface_tangent_candidate(state.points, window, normal, side, SURFACE_TANGENT_STRENGTH)
    target = _project_local_tangents(world, state.points, target, window, state.pins)
    p5._restore_pins(target, state.pins); state.candidate_ms += p5._elapsed(started); return target


def _pin_normal(world, points, pin):
    return _unit(world.nearest(points[pin:pin + 1])[1][0]) if world is not None else np.zeros(3)


def _project_local_tangents(world, reference, target, window, pins):
    if world is None:
        return target
    indices = _movable_indices(window, pins); normals = p5._unit_rows(world.nearest(reference[indices])[1])
    delta = target[indices] - reference[indices]
    target[indices] = reference[indices] + delta - np.sum(delta * normals, axis=1)[:, None] * normals
    return target


def _accept_surface_tangent(state, candidate, fraction):
    proposed = p5._interpolate(state.points, candidate, fraction); p5._restore_pins(proposed, state.pins)
    started = perf_counter(); checked = p5._validate(proposed, state.request, state.planner, state.snapshot)
    state.validation_ms += p5._elapsed(started)
    if not checked.valid or not _surface_turns_improve(turn_metrics(state.points), turn_metrics(proposed)):
        state.rejected += 1; return False
    state.points = proposed; state.accepted += 1; state.local_accepted += 1
    state.accepted_fractions.append(float(fraction)); return True


def _surface_turns_improve(before, after):
    drop = before[0] - after[0]; required = max(5.0, 0.10 * before[0])
    return bool(drop >= required and after[1] <= before[1] + 2.0 and after[2] <= before[2] + 1.0e-9)


def _smooth_individually(state):
    for window in state.windows:
        state.local_attempts += 1; candidate = _candidate(state, (window,), global_target=False)
        accepted = _attempt(state, candidate); state.local_accepted += int(accepted)


def _candidate(state, windows, global_target):
    started = perf_counter(); target = smoothing_candidate(state.reference, tuple(state.pins), windows)
    target = _project_tangent(state, target, windows)
    if not global_target:
        target = _local_target(state.points, target, windows[0])
    p5._restore_pins(target, state.pins)
    state.candidate_ms += p5._elapsed(started); return target


def _local_target(current, target, window):
    output = np.asarray(current).copy(); rows = slice(window.left, window.right + 1)
    output[rows] = target[rows]; return output


def _project_tangent(state, candidate, windows):
    return _project_tangent_from(state, candidate, windows, state.reference)


def _project_tangent_from(state, candidate, windows, reference):
    output = np.asarray(candidate).copy()
    for window in windows:
        _project_window_tangent(state, output, window, reference)
    return output


def _project_window_tangent(state, output, window, reference):
    owner = state.request.anchors[window.anchor].owner_id; world = state.owner_worlds.get(owner)
    indices = _movable_indices(window, state.pins)
    if world is None or not len(indices):
        return
    started = perf_counter(); point = reference[window.pin:window.pin + 1]
    _closest, normals, _distances, _ids, _contained = world.nearest(point)
    delta = output[indices] - reference[indices]; normal = _unit(normals[0])
    output[indices] = reference[indices] + _tangent_rows(delta, normal)
    state.nearest_ms += p5._elapsed(started)


def _movable_indices(window, pins):
    values = np.arange(window.left, window.right + 1, dtype=np.int64)
    return values[~np.isin(values, np.asarray(tuple(pins), dtype=np.int64))]


def _unit(value):
    length = float(np.linalg.norm(value))
    return np.asarray(value) / length if length > 1.0e-12 else np.zeros(3)


def _tangent_rows(delta, normal):
    values = np.asarray(delta); direction = np.asarray(normal)
    return values - np.sum(values * direction, axis=1)[:, None] * direction


def _attempt(state, candidate):
    if not _improves(state, candidate):
        state.rejected += 1; return False
    envelope = p5._waypoint_envelope(state.points, (candidate,)); started = perf_counter()
    step = p5._safe_step_p51(state, state.points, candidate, envelope)
    state.ccd_ms += p5._elapsed(started); p5._absorb_ccd(state, step)
    state.limiters.append(_limiter(state))
    if not step.valid or step.safe_step <= 1.0e-12:
        state.rejected += 1; state.blocked += 1; return False
    return _accept_fraction(state, candidate, p5._backed_fraction(step.safe_step))


def _accept_fraction(state, candidate, safe):
    current = _merit(state, state.points); turns = turn_metrics(state.points)
    for depth in range(7):
        fraction = float(safe) * (0.5 ** depth); proposed = p5._interpolate(state.points, candidate, fraction)
        p5._restore_pins(proposed, state.pins)
        if _merit(state, proposed) < current and _turns_improve(turns, turn_metrics(proposed)):
            state.points = proposed; state.accepted_fractions.append(fraction)
            state.accepted += 1; return True
    state.rejected += 1; return False


def _improves(state, candidate):
    return bool(_merit(state, candidate) < _merit(state, state.points) and
                _turns_improve(turn_metrics(state.points), turn_metrics(candidate)))


def _turns_improve(before, after):
    return all(float(new) <= float(old) + 1.0e-9 for old, new in zip(before, after))


def _limiter(state):
    edge, face = state.pair_cache.priority or (-1, -1)
    owner = state.snapshot.face_owners[face] if 0 <= face < len(state.snapshot.face_owners) else ""
    return int(edge), int(face), str(owner)


def _merit(state, points):
    edge = np.linalg.norm(np.diff(state.reference, axis=0), axis=1)
    scale = max(float(np.median(edge)), 1.0e-12)
    fidelity = float(np.sum((np.asarray(points) - state.reference) ** 2)) / (scale * scale)
    return curvature_energy(points, state.reference) + FIDELITY_WEIGHT * fidelity


def _finish_live(live, termination, message, smoothing, started):
    checked = p5._timed_validation(live, live.points); diagnostics = p5._diagnostics(live, checked)
    validated = bool(checked.valid and np.isfinite(live.points).all())
    if not validated:
        termination, message = V2Termination.UNSAFE_OUTPUT, "final independent validation failed"
    result = replace(v24._result(live, diagnostics, termination, validated, message),
                     engine_version=PIN_SMOOTHING_VERSION)
    trace = _live_trace(live, smoothing, started)
    return p5.V2Package5Result(result, live.planner, trace)


def _live_trace(live, smoothing, started):
    base = v24._trace(live, started)
    if smoothing is None:
        return PinSmoothingTrace(**vars(base))
    before, after = turn_metrics(smoothing.reference), turn_metrics(smoothing.points)
    return PinSmoothingTrace(**vars(base), **_trace_values(smoothing, before, after))


def _trace_values(state, before, after):
    values = _retraction_trace(state); values.update(_smoothing_work_trace(state))
    values.update(_surface_trace(state)); values.update(_global_trace(state))
    values.update(_roadmap_trace(state)); values.update(_smoothing_quality_trace(state, before, after)); return values


def _retraction_trace(state):
    return {"retraction_active": _retraction_supported(_bridge_spans(state.planner.spans)),
            "retraction_ms": state.retraction_ms, "retraction_accepted": state.retraction_accepted,
            "retraction_safe_fraction": state.retraction_fraction,
            "owner_max_before": state.owner_max_before, "owner_max_after": state.owner_max_after,
            "retraction_factors": tuple(state.retraction_factors),
            "retraction_accepted_factors": tuple(state.retraction_accepted_factors),
            "fused_second_stage": state.fused_second_stage}


def _smoothing_work_trace(state):
    return {"smoothing_active": bool(state.windows), "smoothing_ms": getattr(state, "smoothing_ms", 0.0),
            "smoothing_candidate_ms": state.candidate_ms, "smoothing_nearest_ms": state.nearest_ms,
            "smoothing_ccd_ms": state.ccd_ms, "smoothing_validation_ms": state.validation_ms,
            "smoothing_windows": len(state.windows), "batch_attempts": state.batch_attempts,
            "batch_accepted": state.batch_accepted, "local_attempts": state.local_attempts,
            "local_accepted": state.local_accepted, "blocked_attempts": state.blocked,
            "smoothing_ccd_pairs": state.ccd_pairs, "smoothing_ccd_tested": state.ccd_tested}


def _surface_trace(state):
    return {"surface_tangent_attempts": state.surface_tangent_attempts,
            "surface_tangent_accepted": state.surface_tangent_accepted,
            "surface_tangent_ms": state.surface_tangent_ms}


def _global_trace(state):
    return {"global_pin_attempts": state.global_pin_attempts,
            "global_pin_accepted": state.global_pin_accepted,
            "global_pin_ms": state.global_pin_ms}


def _roadmap_trace(state):
    return {"roadmap_corner_attempts": state.roadmap_corner_attempts,
            "roadmap_corner_accepted": state.roadmap_corner_accepted,
            "roadmap_corner_window": tuple(state.roadmap_corner_window)}


def _smoothing_quality_trace(state, before, after):
    return {"maximum_turn_before": before[0], "maximum_turn_after": after[0],
            "p95_turn_before": before[1], "p95_turn_after": after[1],
            "curvature_before": curvature_energy(state.reference, state.reference),
            "curvature_after": curvature_energy(state.points, state.reference),
            "smoothing_fractions": tuple(state.fractions),
            "smoothing_accepted_fractions": tuple(state.accepted_fractions),
            "smoothing_limiters": tuple(state.limiters)}


def _versioned(base, started):
    result = replace(base.result, engine_version=PIN_SMOOTHING_VERSION)
    values = dict(vars(base.trace)); values["total_ms"] = p5._elapsed(started)
    return replace(base, result=result, trace=PinSmoothingTrace(**values))
