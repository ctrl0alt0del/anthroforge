"""Planner-independent augmented-contact Fiber V2 production core."""

from dataclasses import dataclass, replace
from time import perf_counter

import numpy as np

from .collision import (V2OwnerContact, build_triangle_snapshot_known,
                        begin_collision_free_step, cached_native_collision_world_batch,
                        collision_backend_status)
from .collision_native import native_contact_block_solve
from .contracts import V2Diagnostics, V2Result, V2Termination, V2Topology
from .planner import (V2PlannerDiagnostics, V2PlannerMode, V2PlannerResult,
                      plan_reference_v43)
from .structural import _base_bands, _static_settings
from .trust_sqp import (actual_reduction, model_reduction, solve_trust_sqp,
                         objective_diagonal, objective_energy, objective_gradient,
                         update_trust_radius)


V2_CONTACT_CORE_VERSION = "fiber-v2-production-3"


@dataclass(frozen=True)
class V2ContactPolicy:
    true_length_irls: bool = False
    true_length_epsilon_ratio: float = 1.0e-4
    spacing_weight_ratio: float = 0.0
    curvature_weight_scale: float = 1.0
    adaptive_quality: bool = False
    sqp_regularization_ratio: float = 0.0
    adaptive_regularized_sqp: bool = False


@dataclass(frozen=True)
class V2Contact:
    edge: int
    factor: float
    collider_id: str
    triangle_id: int
    feature_id: str
    normal: tuple
    gap: float
    linearized_gap: float = float("nan")
    multiplier: float = 0.0
    group: int = -1
    age: int = 0
    clear_streak: int = 0

    @property
    def key(self):
        if self.feature_id == "LIMITING":
            return self.edge, self.collider_id, -1, self.feature_id
        return self.edge, self.collider_id, self.triangle_id, self.feature_id


@dataclass(frozen=True)
class V2ContactGroup:
    group: int
    first_edge: int
    last_edge: int
    collider_id: str
    escape_candidates: tuple = ()
    selected_side: tuple = ()
    escape_distance: float = 0.0


@dataclass(frozen=True)
class V2FeasibilityState:
    maximum_violation: float
    squared_violation: float
    new_collision_count: int
    pin_residual: float
    feasible: bool
    penetrating_groups: tuple = ()


@dataclass(frozen=True)
class V2ContactCoreTrace:
    planner_ms: float = 0.0
    total_ms: float = 0.0
    feasibility_history: tuple = ()
    multiplier_history: tuple = ()
    condition_history: tuple = ()
    accepted_merits: tuple = ()
    limiting_history: tuple = ()
    fixed_residual_history: tuple = ()
    stationarity_history: tuple = ()
    trust_history: tuple = ()
    rejection_reasons: tuple = ()
    final_contacts: tuple = ()
    stationarity_profile: tuple = ()
    ccd_step_history: tuple = ()
    model_ratio_history: tuple = ()
    normal_step_history: tuple = ()
    tangent_step_history: tuple = ()
    sqp_solve_ms: float = 0.0
    iteration_trace: tuple = ()
    reference_points: tuple = ()
    pin_indices: tuple = ()
    policy_stats: tuple = ()
    regularization_history: tuple = ()


@dataclass(frozen=True)
class V2ContactCoreResult:
    result: V2Result
    planner: V2PlannerResult
    trace: V2ContactCoreTrace

    @property
    def succeeded(self):
        return self.result.successful


@dataclass
class V2ContactCoreSession:
    request: object
    snapshot: object = None
    preview: bool = False
    use_planner: bool = True
    use_filter_sqp: bool = False
    started: float = 0.0
    state: object = None
    package: object = None
    done: bool = False
    trials: int = 0
    phase: str = "NEW"
    seed_candidates: tuple = ()
    seed_index: int = 0
    seed_best: object = None
    diagnostic_trace: bool = False
    policy: object = None

    def step(self):
        return _advance_contact_session(self)

    @property
    def points(self):
        return () if self.state is None else self.state.points

    @property
    def infeasible(self):
        return bool(self.state is not None and not self.state.metrics.feasible)


@dataclass
class _ContactState:
    request: object
    snapshot: object
    world: object
    planner: object
    q: np.ndarray
    points: np.ndarray
    pin_indices: tuple
    pins: dict
    contacts: dict
    groups: tuple
    mu: float
    metrics: object
    started_invalid: bool
    accepted: int = 0
    rejected: int = 0
    stalled: int = 0
    feasibility_iterations: int = 0
    injected: int = 0
    retired: int = 0
    limiting: int = 0
    regroupings: int = 0
    multiplier_updates: int = 0
    fixed_residual: float = float("inf")
    stationarity: float = float("inf")
    condition: float = 0.0
    energy_streak: int = 0
    contact_ms: float = 0.0
    assembly_ms: float = 0.0
    factor_ms: float = 0.0
    solve_ms: float = 0.0
    ccd_ms: float = 0.0
    ccd_candidates: int = 0
    ccd_tested: int = 0
    validation_ms: float = 0.0
    feasibility_history: list = None
    multiplier_history: list = None
    condition_history: list = None
    energy_history: list = None
    group_sides: dict = None
    limiting_history: list = None
    fixed_history: list = None
    stationarity_history: list = None
    trust_history: list = None
    trust_radius: float = 0.0
    min_trust: float = 0.0
    max_trust: float = 0.0
    accelerated_steps: int = 0
    rejection_reasons: list = None
    pending_candidate: object = None
    pending_sweep: object = None
    filter_sqp_enabled: bool = False
    pending_sqp: object = None
    model_ratio_history: list = None
    normal_step_history: list = None
    tangent_step_history: list = None
    sqp_solve_ms: float = 0.0
    injection_streak: int = 0
    owner_span_override: float = 0.0
    diagnostic_enabled: bool = False
    diagnostic_events: list = None
    diagnostic_proposal: int = 0
    policy: object = None
    quality_adapted: bool = False
    quality_spacing: bool = False
    quality_trigger: str = ""
    sqp_regularization: float = 0.0
    regularization_scale: float = 0.0
    regularization_increases: int = 0
    regularization_decreases: int = 0


def solve_contact_core(request, snapshot=None, preview=False, use_planner=True,
                       use_filter_sqp=False, owner_span_override=0.0,
                       diagnostic_trace=False, policy=None):
    session = begin_contact_core(request, snapshot, preview, use_planner,
        use_filter_sqp, owner_span_override, diagnostic_trace, policy)
    while not session.done: session.step()
    return session.package


def begin_contact_core(request, snapshot=None, preview=False, use_planner=True,
                       use_filter_sqp=False, owner_span_override=0.0,
                       diagnostic_trace=False, policy=None):
    session = V2ContactCoreSession(request, snapshot, preview, use_planner,
                                   use_filter_sqp, perf_counter())
    session.diagnostic_trace = bool(diagnostic_trace)
    session.policy = policy or V2ContactPolicy()
    _initialize_contact_session(session)
    if session.state is not None: session.state.owner_span_override = float(owner_span_override)
    return session


def _initialize_contact_session(session):
    status = collision_backend_status(); request = session.request
    if not status.available:
        _fail_contact_session(session, V2Termination.BACKEND_UNAVAILABLE, status.message); return
    issue = _configuration_issue(request)
    if issue:
        _fail_contact_session(session, V2Termination.INVALID_CONFIGURATION, issue); return
    session.state = _prime_state(request, session.use_filter_sqp,
        session.diagnostic_trace, session.policy); session.phase = "WORLD"


def _advance_contact_session(session):
    if session.done: return session.package
    if session.phase != "SOLVE":
        _advance_contact_initialization(session); return session.package
    outcome = _iteration(session.state)
    if outcome is not False: session.trials += 1
    if isinstance(outcome, tuple): _finish_contact_session(session, *outcome)
    elif _contact_budget_done(session):
        _finish_contact_session(session, V2Termination.BUDGET_EXHAUSTED, "accepted-step cap exhausted")
    return session.package


