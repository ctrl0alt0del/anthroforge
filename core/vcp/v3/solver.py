"""Resumable accepted-logic Fiber V3 span solver."""

from dataclasses import dataclass, field, replace
from time import perf_counter

import numpy as np

from ..v2.collision import build_triangle_snapshot_known, cached_native_collision_world_batch
from ..v2.contact_core import (_finish_contact_session, _spacing_weight,
                               begin_contact_core, _direct_reference, _planner_seed)
from ..fiber_numeric_contracts import FiberNumericTermination
from ..v2.planner import plan_reference_v43
from ..v2.trust_sqp import _spacing_energy
from .contracts import v3_diagnostics
from .policy import V3_PRODUCTION_POLICY, accepted_v3_request
from .shortcut import V3ShortcutTrace, apply_v3_shortcut
from .spans import aggregate_spans, prepare_span_request, synchronize_owner_spans


V3_SOLVER_VERSION = "fiber-v3-production-4"


@dataclass
class V3SolveSession:
    request: object
    snapshot: object = None
    preview: bool = False
    checkpoint_steps: int = 0
    use_planner: bool = True
    policy: object = V3_PRODUCTION_POLICY
    started: float = field(default_factory=perf_counter)
    phase: str = "WORLD"
    world: object = None
    planner: object = None
    seed: object = None
    pins: tuple = ()
    spans: tuple = ()
    cursor: int = 0
    rounds: int = 0
    completed: dict = field(default_factory=dict)
    shortcut: object = field(default_factory=V3ShortcutTrace)
    checkpoint_ready: bool = False
    package: object = None
    done: bool = False
    native_session: bool = True

    def step(self):
        _advance_v3(self)
        return self.package

    def cancel(self):
        for row in self.spans:
            cancel = getattr(row, "cancel", None)
            if callable(cancel): cancel()
        self.done, self.phase = True, "DONE"

    @property
    def points(self):
        return _live_points(self)

    @property
    def infeasible(self):
        return any(row.state is not None and not row.state.metrics.feasible for row in self.spans)

    @property
    def pending_native_sweep(self):
        return next((row.pending_native_sweep for row in self.spans
                     if row.pending_native_sweep is not None), None)


def begin_v3_session(request, snapshot=None, preview=False, checkpoint_steps=0,
                     use_planner=True, policy=V3_PRODUCTION_POLICY, native_session=True):
    version = f"{V3_SOLVER_VERSION}:{policy.fingerprint()[:12]}"
    accepted = replace(accepted_v3_request(request, policy), engine_version=version)
    value = V3SolveSession(accepted, snapshot, preview, max(0, int(checkpoint_steps)),
                           bool(use_planner), policy)
    value.native_session = bool(native_session); return value


def solve_v3_session(request, snapshot=None, preview=False, checkpoint_steps=0,
                     use_planner=True, policy=V3_PRODUCTION_POLICY, native_session=True):
    session = begin_v3_session(request, snapshot, preview, checkpoint_steps, use_planner,
                               policy, native_session)
    while not session.done: session.step()
    return session.package


def _advance_v3(session):
    actions = {"WORLD": _prepare_world, "PLAN": _prepare_plan,
               "SEED": _prepare_seed, "SPANS": _prepare_spans, "SOLVE": _advance_spans}
    action = actions.get(session.phase)
    if action is None: _fail_phase(session)
    else: action(session)


def _prepare_world(session):
    session.world = cached_native_collision_world_batch(session.request.colliders)
    if session.snapshot is None:
        session.snapshot = build_triangle_snapshot_known(session.request.colliders, session.world.closed_flags)
    session.phase = "PLAN"


def _prepare_plan(session):
    if session.use_planner:
        session.planner = plan_reference_v43(session.request, session.snapshot, native_world=session.world)
    session.seed, session.pins = _initial_seed(session)
    session.phase = "SEED"


def _initial_seed(session):
    direct, pins = _direct_reference(session.request)
    if session.planner is not None and session.planner.succeeded:
        return _planner_seed(session.planner, pins, len(direct)), pins
    if len(session.request.warm_seed) == len(direct):
        return np.asarray(session.request.warm_seed, dtype=np.float64), pins
    return direct, pins


def _prepare_seed(session):
    if session.planner is not None and session.planner.succeeded:
        session.seed, session.shortcut = apply_v3_shortcut(
            session.request, session.planner, session.seed, session.pins,
            session.world, session.policy.shortcut_mode)
    session.phase = "SPANS"


def _prepare_spans(session):
    rows = []
    for span, (first, last) in enumerate(zip(session.pins[:-1], session.pins[1:])):
        request = prepare_span_request(session.request, session.seed, span, first, last)
        rows.append(begin_contact_core(request, session.snapshot, session.preview, False,
                    use_filter_sqp=True, policy=session.policy,
                    native_session=session.native_session))
    session.spans = tuple(rows); session.completed.update(_already_done(session.spans))
    session.phase = "SOLVE"


def _already_done(spans):
    return {index: 0 for index, row in enumerate(spans) if row.done}


def _advance_spans(session):
    if _budget_done(session):
        _finish_budget(session); return _finalize(session)
    index = _next_span(session)
    if index < 0: return _finalize(session)
    session.spans[index].step(); _record_completion(session, index)
    _try_checkpoint(session)
    if all(row.done for row in session.spans): _finalize(session)


