"""Package 7.2 shape-reference and adaptive-recovery experiment."""

from dataclasses import dataclass
from time import perf_counter

import numpy as np

from .contracts import V2Diagnostics, V2Termination
from .structural import structural_energy
from . import solver as p5
from . import solver_p6 as p6
from . import solver_p61 as p61
from . import solver_p71 as p71


V2_SOLVER_P72_VERSION = "fiber-v2-solver-package7.2-1"
RATIO_ACCEPT = 0.10
RATIO_SHRINK = 0.25
RATIO_GROW = 0.75


@dataclass(frozen=True)
class V2Package72Trace(p71.V2Package71Trace):
    acquisition_ms: float = 0.0
    acquisition_trials: int = 0
    acquisition_accepted: int = 0
    acquisition_rejected: int = 0
    recovery_activations: int = 0
    ratio_history: tuple = ()
    controller_history: tuple = ()
    rejection_reasons: tuple = ()
    reference_source: str = "P51_PROXIMAL"


def solve_package72(request, snapshot=None, contact_weight=p5.DEFAULT_CONTACT_WEIGHT):
    started = perf_counter(); triangle = snapshot or p5.build_triangle_snapshot(request.colliders)
    planner = p5._package5_planner(request, triangle)
    if not planner.succeeded:
        return _failed(request, planner, started, contact_weight)
    state = p6._state(request, p5._solver_planner(request, planner), triangle, contact_weight)
    _initialize(state); _acquire_reference(state); first = _start_fixed_phase(state)
    termination, message = _iterate(state, first); return _finish(state, termination, message, started)


def _initialize(state):
    p5._prepare_contacts(state); state.acquisition_ms = 0.0
    state.acquisition_trials = state.acquisition_accepted = state.acquisition_rejected = 0
    state.ratio_history = []; state.controller_history = []; state.rejection_reasons = []
    state.recovery_activations = 0; state.controller = "FAST"