def _advance_contact_initialization(session):
    actions = {"WORLD": _prepare_world, "SNAPSHOT": _prepare_snapshot,
               "PLAN": _prepare_planner, "SEED": _prepare_seed}
    action = actions.get(session.phase)
    if action is None: _fail_contact_session(session, V2Termination.UNSAFE_OUTPUT, "invalid core phase")
    else: action(session)


def _contact_budget_done(session):
    cap = session.request.settings.max_accepted_steps
    return session.state.accepted >= cap or session.trials >= max(32, 8 * cap)


def _finish_contact_session(session, termination, message):
    session.package = _finish(session.state, termination, message, session.started)
    session.done = True


def _fail_contact_session(session, termination, message):
    session.package = _failed_package(session.request, termination, message, session.started)
    session.done = True


def _configuration_issue(request):
    if request.settings.topology is not V2Topology.OPEN:
        return "production V2 contact core currently supports open Fibers"
    if len(request.anchors) < 2:
        return "open Fiber requires at least two authored anchors"
    if request.settings.node_count < len(request.anchors):
        return "authored anchors cannot fit requested node count"
    return ""


def _prime_state(request, filter_sqp=False, diagnostic=False, policy=None):
    q, indices = _direct_reference(request); pins = _pin_targets(request, indices)
    metrics = V2FeasibilityState(float("inf"), float("inf"), 0, 0.0, False)
    state = _ContactState(request, None, None, _planner_unavailable("pending"),
        q, q.copy(), indices, pins, {}, (), _initial_penalty(request), metrics, True,
        filter_sqp_enabled=bool(filter_sqp), diagnostic_enabled=bool(diagnostic),
        policy=policy or V2ContactPolicy())
    state.mu = _initial_penalty(request, _effective_settings(state))
    _initialize_lists(state); _initialize_controller(state)
    return state


def _prepare_world(session):
    session.state.world = cached_native_collision_world_batch(session.request.colliders)
    session.phase = "SNAPSHOT"


def _prepare_snapshot(session):
    state = session.state; state.snapshot = session.snapshot or build_triangle_snapshot_known(
        session.request.colliders, state.world.closed_flags)
    session.phase = "PLAN"


def _prepare_planner(session):
    state = session.state
    state.planner = _optional_planner(session.request, state.snapshot, state.world, session.use_planner)
    session.seed_candidates = _seed_candidates(state)
    session.phase = "SEED"


def _prepare_seed(session):
    state = session.state; seed = session.seed_candidates[session.seed_index]
    record = _measure_seed(state, seed, session.seed_index)
    if session.seed_best is None or record[0] < session.seed_best[0]: session.seed_best = record
    session.seed_index += 1
    if not record[3].feasible and session.seed_index < len(session.seed_candidates): return
    _adopt_seed(state, session.seed_best)
    issue = _pin_issue(state)
    if issue: _finish_contact_session(session, V2Termination.INVALID_CONFIGURATION, issue); return
    state.started_invalid = not state.metrics.feasible; session.phase = "SOLVE"


def _initialize_lists(state):
    state.feasibility_history, state.multiplier_history = [], []
    state.condition_history, state.energy_history = [], []
    state.group_sides, state.limiting_history = {}, []
    state.fixed_history, state.stationarity_history = [], []
    state.trust_history = []
    state.rejection_reasons = []
    state.ccd_step_history = []
    state.model_ratio_history, state.normal_step_history = [], []
    state.tangent_step_history = []
    state.regularization_history = []
    state.diagnostic_events = [] if state.diagnostic_enabled else None


def _initialize_controller(state):
    radius = _radius(state); scale = state.request.tolerances.length_scale
    state.trust_radius = max(8.0 * radius, .01 * scale)
    state.min_trust = max(.25 * radius, state.request.tolerances.numeric_floor)
    state.max_trust = max(state.trust_radius, .25 * scale)
    _initialize_regularization(state)


def _initialize_regularization(state):
    ratio = max(0.0, float(getattr(state.policy, "sqp_regularization_ratio", 0.0)))
    if _policy_enabled(state, "adaptive_regularized_sqp") and ratio <= 0.0: ratio = 1.0e-6
    diagonal = objective_diagonal(state.points, _effective_settings(state),
                                  _true_length_epsilon(state), _spacing_weight(state))
    state.regularization_scale = max(float(np.median(diagonal)), state.request.tolerances.numeric_floor)
    state.sqp_regularization = ratio * state.regularization_scale
    state.regularization_history.append(state.sqp_regularization)


def _update_regularization(state, ratio, accepted, contact_changed=False):
    if not _policy_enabled(state, "adaptive_regularized_sqp"): return
    factor = _regularization_factor(state, ratio, accepted, contact_changed)
    low, high = 1.0e-10 * state.regularization_scale, 1.0e2 * state.regularization_scale
    value = min(high, max(low, factor * state.sqp_regularization))
    state.regularization_increases += int(value > state.sqp_regularization)
    state.regularization_decreases += int(value < state.sqp_regularization)
    state.sqp_regularization = value; state.regularization_history.append(value)


def _regularization_factor(state, ratio, accepted, contact_changed):
    if not accepted: return 4.0 if not contact_changed else 2.0
    if np.isfinite(ratio) and ratio > .75: return .5
    if not np.isfinite(ratio) or ratio < .25: return 2.0
    return 2.0 if _regularization_condition(state) > 1.0e12 else 1.0


def _regularization_condition(state):
    step = state.pending_sqp
    return state.condition if step is None else float(step.structural_condition)


def _optional_planner(request, snapshot, world, enabled):
    if not enabled:
        return _planner_unavailable("planner disabled for solver qualification")
    return plan_reference_v43(request, snapshot, native_world=world)


def _planner_unavailable(message):
    diagnostics = V2PlannerDiagnostics()
    return V2PlannerResult(V2Termination.NO_FEASIBLE_PATH, V2PlannerMode.DIRECT,
                           diagnostics=diagnostics, message=message)


def _direct_reference(request):
    anchors = np.asarray([row.point for row in request.anchors], dtype=np.float64)
    counts = _span_counts(anchors, request.settings.node_count - 1)
    rows, indices = [anchors[0]], [0]
    for first, (start, end) in enumerate(zip(anchors[:-1], anchors[1:])):
        rows.extend(start + (end - start) * (step / counts[first]) for step in range(1, counts[first] + 1))
        indices.append(len(rows) - 1)
    return np.ascontiguousarray(rows), tuple(indices)


def _span_counts(anchors, edge_budget):
    spans = len(anchors) - 1; counts = np.ones(spans, dtype=np.int64)
    remaining = int(edge_budget) - spans
    if remaining <= 0:
        return counts
    lengths = np.linalg.norm(np.diff(anchors, axis=0), axis=1)
    weights = lengths / float(lengths.sum()) if float(lengths.sum()) > 1.0e-12 else np.full(spans, 1.0 / spans)
    raw = remaining * weights
    counts += np.floor(raw).astype(np.int64); left = remaining - int(np.floor(raw).sum())
    counts[np.argsort(-(raw - np.floor(raw)), kind="stable")[:left]] += 1
    return counts


def _pin_targets(request, indices):
    return {int(index): np.asarray(anchor.point, dtype=np.float64)
            for index, anchor in zip(indices, request.anchors)}


def _measure_seed(state, seed, order):
    _restore_pins(seed, state.pins); fresh, metrics = _measure(state, seed)
    score = (not metrics.feasible, metrics.maximum_violation, metrics.squared_violation, order)
    return score, seed, fresh, metrics, state.groups, dict(state.group_sides)