def _next_span(session):
    count = len(session.spans)
    if not count: return -1
    if session.cursor == 0:
        session.rounds += 1; synchronize_owner_spans(session.spans, session.request, session.pins)
    for offset in range(count):
        index = (session.cursor + offset) % count
        if not session.spans[index].done:
            session.cursor = (index + 1) % count
            return index
    return -1


def _record_completion(session, index):
    if session.spans[index].done:
        session.completed[index] = session.rounds


def _accepted(session):
    return sum(row.state.accepted for row in session.spans if row.state is not None)


def _budget_done(session):
    return bool(session.spans and _accepted(session) >= session.request.settings.max_accepted_steps)


def _finish_budget(session):
    for index, row in enumerate(session.spans):
        if row.done: continue
        _finish_contact_session(row, FiberNumericTermination.BUDGET_EXHAUSTED,
                                "shared accepted-step cap exhausted")
        session.completed[index] = session.rounds


def _try_checkpoint(session):
    if session.checkpoint_ready or session.checkpoint_steps <= 0: return
    if _accepted(session) < session.checkpoint_steps: return
    points = _live_points(session)
    session.checkpoint_ready = bool(len(points) and _validate_live(session, points))


def _live_points(session):
    if not session.spans: return () if session.seed is None else session.seed
    rows = []
    for span in session.spans:
        points = np.asarray(span.points)
        rows.extend(points if not rows else points[1:])
    return np.asarray(rows, dtype=np.float64)


def _validate_live(session, points):
    edges = tuple((index, index + 1) for index in range(len(points) - 1))
    owners = _edge_owners(session.request, session.pins, edges)
    result = session.world.validate(points, edges, owners, _owner_span(session, points), _threshold(session))
    return bool(all(result.clear))


def _edge_owners(request, pins, edges):
    values = {index: anchor.owner_id for index, anchor in zip(pins, request.anchors)}
    return tuple((values.get(first, ""), values.get(second, "")) for first, second in edges)


def _owner_span(session, points):
    radius = session.request.collision_policy.collision_radius
    slack = session.request.tolerances.clearance_slack; lengths = []
    for pin in session.pins:
        if pin: lengths.append(np.linalg.norm(points[pin] - points[pin - 1]))
        if pin + 1 < len(points): lengths.append(np.linalg.norm(points[pin + 1] - points[pin]))
    return max(4.0 * slack, 2.5 * radius, max(lengths, default=0.0), 1.0e-9)


def _threshold(session):
    policy = session.request.collision_policy; slack = session.request.tolerances.clearance_slack
    return max(0.0, policy.collision_radius - slack)


def _finalize(session):
    _complete_records(session)
    package = aggregate_spans(session.request, session.planner, session.spans, session.pins,
                              session.rounds, session.completed, session.started, V3_SOLVER_VERSION)
    session.package = _validated_package(session, package)
    session.done, session.phase = True, "DONE"


def _complete_records(session):
    for index, row in enumerate(session.spans):
        if row.done and index not in session.completed: session.completed[index] = session.rounds


def _validated_package(session, package):
    points = np.asarray(package.result.points)
    valid = bool(len(points) and _validate_live(session, points))
    termination = package.result.termination if valid else FiberNumericTermination.UNSAFE_OUTPUT
    message = package.result.message if valid else "stitched Fiber failed independent validation"
    diagnostics = _v3_diagnostics(session, package)
    result = replace(package.result, termination=termination, validated=valid,
                     message=message, diagnostics=diagnostics, engine_version=V3_SOLVER_VERSION)
    return replace(package, result=result)


def _v3_diagnostics(session, package):
    points = np.asarray(package.result.points); lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    initial, final, increases, decreases = _regularization(session)
    return v3_diagnostics(package.result.diagnostics, true_length=float(lengths.sum()),
        fidelity_energy=_fidelity(session, points), spacing_energy=_spacing(session), segment_cv=_cv(lengths),
        regularization_initial=initial, regularization_final=final,
        regularization_increases=increases, regularization_decreases=decreases,
        span_terminations=tuple(row.package.result.termination.value for row in session.spans),
        shortcut_mode=session.shortcut.mode, shortcut_attempts=session.shortcut.attempts,
        shortcut_accepted=session.shortcut.accepted, interactive_checkpoint=session.checkpoint_ready)


def _regularization(session):
    histories = [row.state.regularization_history for row in session.spans if row.state is not None]
    initial = sum((values[0] for values in histories if values), 0.0)
    final = sum((values[-1] for values in histories if values), 0.0)
    increases = sum(row.state.regularization_increases for row in session.spans if row.state is not None)
    decreases = sum(row.state.regularization_decreases for row in session.spans if row.state is not None)
    return initial, final, increases, decreases


def _fidelity(session, points):
    reference, _pins = _direct_reference(session.request)
    if points.shape != reference.shape: return 0.0
    delta = points - reference
    return float(session.request.settings.fidelity_weight) * float(np.sum(delta * delta))


def _spacing(session):
    return sum(_spacing_energy(row.state.points, _spacing_weight(row.state))
               for row in session.spans if row.state is not None)


def _cv(lengths):
    mean = float(np.mean(lengths)) if len(lengths) else 0.0
    return float(np.std(lengths) / mean) if mean > 0.0 else 0.0


def _fail_phase(session):
    session.done, session.phase = True, "DONE"
    raise RuntimeError("invalid V3 session phase")
