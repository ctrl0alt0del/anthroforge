"""Opt-in round-robin SQP experiment split at authored hard anchors."""

from dataclasses import dataclass, replace
from time import perf_counter

import numpy as np

from .collision import build_triangle_snapshot_known, cached_native_collision_world_batch
from .contact_core import (_direct_reference, _planner_seed, V2ContactCoreResult,
                           _finish_contact_session, begin_contact_core)
from .contracts import (V2AnchorRole, V2Diagnostics, V2Result, V2Termination)
from .planner import plan_reference_v43


V2_SUBFIBER_SQP_VERSION = "fiber-v2-subfiber-sqp-experiment-1"
V2_SUBFIBER_SQP_FIXED_VERSION = "fiber-v2-subfiber-sqp-experiment-2"


@dataclass(frozen=True)
class V2SubfiberSpanTrace:
    span: int
    first_node: int
    last_node: int
    completed_round: int
    termination: str
    accepted_steps: int
    rejected_steps: int
    fixed_residual: float
    stationarity_residual: float
    condition: float
    contacts: tuple
    stationarity_profile: tuple
    rejection_reasons: tuple
    iterations: tuple
    experiment_stats: tuple
    regularization_history: tuple
    total_ms: float


@dataclass(frozen=True)
class V2SubfiberTrace:
    planner_ms: float = 0.0
    total_ms: float = 0.0
    outer_rounds: int = 0
    spans: tuple = ()


def solve_subfiber_sqp(request, snapshot=None, use_planner=True, diagnostic_trace=False, experiment=None):
    return _solve_subfibers(request, snapshot, use_planner, False, diagnostic_trace, experiment)


def solve_subfiber_sqp_fixed(request, snapshot=None, use_planner=True, diagnostic_trace=False, experiment=None):
    return _solve_subfibers(request, snapshot, use_planner, True, diagnostic_trace, experiment)


def _solve_subfibers(request, snapshot, use_planner, fixed, diagnostic, experiment):
    started = perf_counter(); q, indices = _direct_reference(request)
    snapshot, planner = _prepare_shared(request, snapshot, use_planner)
    seed = _initial_seed(request, q, indices, planner)
    sessions = _sessions(request, snapshot, seed, indices, fixed, diagnostic, experiment)
    drain = _drain_global if fixed else _drain_round_robin
    rounds, completed = drain(sessions, request, indices)
    version = V2_SUBFIBER_SQP_FIXED_VERSION if fixed else V2_SUBFIBER_SQP_VERSION
    return _aggregate(request, planner, sessions, indices, rounds, completed, started, version)


def _prepare_shared(request, snapshot, use_planner):
    world = cached_native_collision_world_batch(request.colliders)
    shared = snapshot or build_triangle_snapshot_known(request.colliders, world.closed_flags)
    planner = plan_reference_v43(request, shared, native_world=world) if use_planner else None
    return shared, planner


def _initial_seed(request, direct, indices, planner):
    if planner is not None and planner.succeeded:
        return _planner_seed(planner, indices, len(direct))
    if len(request.warm_seed) == len(direct):
        return np.asarray(request.warm_seed, dtype=np.float64)
    return direct


def _sessions(request, snapshot, seed, indices, fixed, diagnostic, experiment):
    output = []
    for span, (first, last) in enumerate(zip(indices[:-1], indices[1:])):
        local = _span_experiment(experiment, seed[first:last + 1])
        subrequest = _span_request(request, seed, span, first, last, fixed,
                                   _true_length_experiment(local), _curvature_scale(local))
        output.append(begin_contact_core(subrequest, snapshot, use_planner=False,
            use_filter_sqp=True, diagnostic_trace=diagnostic, experiment=local))
    return tuple(output)


def _span_request(request, seed, span, first, last, fixed=False, true_length=False,
                  curvature_scale=1.0):
    roles = V2AnchorRole.ENDPOINT_A, V2AnchorRole.ENDPOINT_B
    anchors = tuple(replace(request.anchors[span + index], role=roles[index]) for index in range(2))
    settings = _span_settings(request.settings, last - first + 1, fixed,
                              true_length, curvature_scale)
    warm = tuple(map(tuple, np.asarray(seed[first:last + 1], dtype=np.float64)))
    return replace(request, token=request.token * 1000 + span + 1,
                   source_revision=f"{request.source_revision}:span:{span}",
                   settings=settings, anchors=anchors, warm_seed=warm)


def _span_settings(settings, count, fixed, true_length=False, curvature_scale=1.0):
    bend = settings.curvature_weight * float(curvature_scale)
    if not fixed: return replace(settings, node_count=count, curvature_weight=bend)
    ratio = (settings.node_count - 1) / max(1, count - 1)
    length = settings.length_weight if true_length else settings.length_weight * ratio
    return replace(settings, node_count=count,
        length_weight=length, curvature_weight=bend * ratio ** 3)


def _true_length_experiment(experiment):
    return bool(getattr(experiment, "true_length_irls", False))


def _span_experiment(experiment, points):
    return experiment


def _curvature_scale(experiment):
    return float(getattr(experiment, "curvature_weight_scale", 1.0))


def _drain_round_robin(sessions, _request=None, _indices=None):
    completed = {}; rounds = 0
    while any(not session.done for session in sessions):
        rounds += 1
        for index, session in enumerate(sessions):
            if session.done: continue
            session.step()
            if session.done: completed[index] = rounds
    return rounds, completed


def _drain_global(sessions, request, indices):
    completed = {}; rounds = 0
    while any(not session.done for session in sessions):
        rounds += 1; _sync_owner_span(sessions, request, indices)
        _advance_round(sessions, completed, rounds)
        if _accepted(sessions) >= request.settings.max_accepted_steps:
            _finish_budget(sessions, completed, rounds); break
    return rounds, completed


