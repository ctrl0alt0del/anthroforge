"""Package 6 contact-space trust-step Fiber V2 experiment."""

from dataclasses import dataclass
from time import perf_counter

import numpy as np

from .collision import (V2CollisionReason, V2DistanceCertificateCache,
                        build_triangle_snapshot, collision_free_step)
from .contracts import V2Diagnostics, V2Termination
from . import solver as p5


V2_SOLVER_P6_VERSION = "fiber-v2-solver-package6-1"


@dataclass(frozen=True)
class V2Package6Trace(p5.V2Package5Trace):
    trust_radii: tuple = ()
    clipped_nodes: tuple = ()
    certificate_hits: int = 0
    certificate_refreshes: int = 0
    certificate_exclusions: int = 0
    ccd_intervals: int = 0


def solve_package6(request, snapshot=None, contact_weight=p5.DEFAULT_CONTACT_WEIGHT):
    started = perf_counter(); triangle = snapshot or build_triangle_snapshot(request.colliders)
    planner = p5._package5_planner(request, triangle)
    if not planner.succeeded:
        return _failed(request, planner, started, contact_weight)
    state = _state(request, p5._solver_planner(request, planner), triangle, contact_weight)
    p5._prepare_contacts(state); termination, message = _iterate(state)
    return _finish(state, termination, message, started)


def _state(request, planner, snapshot, contact_weight):
    state = p5._solver_state(request, planner, snapshot, contact_weight, True)
    edge = _median_edge(state.reference, p5._cyclic(state)); radius = request.collision_policy.collision_radius
    state.initial_trust = min(2.0 * edge, 8.0 * radius) if radius > 0.0 else 2.0 * edge
    state.min_trust = max(0.25 * radius, request.tolerances.numeric_floor)
    state.max_trust = max(state.initial_trust, 4.0 * edge); state.trust_radius = max(state.min_trust, state.initial_trust)
    _setup_trace_state(state); return state


def _setup_trace_state(state):
    state.distance_cache = V2DistanceCertificateCache(); state.trust_radii = []
    state.clipped_nodes = []; state.ccd_intervals = 0; state.zero_steps = 0


def _median_edge(points, cyclic):
    values = np.asarray(points); delta = np.roll(values, -1, axis=0) - values if cyclic else np.diff(values, axis=0)
    lengths = np.linalg.norm(delta, axis=1); positive = lengths[lengths > 1.0e-12]
    return float(np.median(positive)) if len(positive) else 1.0e-6


def _iterate(state):
    for _trial in range(state.request.settings.max_accepted_steps):
        state.trials += 1; candidate, clipped = _candidate(state)
        changed = state.contact_changed; accepted, full, step = _accept(state, candidate)
        _update_trust(state, accepted, full, step); state.clipped_nodes.append(clipped)
        terminal = _terminal(state, accepted, full, clipped, changed, step)
        if terminal is not None:
            return terminal
    return V2Termination.BUDGET_EXHAUSTED, "accepted-step cap exhausted"


def _candidate(state):
    return _bounded_candidate(state, p5._candidate(state))


def _bounded_candidate(state, candidate):
    delta = np.asarray(candidate) - state.points
    norms = np.linalg.norm(delta, axis=1); maximum = float(np.max(norms)) if len(norms) else 0.0
    scale = min(1.0, state.trust_radius / maximum) if maximum > 0.0 else 1.0
    output = state.points + scale * delta; p5._restore_pins(output, state.pins)
    return output, int(np.count_nonzero(norms > 1.0e-12)) if scale < 1.0 else 0


def _accept(state, candidate):
    started = perf_counter(); step = _safe_step(state, candidate)
    state.ccd_ms += p5._elapsed(started); p5._absorb_ccd(state, step); state.ccd_intervals += step.intervals
    proposed, full = p5._ccd_proposal(state.points, candidate, step)
    if proposed is None:
        state.rejected += 1; return False, False, step
    prior = state.points.copy(); accepted, full = p5._accept_unvalidated(state, proposed, full)
    if accepted:
        state.distance_cache.advance(_edges(state), prior, state.points)
    return accepted, full, step


def _safe_step(state, candidate):
    request = state.request; tolerance = request.tolerances; policy = request.collision_policy
    return collision_free_step(state.points, candidate, state.snapshot, policy.collision_radius,
                               state.planner.contacts, cyclic=p5._cyclic(state),
                               slack=tolerance.clearance_slack, pair_cache=state.pair_cache,
                               assume_initial_valid=True, distance_cache=state.distance_cache)


def _edges(state):
    return p5._chain_links(len(state.points), p5._cyclic(state))


def _update_trust(state, accepted, full, step):
    state.trust_radii.append(float(state.trust_radius))
    if not accepted or step.safe_step < 0.25:
        state.trust_radius = max(state.min_trust, 0.5 * state.trust_radius)
    elif full:
        state.trust_radius = min(state.max_trust, 1.5 * state.trust_radius)


def _terminal(state, accepted, full, clipped, changed, step):
    if not step.valid and step.reason is V2CollisionReason.BACKEND_UNAVAILABLE:
        return V2Termination.BACKEND_UNAVAILABLE, "native collision backend unavailable"
    if accepted and full and not clipped and not changed and p5._step_converged(state):
        return V2Termination.CONVERGED, "contact-space trust fixed point"
    state.zero_steps = state.zero_steps + 1 if step.safe_step <= 1.0e-12 and not changed else 0
    if state.zero_steps >= 2 and state.trust_radius <= state.min_trust * (1.0 + 1.0e-12):
        return V2Termination.BLOCKED, "minimum trust radius is CCD-blocked"
    return None


def _finish(state, termination, message, started):
    checked = p5._timed_validation(state, state.points); diagnostics = p5._diagnostics(state, checked)
    validated = bool(checked.valid and np.isfinite(state.points).all())
    if not validated:
        termination, message = V2Termination.UNSAFE_OUTPUT, "final independent validation failed"
    result = p5._result(state.request, state.planner, state.points, diagnostics,
                        termination, validated, message, V2_SOLVER_P6_VERSION)
    return p5.V2Package5Result(result, state.planner, _trace(state, started))


def _trace(state, started):
    base = p5._trace(state, started); cache = state.distance_cache
    return V2Package6Trace(**vars(base), trust_radii=tuple(state.trust_radii),
                           clipped_nodes=tuple(state.clipped_nodes), certificate_hits=cache.hits,
                           certificate_refreshes=cache.refreshes, certificate_exclusions=cache.excluded,
                           ccd_intervals=state.ccd_intervals)


def _failed(request, planner, started, contact_weight):
    result = p5._result(request, planner, (), V2Diagnostics(), planner.termination, False,
                        planner.message, V2_SOLVER_P6_VERSION)
    trace = V2Package6Trace(p5._elapsed(started), contact_weight=float(contact_weight))
    return p5.V2Package5Result(result, planner, trace)