def _adopt_seed(state, record):
    state.points = np.ascontiguousarray(record[1]); state.groups = record[4]
    state.group_sides = record[5]; state.contacts = {row.key: row for row in record[2]}
    state.metrics = record[3]; state.injected += len(state.contacts)
    state.feasibility_history.append((state.metrics.maximum_violation, state.metrics.squared_violation))
    _trace_event(state, "SEED", decision="SELECTED")


def _seed_candidates(state):
    rows = []
    if state.planner.succeeded and len(state.planner.reference) >= len(state.request.anchors):
        rows.append(_planner_seed(state.planner, state.pin_indices, len(state.q)))
    if len(state.request.warm_seed) == len(state.q):
        rows.append(np.asarray(state.request.warm_seed, dtype=np.float64).copy())
    rows.append(state.q.copy()); return tuple(rows)


def _planner_seed(planner, indices, count):
    source = np.asarray(planner.reference, dtype=np.float64); rows = []
    source_pins = tuple(planner.pin_indices)
    if len(source_pins) != len(indices):
        return _resample(source, count)
    for span, (first, last) in enumerate(zip(indices[:-1], indices[1:])):
        part = _resample(source[source_pins[span]:source_pins[span + 1] + 1], last - first + 1)
        rows.extend(part if not rows else part[1:])
    return np.ascontiguousarray(rows)


def _resample(points, count):
    values = np.asarray(points, dtype=np.float64)
    if len(values) == count:
        return values.copy()
    lengths = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(values, axis=0), axis=1))]
    targets = np.linspace(0.0, float(lengths[-1]), int(count)); rows = []
    for target in targets:
        edge = min(max(0, int(np.searchsorted(lengths, target, side="right") - 1)), len(values) - 2)
        scale = (target - lengths[edge]) / max(lengths[edge + 1] - lengths[edge], 1.0e-12)
        rows.append(values[edge] + scale * (values[edge + 1] - values[edge]))
    return np.ascontiguousarray(rows)


def _initial_penalty(request, settings=None):
    settings = request.settings if settings is None else settings
    diagonal = _base_bands(settings.node_count, _static_settings(settings))[0]
    return max(float(np.median(diagonal)), 1.0)


def _pin_issue(state):
    points = np.asarray([state.pins[index] for index in state.pin_indices])
    edges = tuple((index, index) for index in range(len(points)))
    owners = tuple((row.owner_id, row.owner_id) for row in state.request.anchors)
    threshold = _validation_threshold(state); started = perf_counter()
    result = state.world.validate(points, edges, owners, _owner_span(state), threshold)
    state.validation_ms += _elapsed(started)
    for index, clear in enumerate(result.clear):
        if not clear:
            return f"authored anchor {index} intersects unrelated collider {result.blockers[index]}"
    return ""


def _iteration(state):
    if state.pending_sweep is not None: return _advance_feasible_sweep(state)
    _adapt_quality(state)
    candidate = _solve_candidate(state)
    if state.metrics.feasible:
        _begin_feasible_sweep(state, candidate); return _advance_feasible_sweep(state)
    accepted = _accept_infeasible_candidate(state, candidate)
    return _complete_trial(state, accepted)


def _complete_trial(state, accepted):
    if accepted and _converged(state):
        return V2Termination.CONVERGED, "augmented-contact fixed point converged"
    state.stalled = 0 if accepted else state.stalled + 1
    if not accepted and not state.metrics.feasible and not state.filter_sqp_enabled:
        _update_multipliers(state)
    if state.stalled >= 8 and not state.metrics.feasible and state.regroupings < 3:
        _regroup(state); return None
    if state.stalled >= 8:
        reason = V2Termination.STALLED if state.metrics.feasible else V2Termination.NO_FEASIBLE_PATH
        return reason, "contact-constrained solve made no filter progress"
    if not state.filter_sqp_enabled: _adapt_penalty(state)
    return None


def _regroup(state):
    state.regroupings += 1; state.stalled = 0; state.contacts = {}; state.group_sides = {}
    state.mu = _initial_penalty(state.request, _effective_settings(state))
    _refresh_state(state)


def _solve_candidate(state):
    if state.filter_sqp_enabled: return _solve_sqp_candidate(state)
    bands = _base_bands(len(state.q), _static_settings(state.request.settings))
    rhs = state.request.settings.fidelity_weight * state.q
    rows = tuple(_native_contact_row(row) for row in state.contacts.values())
    pins = tuple(state.pins); targets = tuple(state.pins[index] for index in pins)
    candidate, trace = native_contact_block_solve(bands, rhs, state.points, rows, pins,
                                                   targets, state.mu)
    state.assembly_ms += trace["assembly_ms"]; state.factor_ms += trace["factor_ms"]
    state.solve_ms += trace["solve_ms"]; state.condition = trace["condition"]
    state.condition_history.append(state.condition); return candidate


def _solve_sqp_candidate(state):
    arguments = (state.points, state.q, _effective_settings(state),
                  tuple(state.contacts.values()), state.pins, state.trust_radius)
    epsilon, spacing = _true_length_epsilon(state), _spacing_weight(state)
    step = solve_trust_sqp(*arguments, epsilon, spacing, state.sqp_regularization)
    state.pending_sqp = step; state.sqp_solve_ms += step.solve_ms
    state.condition = step.condition; state.condition_history.append(step.condition)
    state.normal_step_history.append(step.normal_norm)
    state.tangent_step_history.append(step.tangential_norm)
    _trace_sqp_proposal(state, step)
    return step.points


def _native_contact_row(contact):
    gap = contact.linearized_gap if np.isfinite(contact.linearized_gap) else contact.gap
    return contact.edge, contact.factor, contact.normal, gap, contact.multiplier


def _accept_infeasible_candidate(state, candidate):
    if not np.isfinite(candidate).all():
        state.rejected += 1; return False
    state.feasibility_iterations += 1
    if state.filter_sqp_enabled: return _accept_sqp_infeasible(state, candidate)
    trials = _infeasible_trials(state, candidate)
    if trials:
        _score, proposed, fresh, metrics = min(trials, key=lambda row: row[0])
        _adopt(state, proposed, fresh, metrics); return True
    state.rejected += 1; return False


def _accept_sqp_infeasible(state, candidate):
    fresh, metrics = _measure(state, candidate); accepted = _filter_improves(state.metrics, metrics)
    ratio = _sqp_ratio(state, candidate, metrics); _update_sqp_controller(state, ratio, accepted)
    _trace_trial(state, candidate, fresh, metrics, ratio)
    if accepted:
        movement = _accepted_movement(state, candidate)
        _adopt(state, candidate, fresh, metrics)
        _trace_event(state, "DECISION", decision="ACCEPT_INFEASIBLE", extra={"accepted_step_norms": movement})
    else:
        state.rejected += 1; _trace_event(state, "DECISION", decision="REJECT:FILTER")
    return accepted


def _infeasible_trials(state, candidate):
    output = []
    for fraction in _filter_fractions():
        proposed = state.points + fraction * (candidate - state.points); _restore_pins(proposed, state.pins)
        fresh, metrics = _measure(state, proposed)
        if _filter_improves(state.metrics, metrics):
            score = (metrics.maximum_violation, metrics.squared_violation, _structural_merit(state, proposed))
            output.append((score, proposed, fresh, metrics))
    return output


def _filter_fractions():
    return tuple(2.0 ** -power for power in range(13))


def _structural_merit(state, points):
    return _objective(state, points).total


def _begin_feasible_sweep(state, candidate):
    started = perf_counter()
    state.pending_candidate = _trusted_candidate(state, candidate)
    contacts = _motion_contacts(state, state.points, state.pending_candidate)
    state.pending_sweep = begin_collision_free_step(
        state.points, state.pending_candidate, state.snapshot, _radius(state), contacts,
        slack=_slack(state), assume_initial_valid=True)
    state.pending_sweep._started = started


