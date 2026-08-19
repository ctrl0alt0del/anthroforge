"""Isolated per-node active-set V3 corridor experiment."""

from dataclasses import replace
from time import perf_counter

import numpy as np

from .v2.collision import V2SweepPairCache, build_triangle_snapshot, collision_free_step
from .v2.contracts import V2Termination
from . import v3_experiment as base


V3_ACTIVE_STEP_VERSION = "fiber-v3-active-step-experiment-1"


def solve_v3_active_step(request, snapshot=None):
    started = perf_counter(); triangle = snapshot or build_triangle_snapshot(request.colliders)
    corridor = base.plan_v3_corridor(request, triangle)
    if not corridor.succeeded: return base._failed_result(corridor)
    state = _state(request, triangle, corridor); _advance(state)
    result = base._finish(state, V2Termination.CONVERGED.value,
                          "per-node collision boundaries resolved", started)
    return replace(result, trace=replace(result.trace, projected_residual=_residual(state)))


def solve_v3_active_refined(request, snapshot=None):
    from .v3_joint_experiment import solve_v3_joint
    triangle = snapshot or build_triangle_snapshot(request.colliders)
    corridor = base.plan_v3_corridor(request, triangle)
    if not corridor.succeeded: return base._failed_result(corridor)
    state = _state(request, triangle, corridor); _advance(state)
    prior = base._finish(state, V2Termination.CONVERGED.value, "active boundary ready", perf_counter())
    return solve_v3_joint(request, triangle, prior)


def _state(request, snapshot, corridor):
    direct, roadmap = np.asarray(corridor.direct), np.asarray(corridor.roadmap)
    edges = base._edges(len(direct)); owners = base._edge_owners(corridor.contacts, edges)
    return base._State(request, snapshot, corridor, direct, roadmap, np.ones(len(direct)),
                       roadmap.copy(), edges, owners, base._world(request), V2SweepPairCache())


def _advance(state):
    active = np.ones(len(state.points), dtype=bool)
    locked = np.zeros(len(state.points), dtype=bool)
    active[np.asarray(state.corridor.pin_indices, dtype=np.int64)] = False
    for iteration in range(2 * len(active)):
        if not np.any(active): break
        state.iterations = iteration + 1; target = state.points.copy(); target[active] = state.direct[active]
        step = _safe_step(state, target); fraction = _fraction(step)
        _accept_step(state, target, active, fraction)
        if fraction >= 1.0: active[:] = False
        else:
            node = _freeze_limiter(state, active); locked[node] = True
    return locked


def _accept_step(state, target, active, fraction):
    state.points[active] += fraction * (target[active] - state.points[active])
    state.alpha[active] *= 1.0 - fraction; state.accepted += int(fraction > 0.0)
    state.rejected += int(fraction < 1.0)


def _freeze_limiter(state, active):
    edge = int(state.pair_cache.priority[0]) if state.pair_cache.priority else -1
    candidates = [int(node) for node in state.edges[edge] if active[int(node)]] if edge >= 0 else []
    if not candidates: candidates = list(map(int, np.flatnonzero(active)[:1]))
    node = _contact_node(state, edge, candidates) if len(candidates) > 1 else candidates[0]
    active[node] = False
    return node


def _contact_node(state, edge, candidates):
    rows, mapping = base._chain_contacts(state, state.points, base._threshold(state) * 1.01)
    queries = [index for index, row in enumerate(mapping) if row[0] == edge and rows.active[index]]
    if not queries: return max(candidates, key=lambda node: np.linalg.norm(state.points[node] - state.direct[node]))
    query = min(queries, key=lambda index: rows.distances[index]); low, high = mapping[query][1:]
    factor = low + (high - low) * rows.factors[query]
    return candidates[int(factor >= 0.5)]


def _safe_step(state, target):
    state.ccd += 1
    return collision_free_step(state.points, target, state.snapshot,
                               state.request.collision_policy.collision_radius,
                               state.corridor.contacts, slack=state.request.tolerances.clearance_slack,
                               pair_cache=state.pair_cache, assume_initial_valid=True)


def _fraction(step):
    if not step.valid or step.safe_step <= 1.0e-10: return 0.0
    return 1.0 if step.safe_step >= 1.0 else 0.999 * step.safe_step


def _residual(state):
    distance = np.linalg.norm(state.points - state.direct, axis=1)
    scale = max(state.request.tolerances.length_scale, 1.0e-9)
    return float(np.max(distance) / scale) if len(distance) else 0.0