def _advance_round(sessions, completed, rounds):
    for index, session in enumerate(sessions):
        if session.done: continue
        session.step()
        if session.done: completed[index] = rounds


def _accepted(sessions):
    return sum(session.state.accepted for session in sessions if session.state is not None)


def _finish_budget(sessions, completed, rounds):
    for index, session in enumerate(sessions):
        if session.done: continue
        _finish_contact_session(session, V2Termination.BUDGET_EXHAUSTED,
                                "shared accepted-step cap exhausted")
        completed[index] = rounds


def _sync_owner_span(sessions, request, indices):
    points = _working_points(sessions); radius = request.collision_policy.collision_radius
    slack = request.tolerances.clearance_slack; lengths = _pin_lengths(points, indices)
    value = max(4.0 * slack, 2.5 * radius, max(lengths, default=0.0), 1.0e-9)
    for session in sessions: session.state.owner_span_override = value


def _working_points(sessions):
    rows = []
    for session in sessions:
        points = np.asarray(session.points)
        rows.extend(points if not rows else points[1:])
    return np.asarray(rows)


def _pin_lengths(points, indices):
    rows = []
    for pin in indices:
        if pin: rows.append(float(np.linalg.norm(points[pin] - points[pin - 1])))
        if pin + 1 < len(points): rows.append(float(np.linalg.norm(points[pin + 1] - points[pin])))
    return rows


def _aggregate(request, planner, sessions, indices, rounds, completed, started, version):
    packages = tuple(session.package for session in sessions)
    points = _stitch(packages); diagnostics = _diagnostics(packages)
    termination = _termination(packages); validated = bool(points) and all(
        package.result.validated for package in packages)
    route = planner.mode.value if planner is not None and planner.succeeded else "DIRECT"
    result = V2Result(request.signature(), termination, points, diagnostics, validated, route,
        _message(packages), version, packages[0].result.backend_version)
    trace = _trace(packages, indices, rounds, completed, planner, started)
    return V2ContactCoreResult(result, planner or packages[0].planner, trace)


def _stitch(packages):
    rows = []
    for package in packages:
        points = package.result.points
        if not points: return ()
        rows.extend(points if not rows else points[1:])
    return tuple(rows)


def _termination(packages):
    values = tuple(package.result.termination for package in packages)
    if all(value is V2Termination.CONVERGED for value in values): return V2Termination.CONVERGED
    priority = (V2Termination.UNSAFE_OUTPUT, V2Termination.NO_FEASIBLE_PATH,
                V2Termination.STALLED, V2Termination.BUDGET_EXHAUSTED)
    return next((value for value in priority if value in values), values[0])


def _message(packages):
    return "; ".join(f"span {index}:{package.result.termination.value}"
                     for index, package in enumerate(packages))


def _diagnostics(packages):
    rows = tuple(package.result.diagnostics for package in packages)
    total = lambda name: sum(getattr(row, name) for row in rows)
    maximum = lambda name: max((getattr(row, name) for row in rows), default=0)
    return V2Diagnostics(total("structural_energy"), total("length_energy"),
        total("curvature_energy"), total("contact_energy"), maximum("fixed_point_residual"),
        maximum("stationarity_residual"), maximum("node_clearance_residual"),
        maximum("edge_clearance_residual"), min(row.ccd_step_fraction for row in rows),
        total("ccd_candidate_pairs"), total("ccd_tested_pairs"), total("accepted_steps"),
        total("rejected_steps"), total("accelerated_steps"), **_extra_diagnostics(rows))


def _extra_diagnostics(rows):
    total = lambda name: sum(getattr(row, name) for row in rows)
    maximum = lambda name: max((getattr(row, name) for row in rows), default=0)
    return dict(feasibility_iterations=total("feasibility_iterations"),
        max_constraint_violation=maximum("max_constraint_violation"),
        aggregate_constraint_violation=total("aggregate_constraint_violation"),
        active_contacts=total("active_contacts"), injected_contacts=total("injected_contacts"),
        retired_contacts=total("retired_contacts"), limiting_contacts=total("limiting_contacts"),
        contact_groups=total("contact_groups"), multiplier_updates=total("multiplier_updates"),
        native_contact_ms=total("native_contact_ms"), native_assembly_ms=total("native_assembly_ms"),
        native_factor_ms=total("native_factor_ms"), native_solve_ms=total("native_solve_ms"),
        native_ccd_ms=total("native_ccd_ms"), native_validation_ms=total("native_validation_ms"),
        block_factor_condition=maximum("block_factor_condition"),
        feasibility_reached_from_invalid=any(row.feasibility_reached_from_invalid for row in rows))


def _trace(packages, indices, rounds, completed, planner, started):
    spans = tuple(_span_trace(index, package, indices, completed)
                  for index, package in enumerate(packages))
    planner_ms = 0.0 if planner is None else planner.diagnostics.planner_ms
    return V2SubfiberTrace(planner_ms, 1000.0 * (perf_counter() - started), rounds, spans)


def _span_trace(index, package, indices, completed):
    result, trace = package.result, package.trace; diagnostics = result.diagnostics
    return V2SubfiberSpanTrace(index, indices[index], indices[index + 1], completed[index],
        result.termination.value, diagnostics.accepted_steps, diagnostics.rejected_steps,
        diagnostics.fixed_point_residual, diagnostics.stationarity_residual,
        diagnostics.block_factor_condition, trace.final_contacts,
        trace.stationarity_profile, trace.rejection_reasons,
        trace.iteration_trace, trace.experiment_stats, trace.regularization_history,
        trace.total_ms)