def _advance_feasible_sweep(state):
    step = state.pending_sweep.step()
    if step is None: return False
    started = state.pending_sweep._started; candidate = state.pending_candidate
    state.pending_sweep = None; state.pending_candidate = None
    _record_ccd(state, step, started, candidate)
    accepted = _accept_feasible_step(state, candidate, step)
    if isinstance(accepted, tuple): return accepted
    return _complete_trial(state, accepted)


def _accept_feasible_step(state, candidate, step):
    limiting = _limiting_outcome(state, candidate, step)
    if limiting is not None: return limiting
    if not step.valid or step.safe_step <= state.request.tolerances.numeric_floor:
        reason = f"{step.reason.value}:{tuple(step.limiting_pairs)}"
        _refresh_state(state); return _reject_feasible(state, reason)
    proposed, fresh, metrics = _feasible_trial(state, candidate, step)
    if not metrics.feasible:
        _trace_trial(state, proposed, fresh, metrics, None)
        reason = f"INFEASIBLE:{metrics.maximum_violation:.9g}:{metrics.penetrating_groups}"
        return _reject_feasible(state, reason)
    ratio = _sqp_ratio(state, proposed, metrics) if state.filter_sqp_enabled else 1.0
    _trace_trial(state, proposed, fresh, metrics, ratio)
    if state.filter_sqp_enabled and ratio < .1:
        return _model_rejection(state, ratio)
    return _commit_feasible_candidate(state, proposed, fresh, metrics, step, ratio)


def _limiting_outcome(state, candidate, step):
    if not step.limiting_pairs or step.safe_step >= 1.0: return None
    injected = _inject_limiting(state, candidate, step)
    if injected: return _reject_feasible(state, "INJECT_LIMITING", True)
    return None


def _feasible_trial(state, candidate, step):
    fraction = 1.0 if step.safe_step >= 1.0 else .999 * step.safe_step
    proposed = state.points + fraction * (candidate - state.points)
    _restore_pins(proposed, state.pins); fresh, metrics = _measure(state, proposed)
    return proposed, fresh, metrics


def _commit_feasible_candidate(state, proposed, fresh, metrics, step, ratio):
    movement = _accepted_movement(state, proposed); state.injection_streak = 0
    if state.filter_sqp_enabled: _accept_controller(state, step, ratio)
    _adopt(state, proposed, fresh, metrics)
    if not state.filter_sqp_enabled: _accept_controller(state, step, ratio)
    _trace_event(state, "DECISION", decision="ACCEPT", extra={"accepted_step_norms": movement})
    return True


def _model_rejection(state, ratio):
    reason = f"MODEL_RATIO:{ratio:.6g}"
    if _stationary_rejection(state, reason):
        _trace_event(state, "DECISION", decision="CONVERGED_STATIONARY")
        return V2Termination.CONVERGED, "SQP stationary after repeated nondecreasing trials"
    return _reject_feasible(state, reason)


def _stationary_rejection(state, reason):
    tolerance = state.request.tolerances
    if not str(reason).startswith("MODEL_RATIO:") or state.stalled < 2: return False
    if any(row.feature_id == "LIMITING" for row in state.contacts.values()): return False
    return bool(state.metrics.feasible and
                state.fixed_residual <= tolerance.fixed_point_tolerance and
                state.stationarity <= tolerance.stationarity_tolerance)


def _reject_feasible(state, reason, contact_changed=False):
    state.rejected += 1
    state.rejection_reasons.append(str(reason))
    _trace_event(state, "DECISION", decision=f"REJECT:{reason}")
    repeated = _repeated_injection(state) if contact_changed else False
    if contact_changed and not repeated: state.stalled = -1
    if state.filter_sqp_enabled:
        _update_sqp_controller(state, float("-inf"), False, contact_changed and not repeated)
    return False


def _repeated_injection(state):
    state.injection_streak += 1
    if state.injection_streak < 3: return False
    state.injection_streak = 0; return True


def _accept_controller(state, step, ratio=1.0):
    if state.filter_sqp_enabled:
        _update_sqp_controller(state, ratio, True)


def _sqp_ratio(state, candidate, metrics, contacts=None):
    contacts = tuple(state.contacts.values()) if contacts is None else tuple(contacts)
    feasible = state.metrics.feasible
    predicted = model_reduction(state.points, candidate, state.q, _effective_settings(state),
        contacts, state.pins, feasible, _true_length_epsilon(state), _spacing_weight(state),
        state.sqp_regularization)
    before = _structural_merit(state, state.points); after = _structural_merit(state, candidate)
    actual = actual_reduction(state.metrics, metrics, before, after, feasible)
    floor = max(state.request.tolerances.numeric_floor ** 2, 1.0e-16)
    if predicted <= floor: return 1.0 if actual >= -floor else float("-inf")
    return float(actual / predicted)


def _update_sqp_controller(state, ratio, accepted, contact_changed=False):
    _update_regularization(state, ratio, accepted, contact_changed)
    boundary = _at_trust_boundary(state)
    state.trust_radius = update_trust_radius(state.trust_radius, state.min_trust,
    state.max_trust, ratio, accepted, boundary, contact_changed)
    state.model_ratio_history.append(float(ratio)); state.trust_history.append(state.trust_radius)
    if not accepted: state.pending_sqp = None


def _at_trust_boundary(state):
    if state.pending_sqp is None: return False
    delta = np.asarray(state.pending_sqp.points) - state.points
    maximum = max((float(value) for value in np.linalg.norm(delta, axis=1)), default=0.0)
    return maximum >= .8 * state.trust_radius


def _record_ccd(state, step, started, candidate=None):
    state.ccd_ms += _elapsed(started); state.limiting += len(step.limiting_pairs)
    state.ccd_candidates += step.candidate_pairs; state.ccd_tested += step.tested_pairs
    state.limiting_history.append(tuple(step.limiting_pairs))
    state.ccd_step_history.append((step.safe_step, step.reason.value, step.initially_valid))
    _trace_ccd(state, step, candidate)


def _trusted_candidate(state, candidate):
    delta = np.asarray(candidate) - state.points
    maximum = max((float(value) for value in np.linalg.norm(delta, axis=1)), default=0.0)
    trust = state.trust_radius if state.filter_sqp_enabled else max(
        8.0 * _radius(state), .01 * state.request.tolerances.length_scale)
    fraction = min(1.0, trust / max(maximum, state.request.tolerances.numeric_floor))
    return state.points + fraction * delta


def _inject_limiting(state, candidate, step):
    injected = False
    for contact in _limiting_rows(state, state.points, candidate, step):
        prior = state.contacts.get(contact.key); existing = prior is not None
        if prior is not None: contact = replace(contact, multiplier=prior.multiplier, age=prior.age + 1)
        state.contacts[contact.key] = contact
        if not existing: state.injected += 1
        injected |= prior is None or _limiter_changed(state, prior, contact)
    return injected


def _limiting_rows(state, source, target, step):
    impact = source + step.safe_step * (target - source)
    batch = state.world.contact_pairs(impact, _edges(len(impact)), _edge_owners(state, impact),
                                      _owner_span(state, impact), 2.0 * _activation(state))
    pairs = (_limiting_pair(state, batch.pairs, key) for key in step.limiting_pairs)
    rows = tuple(_limiting_contact(state, source, pair) for pair in pairs if pair is not None)
    return rows


def _limiting_contact(state, source, pair):
    contact = _contact_from_pair(state, source, pair); plane = float(np.dot(pair.normal, pair.closest) + _radius(state))
    sample = source[pair.edge] + pair.factor * (source[pair.edge + 1] - source[pair.edge])
    gap = float(np.dot(sample, pair.normal) - plane)
    return replace(contact, feature_id="LIMITING", gap=gap, linearized_gap=gap,
                   normal=tuple(pair.normal))


def _limiting_pair(state, pairs, key):
    edge, face = map(int, key); collider, local = _face_identity(state.snapshot, face)
    exact = [row for row in pairs if row.edge == edge and row.collider_id == collider and row.face == local]
    fallback = [row for row in pairs if row.edge == edge and row.collider_id == collider]
    return min(exact or fallback, key=lambda row: row.distance, default=None)


