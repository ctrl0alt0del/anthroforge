"""Resumable legacy Fiber iteration operations."""

from dataclasses import dataclass, field
from time import perf_counter

from ..deps.runtime_trace import telemetry_count
from .fiber_engine import FiberPhase


@dataclass
class FiberIterationWork:
    start: list
    candidate: list
    pins: object
    targets: dict
    local: dict
    next_guards: dict
    cyclic: bool
    stage: str = "POINTS"
    cursor: int = 0
    max_pen: float = 0.0
    zones: object = None
    alpha: float = 0.0
    accepted_pen: float = 0.0


def start_iteration(session):
    level, solver = session.level, session.solver
    local = solver._collision_context_params(level.params)
    local["_trusted_clear_start"] = level.safe is not None
    level.params["_trusted_clear_start"] = local["_trusted_clear_start"]
    level.colliders = solver._active_colliders(session.oracle, level.nodes,
                                               level.params["margin"])
    start = [point.copy() for point in level.nodes]
    pins = solver._effective_pinned(level.pinned, level.guards, len(start))
    targets = solver._effective_pin_targets(level.targets, level.guards)
    session.iteration_work = FiberIterationWork(
        start, [point.copy() for point in start], pins, targets, local, {}, session.loop)
    telemetry_count("fiber_iterations")
    session.phase = FiberPhase.GLOBAL_STEP.value


def advance_global(session):
    work, solver = session.iteration_work, session.solver
    if work.cyclic:
        solver._apply_cyclic_smoothing(work.candidate, work.pins, work.targets,
                                       work.local, session.level.iteration)
    else:
        solver._apply_open_smoothing(work.candidate, work.pins, work.targets,
                                     work.local, session.level.iteration)
    session.phase = FiberPhase.CONTACTS.value


def advance_contacts(session, deadline):
    work = session.iteration_work
    if work.stage in {"POINTS", "POINTS_V2"}:
        _advance_points(session, deadline)
    elif work.stage == "EDGES":
        _advance_edges(session, deadline)
    else:
        _advance_rollback(session, deadline)
    _advance_contact_stage(session)


def _advance_points(session, deadline):
    work, indices = session.iteration_work, _point_indices(session)
    work.zones = work.zones or session.solver._owner_zone_limits(
        work.candidate, session.oracle, session.level.colliders, work.local)
    while work.cursor < len(indices) and _within_deadline(work.cursor, deadline):
        _push_point(session, indices[work.cursor])
        work.cursor += 1


def _point_indices(session):
    count = len(session.iteration_work.candidate)
    return tuple(range(count)) if session.loop else tuple(range(1, max(1, count - 1)))


def _push_point(session, index):
    work, level, solver = session.iteration_work, session.level, session.solver
    if solver._is_pinned(work.pins, index):
        return
    cols = solver._node_colliders(work.candidate, index, session.oracle,
                                  level.colliders, work.local, work.zones)
    point, pen = session.oracle.push_out_point(work.candidate[index], cols)
    work.candidate[index] = point
    work.max_pen = max(work.max_pen, float(pen))


def _advance_edges(session, deadline):
    work, solver = session.iteration_work, session.solver
    pairs = solver._segment_pairs(len(work.candidate), work.cyclic)
    while work.cursor < len(pairs) and _within_deadline(work.cursor, deadline):
        _push_edge(session, pairs[work.cursor])
        work.cursor += 1


def _push_edge(session, pair):
    work, level, solver = session.iteration_work, session.level, session.solver
    first, second = pair
    cols = solver._pair_colliders(work.candidate, first, second, session.oracle,
                                  level.colliders, work.local, work.zones)
    if not solver._pair_needs_segment_penalty(
            work.candidate, first, second, session.oracle, cols, work.local):
        return
    pen = solver._segment_penalty(work.candidate, work.pins, session.oracle,
                                  cols, first, second, work.local)
    work.max_pen = max(work.max_pen, float(pen))


def _advance_rollback(session, deadline):
    work, solver = session.iteration_work, session.solver
    pairs = solver._segment_pairs(len(work.candidate), work.cyclic)
    while work.cursor < len(pairs) and _within_deadline(work.cursor, deadline):
        first, second = pairs[work.cursor]
        solver._rollback_segment_pair(
            work.candidate, work.start, work.pins, session.oracle,
            session.level.colliders, work.local, first, second, work.next_guards)
        work.cursor += 1


def _advance_contact_stage(session):
    work, solver = session.iteration_work, session.solver
    total = _stage_size(session)
    if work.cursor < total:
        return
    if work.stage == "POINTS":
        work.stage = "EDGES" if work.local["segment_collisions"] else _after_edges(solver, work)
    elif work.stage == "EDGES":
        work.stage = _after_edges(solver, work)
    else:
        _finish_contacts(session)
        return
    work.cursor, work.zones = 0, None
    if work.stage == "DONE":
        _finish_contacts(session)


def _stage_size(session):
    work = session.iteration_work
    if work.stage in {"POINTS", "POINTS_V2"}:
        return len(_point_indices(session))
    return len(session.solver._segment_pairs(len(work.candidate), work.cyclic))


def _after_edges(solver, work):
    if solver._uses_v2(work.local):
        return "POINTS_V2"
    return "ROLLBACK" if work.local["segment_collisions"] else "DONE"


def _finish_contacts(session):
    work = session.iteration_work
    session.solver._restore_pins(work.candidate, work.targets)
    work.local["_v2_contact"] = session.solver._uses_v2(
        work.local) and work.max_pen > work.local["eps_pen"]
    session.phase = FiberPhase.LINE_SEARCH.value


def advance_line_search(session):
    work, solver = session.iteration_work, session.solver
    level = session.level
    work.alpha, work.accepted_pen = solver._accept_candidate(
        level.nodes, work.start, work.candidate, session.oracle, work.local,
        cyclic=work.cyclic, skip_ends=not work.cyclic)
    session.phase = FiberPhase.ACCEPT.value


def iteration_result(session):
    work, solver = session.iteration_work, session.solver
    displacement = solver._max_displacement(session.level.nodes, work.start)
    penetration = solver._accepted_pen(
        work.alpha, work.accepted_pen, work.max_pen)
    return work.local, work.next_guards, displacement, penetration, work.alpha


def clear_iteration(session):
    session.iteration_work = None


def _within_deadline(cursor, deadline):
    return cursor == 0 or perf_counter() < deadline