def _acquisition_cap(state):
    steps = state.request.settings.max_accepted_steps
    return min(4, max(0, steps - 1), max(1, steps // 3))


def _acquire_reference(state):
    started = perf_counter(); cap = _acquisition_cap(state)
    while state.acquisition_accepted < cap and state.acquisition_trials < 2 * cap + 2:
        if not _acquisition_trial(state):
            break
    state.acquisition_ms = p5._elapsed(started)


def _acquisition_trial(state):
    state.acquisition_trials += 1; before_a, before_r = len(state.accepted), state.rejected
    candidate = p5._candidate(state); changed = state.contact_changed
    accepted, full = p5._accept_candidate(state, candidate)
    state.acquisition_accepted += len(state.accepted) - before_a
    state.acquisition_rejected += state.rejected - before_r
    return bool(accepted and (changed or not (full and p5._step_converged(state))))


def _start_fixed_phase(state):
    state.reference = state.points.copy(); _reset_fixed_trace(state)
    p61._initialize_dispatch(state); first = p71._candidate(state)
    state.workload = p61._dispatch_probe(state, first); _select_controller(state)
    return state.dispatch_candidate if state.certificates_enabled else first


def _reset_fixed_trace(state):
    state.accepted = []; state.rejected = 0; state.trials = 0
    state.stationarity_history = []; state.model_ms = 0.0
    state.fixed_contact_stable = 0; state.zero_signature = None; state.zero_repeats = 0
    state.model_repeats = 0; state.poor_ratio_repeats = 0; state.high_ratio_steps = 0


def _select_controller(state):
    state.controller = "TRUST" if state.certificates_enabled else "FAST"
    state.controller_history.append(state.controller)


def _remaining_budget(state):
    return max(1, state.request.settings.max_accepted_steps - state.acquisition_accepted)


def _iterate(state, first):
    budget = _remaining_budget(state); limit = 2 * budget + 8; candidate = first
    while len(state.accepted) < budget and state.trials < limit:
        state.trials += 1; terminal = _trial(state, candidate)
        if terminal is not None:
            return terminal
        candidate = None
    return _budget_terminal(state, budget)


def _trial(state, cached):
    base = cached if cached is not None else p71._candidate(state)
    changed = state.contact_changed; candidate, clipped = _controlled_candidate(state, base, cached)
    if _model_converged(state, changed, clipped):
        return V2Termination.CONVERGED, "adaptive fixed-reference fixed point"
    proposed, full, step = _proposal(state, candidate); outcome = _assess(state, candidate, proposed)
    _record_trial(state, outcome, full, clipped, changed, step)
    return _terminal(state, outcome, full, clipped, changed, step)


def _controlled_candidate(state, base, cached):
    if state.controller != "TRUST":
        return base, 0
    if cached is not None and state.certificates_enabled:
        return base, state.dispatch_clipped
    return p6._bounded_candidate(state, base)


def _proposal(state, candidate):
    started = perf_counter(); step = _safe_step(state, candidate)
    state.ccd_ms += p5._elapsed(started); p5._absorb_ccd(state, step)
    state.ccd_intervals += int(step.intervals)
    proposed, full = p5._ccd_proposal(state.points, candidate, step)
    return proposed, full, step


def _safe_step(state, candidate):
    if state.controller == "TRUST":
        return p6._safe_step(state, candidate)
    envelope = p5._waypoint_envelope(state.points, (candidate,))
    return p5._safe_step_p51(state, state.points, candidate, envelope)


def _assess(state, candidate, proposed):
    if proposed is None:
        return False, float("nan"), "CCD_ZERO"
    _record_proposed(state, proposed)
    current = p71._merit(state, state.points); predicted = current - p71._merit(state, candidate)
    actual = current - p71._merit(state, proposed); ratio = _ratio(actual, predicted, current)
    if not np.isfinite(ratio) or predicted <= _merit_floor(current):
        return False, ratio, "MODEL_NONDESCENT"
    return (ratio >= RATIO_ACCEPT and actual >= -_merit_floor(current)), ratio, _ratio_reason(ratio)


def _ratio(actual, predicted, current):
    if predicted <= _merit_floor(current):
        return float("nan")
    return float(actual / predicted)


def _merit_floor(value):
    return 1.0e-12 * max(1.0, abs(float(value)))


def _ratio_reason(ratio):
    return "ACCEPT" if ratio >= RATIO_ACCEPT else "POOR_RATIO"


def _record_trial(state, outcome, full, clipped, changed, step):
    accepted, ratio, reason = outcome; state.ratio_history.append(float(ratio))
    state.controller_history.append(state.controller); _update_stability(state, accepted, full, changed, ratio)
    state.poor_ratio_repeats = state.poor_ratio_repeats + 1 if reason == "POOR_RATIO" else 0
    if accepted:
        _accept(state, ratio)
    else:
        _reject(state, reason)
    _update_zero_state(state, accepted, changed, step); _update_controller(state, accepted, ratio, full, clipped)


def _accept(state, ratio):
    proposed = state._trial_proposed; merit = p71._merit(state, proposed)
    prior = state.points.copy(); state.last_step = p5._normalized_step(state, proposed)
    state.points = np.asarray(proposed); state.accepted.append(float(merit))
    state.model_repeats = 0
    state.stationarity_history.append(p71._stationarity(state))
    if state.controller == "TRUST":
        state.distance_cache.advance(p6._edges(state), prior, state.points)


def _reject(state, reason):
    state.rejected += 1; state.rejection_reasons.append(str(reason))
    state.model_repeats = state.model_repeats + 1 if reason == "MODEL_NONDESCENT" else 0
    if state.controller == "FAST":
        _activate_recovery(state)


def _update_stability(state, accepted, full, changed, ratio):
    stable = bool(accepted and full and not changed and np.isfinite(ratio) and ratio >= RATIO_GROW)
    state.fixed_contact_stable = state.fixed_contact_stable + 1 if stable else 0
    state.high_ratio_steps = state.high_ratio_steps + 1 if stable else 0


def _update_controller(state, accepted, ratio, full, clipped):
    state.trust_radii.append(float(state.trust_radius))
    if not accepted or not np.isfinite(ratio) or ratio < RATIO_SHRINK:
        state.trust_radius = max(state.min_trust, 0.5 * state.trust_radius)
    elif ratio > RATIO_GROW and full and clipped:
        state.trust_radius = min(state.max_trust, 1.5 * state.trust_radius)
    if state.controller == "TRUST" and state.high_ratio_steps >= 2:
        state.controller = "FAST"; state.high_ratio_steps = 0


def _activate_recovery(state):
    state.controller = "TRUST"; state.recovery_activations += 1
    state.trust_ever = True; state.trust_activations += 1
    state.controller_history.append("TRUST")


def _update_zero_state(state, accepted, changed, step):
    signature = (step.reason.value, int(step.candidate_pairs), int(step.tested_pairs))
    zero = bool(not accepted and not changed and step.safe_step <= 1.0e-12)
    state.zero_repeats = state.zero_repeats + 1 if zero and signature == state.zero_signature else int(zero)
    state.zero_signature = signature if zero else None


def _terminal(state, outcome, full, clipped, changed, step):
    accepted, _ratio_value, _reason = outcome
    if not step.valid and step.reason.value == "BACKEND_UNAVAILABLE":
        return V2Termination.BACKEND_UNAVAILABLE, "native collision backend unavailable"
    if accepted and _model_converged(state, changed, clipped) and full:
        return V2Termination.CONVERGED, "adaptive fixed-reference trust fixed point"
    if state.zero_repeats >= 2 and state.trust_radius <= state.min_trust * (1.0 + 1.0e-12):
        return V2Termination.BLOCKED, "minimum trust radius is repeatedly CCD-blocked"
    if state.model_repeats >= 3 and state.trust_radius <= state.min_trust * (1.0 + 1.0e-12):
        return V2Termination.STALLED, "fixed model has no feasible descent direction"
    if state.poor_ratio_repeats >= 3 and state.trust_radius <= state.min_trust * (1.0 + 1.0e-12):
        return V2Termination.STALLED, "minimum trust has persistently poor model agreement"
    return None


def _model_converged(state, changed, clipped):
    tolerance = state.request.tolerances
    return bool(not changed and not clipped and state.fixed_residual <= tolerance.fixed_point_tolerance
                and p71._stationarity(state) <= tolerance.stationarity_tolerance)


def _budget_terminal(state, budget):
    if len(state.accepted) >= budget:
        return V2Termination.BUDGET_EXHAUSTED, "shared accepted-step cap exhausted"
    reason = state.rejection_reasons[-1] if state.rejection_reasons else "trial limit"
    return V2Termination.STALLED, f"adaptive recovery exhausted after {reason}"


def _record_proposed(state, proposed):
    state._trial_proposed = proposed
    return proposed


def _finish(state, termination, message, started):
    checked = p5._timed_validation(state, state.points); diagnostics = _diagnostics(state, checked)
    validated = bool(checked.valid and np.isfinite(state.points).all())
    if not validated:
        termination, message = V2Termination.UNSAFE_OUTPUT, "final independent validation failed"
    result = p5._result(state.request, state.planner, state.points, diagnostics,
                        termination, validated, message, V2_SOLVER_P72_VERSION)
    return p5.V2Package5Result(result, state.planner, _trace(state, started))


def _diagnostics(state, checked):
    energy = structural_energy(state.points, state.reference, state.request.settings)
    accepted = state.acquisition_accepted + len(state.accepted)
    rejected = state.acquisition_rejected + state.rejected
    return V2Diagnostics(energy.fidelity, energy.length, energy.curvature, p5._contact_energy(state, checked),
                         state.fixed_residual, p71._stationarity(state), checked.node_residual,
                         checked.edge_residual, state.fractions[-1] if state.fractions else 1.0,
                         state.ccd_pairs, state.ccd_tested, accepted, rejected, 0)


def _trace(state, started):
    base = p71._trace(state, started)
    return V2Package72Trace(**vars(base), acquisition_ms=float(state.acquisition_ms),
                            acquisition_trials=state.acquisition_trials,
                            acquisition_accepted=state.acquisition_accepted,
                            acquisition_rejected=state.acquisition_rejected,
                            recovery_activations=state.recovery_activations,
                            ratio_history=tuple(state.ratio_history),
                            controller_history=tuple(state.controller_history),
                            rejection_reasons=tuple(state.rejection_reasons))


def _failed(request, planner, started, contact_weight):
    result = p5._result(request, planner, (), V2Diagnostics(), planner.termination, False,
                        planner.message, V2_SOLVER_P72_VERSION)
    trace = V2Package72Trace(total_ms=p5._elapsed(started), contact_weight=float(contact_weight))
    return p5.V2Package5Result(result, planner, trace)