def _face_identity(snapshot, face):
    for row in snapshot.collider_ranges:
        if int(row[4]) <= face < int(row[4]) + int(row[5]):
            return str(row[0]), face - int(row[4])
    return "", -1


def _limiter_changed(state, prior, contact):
    if prior.triangle_id != contact.triangle_id: return True
    if np.dot(prior.normal, contact.normal) < 1.0 - 1.0e-6: return True
    if abs(prior.factor - contact.factor) > 1.0e-6: return True
    return abs(prior.linearized_gap - contact.linearized_gap) > _slack(state)


def _filter_improves(before, after):
    if _new_unrelated(before.penetrating_groups, after.penetrating_groups):
        return False
    slack = max(1.0e-12, 1.0e-6 * max(1.0, before.maximum_violation))
    if after.maximum_violation < before.maximum_violation - slack:
        return True
    level = abs(after.maximum_violation - before.maximum_violation) <= slack
    return level and after.squared_violation < before.squared_violation - slack * slack


def _new_unrelated(before, after):
    prior = tuple(before)
    return any(not any(old[1] == row[1] and abs(old[0] - row[0]) <= 1 for old in prior)
               for row in after)


def _measure(state, points):
    fresh = _query_contacts(state, points)
    validation = _validate_points(state, points)
    violations = np.asarray([max(0.0, -row.gap) for row in fresh], dtype=np.float64)
    maximum = max(float(violations.max()) if len(violations) else 0.0,
                  max(0.0, _validation_threshold(state) - validation.minimum))
    groups = tuple(sorted({(row.edge, row.collider_id) for row in fresh if row.gap < -_slack(state)}))
    pin = _pin_residual(points, state.pins)
    feasible = bool(all(validation.clear) and maximum <= _slack(state) and pin <= state.request.tolerances.pin_tolerance)
    return fresh, V2FeasibilityState(maximum, float(violations @ violations), 0, pin, feasible, groups)


def _validate_points(state, points):
    started = perf_counter(); edges = _edges(len(points)); owners = _edge_owners(state, points)
    result = state.world.validate(points, edges, owners, _owner_span(state, points), _validation_threshold(state))
    state.validation_ms += _elapsed(started); return result


def _query_contacts(state, points):
    started = perf_counter(); edges = _edges(len(points)); owners = _edge_owners(state, points)
    batch = state.world.contact_pairs(points, edges, owners, _owner_span(state, points), _activation(state))
    fresh = tuple(_contact_from_pair(state, points, row) for row in batch.pairs)
    if state.filter_sqp_enabled: fresh = _collapse_contacts(state, fresh)
    fresh = _coherent_contacts(state, points, fresh)
    state.contact_ms += _elapsed(started); return fresh


def _collapse_contacts(state, contacts):
    output = []
    for row in sorted(contacts, key=lambda value: value.key):
        index = _duplicate_contact(state, output, row)
        if index < 0: output.append(row); continue
        prior = output[index]
        output[index] = replace(prior, multiplier=max(prior.multiplier, row.multiplier))
    return tuple(output)


def _duplicate_contact(state, contacts, row):
    for index, prior in enumerate(contacts):
        if _same_contact_geometry(state, prior, row): return index
    return -1


def _same_contact_geometry(state, first, second):
    if (first.edge, first.collider_id, first.feature_id) != (second.edge, second.collider_id, second.feature_id): return False
    if abs(first.factor - second.factor) > 1.0e-6: return False
    if abs(first.gap - second.gap) > _slack(state): return False
    return bool(np.dot(first.normal, second.normal) >= 1.0 - 1.0e-6)


def _contact_from_pair(state, points, pair):
    distance = float(pair.distance); gap = -(distance + _radius(state)) if pair.contained else distance - _radius(state)
    feature = "CONTAINMENT" if pair.contained else "CROSSING" if distance <= _slack(state) else "DISTANCE"
    key = pair.edge, pair.collider_id, pair.face, feature
    prior = state.contacts.get(key)
    multiplier = 0.0 if prior is None else prior.multiplier
    age = 0 if prior is None else prior.age + 1
    return V2Contact(pair.edge, pair.factor, pair.collider_id, pair.face, feature,
                     tuple(pair.normal), gap, multiplier=multiplier, age=age)


def _coherent_contacts(state, points, contacts):
    groups = _contact_groups(contacts); output = list(contacts); records = []
    for number, indices in enumerate(groups):
        group = _group_record(state, points, output, indices, number); records.append(group)
        for index in indices:
            row = output[index]; normal = _group_normal(row, group.selected_side)
            model_gap = _group_model_gap(row, group)
            output[index] = replace(row, normal=normal, linearized_gap=model_gap, group=number)
    state.groups = tuple(records); return tuple(output)


def _contact_groups(contacts):
    order = sorted(range(len(contacts)), key=lambda index: (contacts[index].collider_id, contacts[index].edge))
    groups = []
    for index in order:
        row = contacts[index]
        if not groups or contacts[groups[-1][-1]].collider_id != row.collider_id or row.edge > contacts[groups[-1][-1]].edge + 1:
            groups.append([])
        groups[-1].append(index)
    return tuple(tuple(row) for row in groups)


def _group_record(state, points, contacts, indices, number):
    rows = [contacts[index] for index in indices]; first = min(row.edge for row in rows)
    last = max(row.edge for row in rows); key = rows[0].collider_id, _routing_span(state, first, last)
    candidates = _escape_candidates(state, points, rows, first, last)
    side = state.group_sides.get(key); distance = 0.0
    side, distance = _existing_escape(state, points, rows, first, last, side)
    if not side: side, distance = _select_escape(state, points, rows, first, last, candidates)
    if side:
        state.group_sides[key] = side
    return V2ContactGroup(number, first, last, rows[0].collider_id,
                          tuple(tuple(row) for row in candidates), tuple(side), distance)


def _routing_span(state, first, last):
    middle = (int(first) + int(last) + 1) // 2
    for index, (low, high) in enumerate(zip(state.pin_indices[:-1], state.pin_indices[1:])):
        if low <= middle <= high:
            return index
    return -1


def _escape_candidates(state, points, contacts, first, last):
    hint = np.mean(points[first:last + 2] - state.q[first:last + 2], axis=0)
    normals = np.asarray([row.normal for row in contacts], dtype=np.float64)
    covariance = normals.T @ normals; _values, vectors = np.linalg.eigh(covariance)
    rows = []
    if np.linalg.norm(hint) > 1.0e-12:
        rows.append(_unit(hint))
    rows.append(_unit(min(contacts, key=lambda row: row.gap).normal))
    for vector in vectors.T:
        rows.extend((_unit(vector), -_unit(vector)))
    return tuple(_unique_directions(rows)[:6])


def _unique_directions(rows):
    output = []
    for row in rows:
        if np.linalg.norm(row) and not any(float(np.dot(row, old)) > 1.0 - 1.0e-8 for old in output):
            output.append(row)
    return output


def _existing_escape(state, points, contacts, first, last, side):
    if not side or not any(row.feature_id != "DISTANCE" for row in contacts):
        return (), 0.0
    row = _escape_trial(state, points, first, last, np.asarray(side), _raw_violation(contacts), 0)
    return (row[1], row[2]) if row is not None else (tuple(side), _activation(state))


def _select_escape(state, points, contacts, first, last, candidates):
    ambiguous = any(row.feature_id != "DISTANCE" for row in contacts)
    if not ambiguous or not candidates:
        return (), 0.0
    base = _raw_violation(contacts); scored = []
    for order, direction in enumerate(candidates):
        row = _escape_trial(state, points, first, last, direction, base, order)
        if row is not None: scored.append(row)
    if not scored: return (), 0.0
    best = min(scored); return best[1], best[2]


