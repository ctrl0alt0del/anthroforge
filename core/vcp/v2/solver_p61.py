"""Package 6.1 dynamically dispatched Fiber V2 experiment."""

from dataclasses import dataclass
from time import perf_counter

import numpy as np

from .collision import build_triangle_snapshot, probe_collision_workload
from .contracts import V2Diagnostics, V2Termination
from . import solver as p5
from . import solver_p6 as p6


V2_SOLVER_P61_VERSION = "fiber-v2-solver-package6.1-1"
MINIMUM_PAIRS = 256
MINIMUM_DENSITY = 4.0
MINIMUM_EXCLUSION = 0.70
MINIMUM_COMPRESSION = 0.50


@dataclass(frozen=True)
class V2Package61Trace(p6.V2Package6Trace):
    dispatch_ms: float = 0.0
    dispatch_candidates: int = 0
    dispatch_density: float = 0.0
    dispatch_sampled: int = 0
    dispatch_excluded: int = 0
    dispatch_exclusion_ratio: float = 0.0
    dispatch_bounded_candidates: int = 0
    dispatch_compression_ratio: float = 0.0
    certificates_enabled: bool = False
    trust_enabled: bool = False
    selected_mode: str = "P51"
    trust_activations: int = 0


def solve_package61(request, snapshot=None, contact_weight=p5.DEFAULT_CONTACT_WEIGHT):
    started = perf_counter(); triangle = snapshot or build_triangle_snapshot(request.colliders)
    planner = p5._package5_planner(request, triangle)
    if not planner.succeeded:
        return _failed(request, planner, started, contact_weight)
    state = p6._state(request, p5._solver_planner(request, planner), triangle, contact_weight)
    p5._prepare_contacts(state); first = p5._candidate(state); _initialize_dispatch(state)
    state.workload = _dispatch_probe(state, first); termination, message = _iterate(state, first)
    return _finish(state, termination, message, started)


def _initialize_dispatch(state):
    state.dispatch_ms = 0.0; state.certificates_enabled = False
    state.trust_enabled = False; state.trust_ever = False; state.trust_activations = 0
    state.dispatch_candidate = None; state.dispatch_clipped = 0; state.dispatch_compression = 0.0


def _dispatch_probe(state, candidate):
    started = perf_counter(); request = state.request; policy = request.collision_policy
    base = _workload(state, candidate, 0); state.base_workload = base
    if not base.certificate_eligible:
        state.dispatch_candidate = candidate; state.dispatch_ms = p5._elapsed(started); return base
    bounded, clipped = p6._bounded_candidate(state, candidate); count = _workload(state, bounded, 0)
    state.dispatch_compression = 1.0 - count.candidate_pairs / max(1, base.candidate_pairs)
    probe = _workload(state, bounded, 128) if state.dispatch_compression >= MINIMUM_COMPRESSION else count
    state.certificates_enabled = probe.exclusion_ratio >= MINIMUM_EXCLUSION
    _enable_initial_trust(state, bounded, clipped); state.dispatch_ms = p5._elapsed(started); return probe


def _workload(state, candidate, sample_limit):
    request = state.request; policy = request.collision_policy
    return probe_collision_workload(state.points, candidate, state.snapshot, policy.collision_radius,
                                    state.planner.contacts, cyclic=p5._cyclic(state),
                                    slack=request.tolerances.clearance_slack, pair_cache=state.pair_cache,
                                    distance_cache=state.distance_cache, minimum_pairs=MINIMUM_PAIRS,
                                    minimum_density=MINIMUM_DENSITY, sample_limit=sample_limit)


def _enable_initial_trust(state, candidate, clipped):
    state.dispatch_candidate = candidate if state.certificates_enabled else None
    state.dispatch_clipped = clipped if state.certificates_enabled else 0
    state.trust_enabled = state.certificates_enabled; state.trust_ever = state.certificates_enabled
    state.trust_activations = int(state.certificates_enabled)


def _iterate(state, first):
    if not state.certificates_enabled:
        return _iterate_p51(state, first)
    return _iterate_dynamic(state, state.dispatch_candidate)


def _iterate_p51(state, first):
    for trial in range(state.request.settings.max_accepted_steps):
        state.trials += 1; candidate = first if trial == 0 else p5._candidate(state)
        changed = state.contact_changed; accepted, full = p5._accept_candidate(state, candidate)
        if accepted and full and not changed and p5._step_converged(state):
            return V2Termination.CONVERGED, "P5.1 fast path fixed point"
        if not accepted and not changed:
            return V2Termination.BLOCKED, "P5.1 fast path is blocked"
    return V2Termination.BUDGET_EXHAUSTED, "accepted-step cap exhausted"


def _iterate_dynamic(state, first):
    for trial in range(state.request.settings.max_accepted_steps):
        state.trials += 1
        candidate, clipped = ((first, state.dispatch_clipped) if trial == 0 else p6._candidate(state))
        changed = state.contact_changed; accepted, full, step = p6._accept(state, candidate)
        p6._update_trust(state, accepted, full, step); state.clipped_nodes.append(clipped)
        terminal = p6._terminal(state, accepted, full, clipped, changed, step)
        if terminal is not None:
            return terminal
    return V2Termination.BUDGET_EXHAUSTED, "accepted-step cap exhausted"


def _finish(state, termination, message, started):
    checked = p5._timed_validation(state, state.points); diagnostics = p5._diagnostics(state, checked)
    validated = bool(checked.valid and np.isfinite(state.points).all())
    if not validated:
        termination, message = V2Termination.UNSAFE_OUTPUT, "final independent validation failed"
    result = p5._result(state.request, state.planner, state.points, diagnostics,
                        termination, validated, message, V2_SOLVER_P61_VERSION)
    return p5.V2Package5Result(result, state.planner, _trace(state, started))


def _trace(state, started):
    base = p6._trace(state, started); probe = state.workload; initial = state.base_workload
    mode = "P61_TRUST" if state.trust_ever else "P61_CERTIFICATES" if state.certificates_enabled else "P51"
    return V2Package61Trace(**vars(base), dispatch_ms=state.dispatch_ms,
                            dispatch_candidates=initial.candidate_pairs, dispatch_density=initial.pair_density,
                            dispatch_sampled=probe.sampled_pairs, dispatch_excluded=probe.excluded_pairs,
                            dispatch_exclusion_ratio=probe.exclusion_ratio,
                            dispatch_bounded_candidates=probe.candidate_pairs,
                            dispatch_compression_ratio=state.dispatch_compression,
                            certificates_enabled=state.certificates_enabled, trust_enabled=state.trust_ever,
                            selected_mode=mode, trust_activations=state.trust_activations)


def _failed(request, planner, started, contact_weight):
    result = p5._result(request, planner, (), V2Diagnostics(), planner.termination, False,
                        planner.message, V2_SOLVER_P61_VERSION)
    trace = V2Package61Trace(total_ms=p5._elapsed(started), contact_weight=float(contact_weight))
    return p5.V2Package5Result(result, planner, trace)
