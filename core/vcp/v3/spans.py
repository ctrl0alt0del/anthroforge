"""Accepted hard-midpoint span coordination for Fiber V3."""

from dataclasses import dataclass, replace
from time import perf_counter

import numpy as np

from ..fiber_numeric_contracts import FiberNumericDiagnostics, FiberNumericResult, FiberNumericTermination
from ..v2.contact_core import V2ContactCoreResult
from ..v2.contracts import V2AnchorRole


@dataclass(frozen=True)
class V3SpanTrace:
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
    policy_stats: tuple
    regularization_history: tuple
    total_ms: float


@dataclass(frozen=True)
class V3SpanSolveTrace:
    planner_ms: float = 0.0
    total_ms: float = 0.0
    outer_rounds: int = 0
    spans: tuple = ()


def prepare_span_request(request, seed, span, first, last):
    roles = V2AnchorRole.ENDPOINT_A, V2AnchorRole.ENDPOINT_B
    anchors = tuple(replace(request.anchors[span + offset], role=roles[offset])
                    for offset in range(2))
    settings = replace(request.settings, node_count=last - first + 1)
    warm = tuple(map(tuple, np.asarray(seed[first:last + 1], dtype=np.float64)))
    return replace(request, token=request.token * 1000 + span + 1,
                   source_revision=f"{request.source_revision}:span:{span}",
                   settings=settings, anchors=anchors, warm_seed=warm)


def synchronize_owner_spans(sessions, request, indices):
    points = _working_points(sessions); radius = request.collision_policy.collision_radius
    slack = request.tolerances.clearance_slack; lengths = _pin_lengths(points, indices)
    value = max(4.0 * slack, 2.5 * radius, max(lengths, default=0.0), 1.0e-9)
    for session in sessions: session.state.owner_span_override = value


def aggregate_spans(request, planner, sessions, indices, rounds, completed, started, version):
    packages = tuple(session.package for session in sessions)
    points = _stitch(packages); diagnostics = _diagnostics(packages)
    termination = _termination(packages); validated = bool(points) and all(
        package.result.validated for package in packages)
    route = planner.mode.value if planner is not None and planner.succeeded else "DIRECT"
    result = FiberNumericResult(request.signature(), termination, points, diagnostics, validated,
        route, _message(packages), version, packages[0].result.backend_version)
    trace = _trace(packages, indices, rounds, completed, planner, started)
    return V2ContactCoreResult(result, planner or packages[0].planner, trace)


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


def _stitch(packages):
    rows = []
    for package in packages:
        points = package.result.points
        if not points: return ()
        rows.extend(points if not rows else points[1:])
    return tuple(rows)


def _termination(packages):
    values = tuple(package.result.termination for package in packages)
    if all(value is FiberNumericTermination.CONVERGED for value in values):
        return FiberNumericTermination.CONVERGED
    priority = (FiberNumericTermination.UNSAFE_OUTPUT, FiberNumericTermination.NO_FEASIBLE_PATH,
                FiberNumericTermination.STALLED, FiberNumericTermination.BUDGET_EXHAUSTED)
    return next((value for value in priority if value in values), values[0])


def _message(packages):
    return "; ".join(f"span {index}:{package.result.termination.value}"
                     for index, package in enumerate(packages))


def _diagnostics(packages):
    rows = tuple(package.result.diagnostics for package in packages)
    total = lambda name: sum(getattr(row, name) for row in rows)
    maximum = lambda name: max((getattr(row, name) for row in rows), default=0)
    return FiberNumericDiagnostics(total("structural_energy"), total("length_energy"),
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
        feasibility_reached_from_invalid=any(row.feasibility_reached_from_invalid for row in rows),
        native_worker_threads=maximum("native_worker_threads"))


def _trace(packages, indices, rounds, completed, planner, started):
    spans = tuple(_span_trace(index, package, indices, completed)
                  for index, package in enumerate(packages))
    planner_ms = 0.0 if planner is None else planner.diagnostics.planner_ms
    return V3SpanSolveTrace(planner_ms, 1000.0 * (perf_counter() - started), rounds, spans)


def _span_trace(index, package, indices, completed):
    result, trace = package.result, package.trace; diagnostics = result.diagnostics
    return V3SpanTrace(index, indices[index], indices[index + 1], completed[index],
        result.termination.value, diagnostics.accepted_steps, diagnostics.rejected_steps,
        diagnostics.fixed_point_residual, diagnostics.stationarity_residual,
        diagnostics.block_factor_condition, trace.final_contacts,
        trace.stationarity_profile, trace.rejection_reasons,
        trace.iteration_trace, trace.policy_stats, trace.regularization_history,
        trace.total_ms)