def _escape_trial(state, points, first, last, direction, base, order):
    movable = [index for index in range(first, last + 2) if index not in state.pins]
    scored = []
    for distance in _escape_distances(state):
        proposed = points.copy(); proposed[movable] += distance * direction
        violation = _raw_violation(_query_raw(state, proposed))
        if violation < base:
            merit = _objective(state, proposed).total
            scored.append(((*violation, merit, order, distance), tuple(direction), distance))
        if violation[0] <= _slack(state): break
    return min(scored) if scored else None


def _escape_distances(state):
    start = max(_activation(state), state.request.tolerances.numeric_floor)
    limit = max(start, .25 * state.request.tolerances.length_scale)
    values = [min(limit, start * (2.0 ** power)) for power in range(12)]
    return tuple(dict.fromkeys(values))


def _query_raw(state, points):
    edges = _edges(len(points)); owners = _edge_owners(state, points)
    batch = state.world.contact_pairs(points, edges, owners, _owner_span(state, points), _activation(state))
    return tuple(_contact_from_pair(state, points, row) for row in batch.pairs)


def _raw_violation(contacts):
    values = [max(0.0, -row.gap) for row in contacts]
    return max(values, default=0.0), float(np.dot(values, values))


def _group_normal(contact, side):
    if not side or contact.gap >= 0.0:
        return tuple(_unit(contact.normal))
    return tuple(_unit(side))


def _group_model_gap(contact, group):
    if not group.selected_side or contact.gap >= 0.0:
        return float("nan")
    return min(contact.gap, -float(group.escape_distance))


def _refresh_state(state):
    fresh, metrics = _measure(state, state.points)
    state.contacts = _merge_contacts(state, fresh); state.metrics = metrics
    state.feasibility_history.append((metrics.maximum_violation, metrics.squared_violation))


def _merge_contacts(state, fresh):
    current = state.contacts; output = {row.key: row for row in fresh}
    migrated = _migrate_limiters(current, output)
    state.injected += sum(key not in current for key in output)
    clear_gap = _activation(state) - _radius(state)
    for key, row in current.items():
        if key in output or key in migrated: continue
        if row.feature_id == "LIMITING": _retire_limiter(state); continue
        retained = _retained_contact(state, row, clear_gap)
        if retained is None: state.retired += 1
        else: output[key] = retained
    return output


def _retire_limiter(state):
    state.retired += 1; state.energy_streak = 0


def _retained_contact(state, row, clear_gap):
    multiplier = max(0.0, row.multiplier - state.mu * clear_gap)
    streak = row.clear_streak + 1
    if streak >= 2 and multiplier <= state.mu * _slack(state): return None
    return replace(row, gap=clear_gap, linearized_gap=float("nan"),
                   multiplier=multiplier, clear_streak=streak)
def _migrate_limiters(current, output):
    migrated = set()
    for key, prior in current.items():
        if prior.feature_id != "LIMITING": continue
        rows = [row for row in output.values() if _same_contact_span(prior, row)]
        if not rows: continue
        fresh = min(rows, key=lambda row: abs(row.factor - prior.factor))
        output[fresh.key] = replace(fresh, multiplier=max(fresh.multiplier, prior.multiplier))
        migrated.add(key)
    return migrated


def _same_contact_span(first, second):
    return first.edge == second.edge and first.collider_id == second.collider_id


def _adopt(state, points, fresh, metrics):
    previous = state.points.copy(); old_energy = _energy(state, previous); pending = state.pending_sqp
    state.points = np.ascontiguousarray(points); state.contacts = _merge_contacts(state, fresh)
    if state.filter_sqp_enabled: _apply_sqp_multipliers(state)
    else: _update_multipliers(state)
    state.metrics = metrics; state.accepted += 1
    scale = state.request.tolerances.length_scale
    state.fixed_residual = float(np.max(np.linalg.norm(state.points - previous, axis=1)) / scale)
    state.stationarity = _stationarity(state); _update_energy_streak(state, old_energy)
    state.fixed_history.append(state.fixed_residual); state.stationarity_history.append(state.stationarity)
    state.feasibility_history.append((metrics.maximum_violation, metrics.squared_violation))


def _apply_sqp_multipliers(state):
    step = state.pending_sqp; duals = {} if step is None else dict(zip(step.active_keys, step.multipliers))
    state.contacts = {key: replace(row, multiplier=max(0.0, duals.get(key, 0.0)))
                      for key, row in state.contacts.items()}
    state.multiplier_updates += 1
    state.multiplier_history.append(max(duals.values(), default=0.0))
    state.pending_sqp = None
def _update_multipliers(state):
    updated = {}
    for key, row in state.contacts.items():
        value = max(0.0, row.multiplier - state.mu * row.gap)
        updated[key] = replace(row, multiplier=value)
    state.contacts = updated; state.multiplier_updates += 1
    maximum = max((row.multiplier for row in updated.values()), default=0.0)
    state.multiplier_history.append(maximum)


def _update_energy_streak(state, old):
    current = _energy(state, state.points); relative = abs(current - old) / max(1.0, abs(old))
    state.energy_streak = state.energy_streak + 1 if relative <= state.request.tolerances.relative_energy_tolerance else 0
    state.energy_history.append(current)


def _energy(state, points):
    structural = _objective(state, points).total
    contact = sum(_contact_energy(row, state.mu) for row in state.contacts.values())
    return float(structural + contact)


def _contact_energy(contact, mu):
    active = max(0.0, contact.multiplier - mu * contact.gap)
    return (active * active - contact.multiplier * contact.multiplier) / (2.0 * mu)


def _stationarity(state):
    gradient = _objective_gradient(state, state.points)
    for row in state.contacts.values():
        _add_contact_gradient(gradient, row, state.mu)
    gradient[list(state.pins)] = 0.0
    diagonal = objective_diagonal(state.points, _effective_settings(state),
                                  _true_length_epsilon(state), _spacing_weight(state))
    scale = max(1.0, float(np.median(diagonal)) * state.request.tolerances.length_scale)
    return float(np.max(np.linalg.norm(gradient, axis=1)) / scale)


def _add_contact_gradient(gradient, contact, mu):
    active = max(0.0, contact.multiplier - mu * contact.gap)
    normal = np.asarray(contact.normal); first = (1.0 - contact.factor) * normal
    second = contact.factor * normal
    gradient[contact.edge] -= active * first; gradient[contact.edge + 1] -= active * second


def _converged(state):
    tolerance = state.request.tolerances
    return bool(state.metrics.feasible and state.fixed_residual <= tolerance.fixed_point_tolerance and
                state.stationarity <= tolerance.stationarity_tolerance and state.energy_streak >= 3)


def _adapt_penalty(state):
    if len(state.feasibility_history) < 4 or state.metrics.feasible:
        return
    recent = [row[0] for row in state.feasibility_history[-4:]]
    progress = recent[-1] <= .5 * recent[0]
    if not progress and state.condition < 1.0e8:
        base = _initial_penalty(state.request, _effective_settings(state))
        state.mu = min(2.0 * state.mu, 16.0 * base)


def _finish(state, termination, message, started):
    fresh, metrics = _measure(state, state.points); state.metrics = metrics
    validated = bool(metrics.feasible and np.isfinite(state.points).all())
    if not validated and termination is V2Termination.CONVERGED:
        termination, message = V2Termination.UNSAFE_OUTPUT, "final native validation invariant failed"
    _trace_event(state, "FINISH", decision=termination.value, metrics=metrics)
    diagnostics = _diagnostics(state); route = state.planner.mode.value if state.planner.succeeded else "DIRECT"
    result = V2Result(state.request.signature(), termination, tuple(map(tuple, state.points)), diagnostics,
                      validated, route, message, V2_CONTACT_CORE_VERSION,
                      collision_backend_status().version)
    return V2ContactCoreResult(result, state.planner, _core_trace(state, started))


def _core_trace(state, started):
    return V2ContactCoreTrace(_planner_ms(state.planner), _elapsed(started),
        tuple(state.feasibility_history), tuple(state.multiplier_history),
        tuple(state.condition_history), tuple(state.energy_history), tuple(state.limiting_history),
        tuple(state.fixed_history), tuple(state.stationarity_history), tuple(state.trust_history),
        tuple(state.rejection_reasons), _contact_trace(state), _stationarity_profile(state),
        tuple(state.ccd_step_history), tuple(state.model_ratio_history),
        tuple(state.normal_step_history), tuple(state.tangent_step_history), state.sqp_solve_ms,
        tuple(state.diagnostic_events or ()), tuple(map(tuple, state.q)), tuple(state.pin_indices),
        _policy_stats(state), tuple(state.regularization_history))


def _policy_stats(state):
    enabled = int(_policy_enabled(state, "true_length_irls"))
    return (("true_length_irls", enabled), ("true_length_epsilon", _true_length_epsilon(state) or 0.0),
            ("spacing_weight", _spacing_weight(state)),
            ("quality_adapted", int(state.quality_adapted)),
            ("quality_spacing", int(state.quality_spacing)),
            ("quality_trigger", state.quality_trigger),
            ("sqp_regularization", state.sqp_regularization),
            ("regularization_increases", state.regularization_increases),
            ("regularization_decreases", state.regularization_decreases))


def _trace_event(state, stage, points=None, decision="", extra=None, contacts=None, metrics=None):
    if not state.diagnostic_enabled: return
    values = state.points if points is None else np.asarray(points, dtype=np.float64)
    rows = tuple(state.contacts.values()) if contacts is None else tuple(contacts)
    record = _trace_header(state, stage, decision, metrics or state.metrics)
    record.update(_geometry_trace(state, values)); record.update(_objective_trace(state, values, rows))
    record.update(_gradient_trace(state, values, rows)); record["contacts"] = _diagnostic_contacts(state, rows)
    if extra: record.update(extra)
    state.diagnostic_events.append(record)


def _trace_sqp_proposal(state, step):
    if not state.diagnostic_enabled: return
    state.diagnostic_proposal += 1
    _trace_event(state, "PROPOSE", step.points, extra=_sqp_step_trace(step))


def _trace_ccd(state, step, candidate):
    if not state.diagnostic_enabled: return
    _trace_event(state, "CCD", candidate, extra=_ccd_step_trace(step))


def _accepted_movement(state, points):
    if not state.diagnostic_enabled: return ()
    return _scalar_rows(np.linalg.norm(points - state.points, axis=1))


def _trace_header(state, stage, decision, metrics):
    return {"proposal": state.diagnostic_proposal, "stage": str(stage), "decision": str(decision),
        "accepted": state.accepted, "rejected": state.rejected, "stalled": state.stalled,
        "trust_radius": state.trust_radius, "penalty": state.mu, "energy_streak": state.energy_streak,
        "fixed_residual": _finite_or_none(state.fixed_residual),
        "stationarity_residual": _finite_or_none(state.stationarity),
        "condition": _finite_or_none(state.condition), "feasibility": _metrics_payload(metrics),
        "active_contacts": len(state.contacts), "injected": state.injected,
        "retired": state.retired, "limiting": state.limiting, "regroupings": state.regroupings}


def _geometry_trace(state, points):
    delta = points - state.points; lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    reference = np.linalg.norm(points - state.q, axis=1)
    return {"points": _vector_rows(points), "step_norms": _scalar_rows(np.linalg.norm(delta, axis=1)),
        "segment_lengths": _scalar_rows(lengths), "turn_degrees": _scalar_rows(_turn_profile(points)),
        "reference_distances": _scalar_rows(reference), "maximum_step": float(np.max(np.linalg.norm(delta, axis=1)))}


def _turn_profile(points):
    output = np.zeros(len(points), dtype=np.float64)
    if len(points) < 3: return output
    before = points[1:-1] - points[:-2]; after = points[2:] - points[1:-1]
    scale = np.linalg.norm(before, axis=1) * np.linalg.norm(after, axis=1)
    cosine = np.divide(np.sum(before * after, axis=1), scale, out=np.ones(len(scale)), where=scale > 1.0e-20)
    output[1:-1] = np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0))); return output


def _objective_trace(state, points, contacts):
    energy = _objective(state, points)
    contact = sum(_contact_energy(row, state.mu) for row in contacts)
    return {"energy": {"fidelity": float(energy.fidelity), "length": float(energy.length),
        "curvature": float(energy.curvature), "contact": float(contact),
        "structural": float(energy.total), "total": float(energy.total + contact)}}


def _gradient_trace(state, points, contacts):
    structural = _objective_gradient(state, points)
    contact = np.zeros_like(structural)
    for row in contacts: _add_contact_gradient(contact, row, state.mu)
    total = structural + contact; total[list(state.pins)] = 0.0
    return {"gradient": {"structural": _vector_rows(structural), "contact": _vector_rows(contact),
        "total": _vector_rows(total), "structural_norms": _scalar_rows(np.linalg.norm(structural, axis=1)),
        "contact_norms": _scalar_rows(np.linalg.norm(contact, axis=1)),
        "total_norms": _scalar_rows(np.linalg.norm(total, axis=1)),
        "opposition_cosine": _scalar_rows(_opposition_profile(structural, contact))}}


def _opposition_profile(first, second):
    scale = np.linalg.norm(first, axis=1) * np.linalg.norm(second, axis=1)
    return np.divide(np.sum(first * second, axis=1), scale,
                     out=np.zeros(len(first), dtype=np.float64), where=scale > 1.0e-20)


def _diagnostic_contacts(state, contacts):
    return tuple(_diagnostic_contact(state, row) for row in contacts)


def _diagnostic_contact(state, row):
    gap = row.linearized_gap if np.isfinite(row.linearized_gap) else row.gap
    force = max(0.0, row.multiplier - state.mu * gap)
    return {"key": row.key, "edge": row.edge, "factor": row.factor,
        "collider": row.collider_id, "triangle": row.triangle_id, "feature": row.feature_id,
        "normal": tuple(map(float, row.normal)), "gap": float(row.gap),
        "linearized_gap": _finite_or_none(row.linearized_gap), "multiplier": float(row.multiplier),
        "active_force": float(force), "complementarity": float(abs(row.multiplier * row.gap)),
        "group": row.group, "age": row.age, "clear_streak": row.clear_streak}


def _trace_trial(state, points, contacts, metrics, ratio):
    if not state.diagnostic_enabled: return
    extra = {"model_ratio": _finite_or_none(ratio), "trial_feasibility": _metrics_payload(metrics)}
    _trace_event(state, "TRIAL", points, extra=extra, contacts=contacts, metrics=metrics)


def _sqp_step_trace(step):
    payload = {"predicted_violation": float(step.predicted_violation),
        "predicted_energy": float(step.predicted_energy), "normal_norm": float(step.normal_norm),
        "tangential_norm": float(step.tangential_norm), "solve_ms": float(step.solve_ms),
        "condition": _finite_or_none(step.condition), "active_keys": tuple(step.active_keys),
        "multipliers": _scalar_rows(step.multipliers),
        "regularization": float(step.regularization),
        "structural_condition": _finite_or_none(step.structural_condition),
        "constraint_condition": _finite_or_none(step.constraint_condition)}
    return {"sqp": payload}


def _ccd_step_trace(step):
    return {"ccd": {"safe_step": float(step.safe_step), "valid": bool(step.valid),
        "initially_valid": bool(step.initially_valid), "reason": step.reason.value,
        "limiting_pairs": tuple(step.limiting_pairs), "candidate_pairs": int(step.candidate_pairs),
        "tested_pairs": int(step.tested_pairs), "intervals": int(step.intervals)}}


def _metrics_payload(metrics):
    return {"feasible": bool(metrics.feasible), "maximum_violation": float(metrics.maximum_violation),
        "squared_violation": float(metrics.squared_violation),
        "new_collision_count": int(metrics.new_collision_count), "pin_residual": float(metrics.pin_residual),
        "penetrating_groups": tuple(metrics.penetrating_groups)}


def _vector_rows(values):
    return tuple(tuple(map(float, row)) for row in np.asarray(values, dtype=np.float64))


def _scalar_rows(values):
    return tuple(map(float, np.asarray(values, dtype=np.float64)))


def _finite_or_none(value):
    if value is None: return None
    return float(value) if np.isfinite(value) else None


def _contact_trace(state):
    return tuple((row.key, row.gap, row.linearized_gap, row.multiplier, row.factor, row.normal)
                 for row in state.contacts.values())


def _stationarity_profile(state):
    gradient = _objective_gradient(state, state.points)
    for row in state.contacts.values(): _add_contact_gradient(gradient, row, state.mu)
    gradient[list(state.pins)] = 0.0; norms = np.linalg.norm(gradient, axis=1)
    order = np.argsort(-norms, kind="stable")[:5]
    return tuple((int(index), float(norms[index])) for index in order)


def _diagnostics(state):
    energy = _objective(state, state.points)
    contact = max(0.0, sum(_contact_energy(row, state.mu) for row in state.contacts.values()))
    values = _diagnostic_values(state)
    return V2Diagnostics(energy.fidelity, energy.length, energy.curvature, contact,
        _finite_or_zero(state.fixed_residual), _finite_or_zero(state.stationarity),
        0.0, state.metrics.maximum_violation,
        1.0, state.ccd_candidates, state.ccd_tested, state.accepted, state.rejected,
        state.accelerated_steps, **values)


def _diagnostic_values(state):
    return dict(feasibility_iterations=state.feasibility_iterations,
        max_constraint_violation=state.metrics.maximum_violation,
        aggregate_constraint_violation=state.metrics.squared_violation,
        active_contacts=len(state.contacts), injected_contacts=state.injected,
        retired_contacts=state.retired, limiting_contacts=state.limiting,
        contact_groups=len(state.groups), multiplier_updates=state.multiplier_updates,
        native_contact_ms=state.contact_ms, native_assembly_ms=state.assembly_ms,
        native_factor_ms=state.factor_ms, native_solve_ms=state.solve_ms,
        native_ccd_ms=state.ccd_ms, native_validation_ms=state.validation_ms,
        block_factor_condition=_finite_or_zero(state.condition),
        feasibility_reached_from_invalid=state.started_invalid and state.metrics.feasible)


def _failed_package(request, termination, message, started):
    planner = _planner_unavailable(message); status = collision_backend_status()
    result = V2Result(request.signature(), termination, (), V2Diagnostics(), False, "DIRECT",
                      str(message or termination.value), V2_CONTACT_CORE_VERSION, status.version)
    return V2ContactCoreResult(result, planner, V2ContactCoreTrace(total_ms=_elapsed(started)))


def _planner_ms(planner):
    return float(getattr(planner.diagnostics, "planner_ms", 0.0))


def _motion_contacts(state, source, target):
    output = []
    for index, anchor in zip(state.pin_indices, state.request.anchors):
        if anchor.owner_id: output.append(_owner_contact(source, index, anchor.owner_id))
    return tuple(output)


def _owner_contact(source, pin, owner):
    intervals = []
    if pin: intervals.append((pin - 1, 0.0, 1.0))
    if pin + 1 < len(source): intervals.append((pin, 0.0, 1.0))
    return V2OwnerContact(owner, (pin,), tuple(intervals))


def _edge_owners(state, points=None):
    owners = {index: anchor.owner_id for index, anchor in zip(state.pin_indices, state.request.anchors)}
    return tuple((owners.get(first, ""), owners.get(second, "")) for first, second in _edges(len(state.q)))


def _edges(count):
    return tuple((index, index + 1) for index in range(int(count) - 1))


def _restore_pins(points, pins):
    for index, target in pins.items():
        points[index] = target


def _pin_residual(points, pins):
    return max((float(np.linalg.norm(points[index] - target)) for index, target in pins.items()), default=0.0)


def _radius(state):
    return float(state.request.collision_policy.collision_radius)


def _slack(state):
    return float(state.request.tolerances.clearance_slack)


def _activation(state):
    return _radius(state) + max(4.0 * _slack(state), .25 * _radius(state))


def _validation_threshold(state):
    return max(0.0, _radius(state) - _slack(state))


def _owner_span(state, points=None):
    if state.owner_span_override > 0.0: return state.owner_span_override
    points = state.points if points is None else points
    lengths = []
    for pin in state.pin_indices:
        if pin: lengths.append(np.linalg.norm(points[pin] - points[pin - 1]))
        if pin + 1 < len(points): lengths.append(np.linalg.norm(points[pin + 1] - points[pin]))
    return max(4.0 * _slack(state), 2.5 * _radius(state), max(lengths, default=0.0), 1.0e-9)


def _unit(value):
    row = np.asarray(value, dtype=np.float64); length = float(np.linalg.norm(row))
    return row / length if length > 1.0e-12 else np.zeros(3)


def _elapsed(started):
    return 1000.0 * (perf_counter() - started)


def _finite_or_zero(value):
    return float(value) if np.isfinite(value) else 0.0


def _policy_enabled(state, name):
    return bool(getattr(getattr(state, "policy", None), name, False))


def _objective(state, points):
    return objective_energy(points, state.q, _effective_settings(state),
                            _true_length_epsilon(state), _spacing_weight(state))


def _objective_gradient(state, points):
    return objective_gradient(points, state.q, _effective_settings(state),
                              _true_length_epsilon(state), _spacing_weight(state))


def _spacing_weight(state):
    ratio = _spacing_ratio(state)
    if ratio <= 0.0: return 0.0
    lengths = np.linalg.norm(np.diff(state.points, axis=0), axis=1)
    scale = max(float(np.mean(lengths)), state.request.tolerances.numeric_floor)
    return ratio * float(state.request.settings.length_weight) / scale


def _spacing_ratio(state):
    if _policy_enabled(state, "adaptive_quality"):
        return .5 if state.quality_adapted and state.quality_spacing else 0.0
    return float(getattr(getattr(state, "policy", None), "spacing_weight_ratio", 0.0))


def _effective_settings(state):
    settings = state.request.settings
    if not _policy_enabled(state, "adaptive_quality"): return settings
    return replace(settings, curvature_weight=0.0)


def _adapt_quality(state):
    if not _quality_can_adapt(state): return
    if state.accepted >= 4 and _segment_cv(state.points) > .75:
        _enable_quality(state, True, "NODE_SPACING")


def _quality_can_adapt(state):
    return bool(_policy_enabled(state, "adaptive_quality") and not state.quality_adapted)


def _enable_quality(state, spacing, reason):
    state.quality_adapted = True; state.quality_spacing = bool(spacing)
    state.quality_trigger = str(reason); state.energy_streak = 0
    state.pending_sqp = None


def _segment_cv(points):
    edges = np.diff(np.asarray(points, dtype=np.float64), axis=0)
    lengths = np.linalg.norm(edges, axis=1); mean = float(np.mean(lengths)) if len(lengths) else 0.0
    return float(np.std(lengths) / mean) if mean > 0.0 else 0.0


def _true_length_epsilon(state):
    if not _policy_enabled(state, "true_length_irls"): return None
    ratio = float(getattr(state.policy, "true_length_epsilon_ratio", 1.0e-4))
    edges = np.linalg.norm(np.diff(state.q, axis=0), axis=1)
    scale = max(float(np.mean(edges)), state.request.tolerances.numeric_floor)
    return max(state.request.tolerances.numeric_floor, ratio * scale)
