"""Composed, resumable production route coordinator. Native searches stay atomic."""

from dataclasses import dataclass, field, replace
from time import perf_counter
import numpy as np

from . import planner as p
from . import planner_preparation as prep
from .planner_search import (PRODUCTION_ROADMAP_POLICY, RoadmapAttempt, RoadmapOutcome,
    RoadmapPhaseTiming, RoadmapRecovery, RoadmapSearchContext)


@dataclass
class PlannerSession:
    request: object
    snapshot: object = None
    owner_contact_factor: float = 2.5
    native_world: object = None
    pin_indices: tuple = ()
    policy: object = PRODUCTION_ROADMAP_POLICY
    started: float = field(default_factory=perf_counter)
    state: object = None
    iterator: object = None
    result: object = None
    done: bool = False
    phase: str = "CAPTURE"
    timings: list = field(default_factory=list)

    def step(self):
        if self.done: return self.result
        tick = perf_counter()
        if self.iterator is None: self.iterator = _plan_steps(self)
        try: self.phase = next(self.iterator)
        except StopIteration as stop: self.result, self.done = stop.value, True
        except (OSError, AttributeError) as error: _fail(self, RoadmapOutcome.BACKEND_UNAVAILABLE, str(error))
        except ValueError as error: _fail(self, RoadmapOutcome.INVALID_CONFIGURATION, str(error))
        self.timings.append(RoadmapPhaseTiming(self.phase, 1000*(perf_counter()-tick)))
        if self.done: _complete(self)
        return self.result

    def cancel(self, superseded=False):
        if self.done: return
        reason = RoadmapOutcome.SUPERSEDED if superseded else RoadmapOutcome.CANCELLED
        _fail(self, reason, reason.value.lower()); _complete(self)


def _fail(session, reason, message):
    termination = getattr(p.V2Termination, reason.value, p.V2Termination.INVALID_CONFIGURATION)
    session.result = replace(p._failed(termination, message, session.started), failure_reason=reason.value)
    session.done = True
    if session.iterator is not None: session.iterator.close()


def _complete(session):
    context = None if session.state is None else session.state.search_context
    diag = replace(session.result.diagnostics, phase_timings=tuple(session.timings),
        attempts=tuple(context.attempts) if context else (), recoveries=tuple(context.recoveries) if context else ())
    session.result = replace(session.result, diagnostics=diag)
    if context: context.release()
    session.state = session.iterator = session.snapshot = session.native_world = session.request = None
    session.phase = "DONE"


def _plan_steps(session):
    issue = p._configuration_issue(session.request) or p._pin_layout_issue(session.request, session.pin_indices)
    if issue: return _failure_result(session, RoadmapOutcome.INVALID_CONFIGURATION, issue)
    if not p.collision_backend_status().available:
        return _failure_result(session, RoadmapOutcome.BACKEND_UNAVAILABLE, "native collision backend unavailable")
    session.state = p._v43_state(session.request, session.snapshot, session.owner_contact_factor,
                                 session.native_world, session.pin_indices)
    session.state.search_context = RoadmapSearchContext()
    yield "CAPTURE"
    invalid = p._invalid_anchor(session.state)
    if invalid: return _failure_result(session, RoadmapOutcome.INVALID_ATTACHMENT, invalid)
    yield "ANCHOR_PREFLIGHT"
    routes = yield from _span_steps(session)
    yield "HANDOFF"
    return _finish(session, routes)


def _failure_result(session, reason, message):
    termination = getattr(p.V2Termination, reason.value)
    result = (p._failed(termination, message, session.started) if session.state is None else
              p._failed_with_state(session.state, termination, message, session.started))
    return replace(result, failure_reason=reason.value)


def _finish(session, routes):
    result = p._finish_plan(session.state, routes, session.started)
    if routes is None:
        return replace(result, failure_reason=session.state.search_context.outcome.value,
            message="no route found in the searched candidate graph")
    reason = "" if result.succeeded else (RoadmapOutcome.HANDOFF_COUNT_FAILED.value
        if "cannot fit" in result.message else RoadmapOutcome.HANDOFF_VALIDATION_FAILED.value)
    return replace(result, failure_reason=reason)


def _span_steps(session):
    state = session.state; anchors = tuple(state.request.anchors); routes = []
    count = len(anchors) - int(not p._cyclic(state.request))
    for index in range(count):
        state.search_context.start_span(index)
        route = yield from _pair_steps(session, anchors[index], anchors[(index+1) % len(anchors)])
        if route is None: return None
        routes.append(route); state.search_context.release()
    return tuple(routes)


def _pair_steps(session, start, end):
    state = session.state
    clear = p._edge_clear(state, start.point, end.point, start.owner_id, end.owner_id)
    yield "DIRECT"
    if clear: return p._direct_segment(start, end)
    owner = str(start.owner_id or "") if start.owner_id == end.owner_id else ""
    surface = p._projected_surface_route(state, start, end, owner) if owner else None
    yield "SURFACE_BRIDGE"
    if surface is None: surface = p._surface_route(state, start, end)
    yield "SURFACE_MESH"
    if surface is not None: return surface
    route = yield from _roadmap_steps(session, start, end)
    return p._roadmap_segment(route) if route is not None else None


def _roadmap_steps(session, start, end):
    state = session.state
    for strategy, points, graph in _ordinary_graphs(state, start, end):
        yield "ORDINARY_PREPARATION"
        route = _search(state, strategy, points, graph, start, end)
        yield "ORDINARY_SEARCH"
        if route is not None:
            route = _check_route(state, route, start, end, strategy.startswith("EXIT"))
            if route is not None: return route
        yield "CORRIDOR_VALIDATION"
    if not session.policy.expanded or state.search_context.last_graph is None: return None
    return (yield from _expanded_steps(session, start, end))


def _ordinary_graphs(state, start, end):
    points = p._compatibility_candidates(state, start, end); values = np.asarray(points)
    graph = p._complete_neighbors(len(points)) if len(points) <= 48 else p._neighbor_rows(values, True)
    yield "COMPATIBILITY", points, graph
    for dense in (False, True):
        points = p._roadmap_candidates(state, start, end, dense)
        yield "DENSE" if dense else "SPARSE", points, p._neighbor_rows(np.asarray(points), dense)
    yield from _exit_graphs(state, start, end)


def _exit_graphs(state, start, end):
    base = p._roadmap_candidates(state, start, end, True); neighbors = p._neighbor_rows(np.asarray(base), True)
    for oblique in (False, True):
        exits = p.anchor_access_candidates(state, start, end, p._batch_edge_states, oblique)
        points = p.append_access_points(base, exits)
        if len(points) == len(base): continue
        graph = p.append_access_neighbors(points, neighbors, p._DENSE_NEIGHBORS)
        graph = p._checked_anchor_neighbors(state, points, graph, start, end)
        yield "EXIT_OBLIQUE" if oblique else "EXIT_NORMAL", points, graph


def _search(state, strategy, points, graph, start, end):
    context = state.search_context; context.remember(points, graph)
    state.candidate_nodes = max(state.candidate_nodes, len(points))
    path, result = state.native_world.lazy_path(np.asarray(points), graph, start.owner_id, end.owner_id,
        p._state_contact_span(state), p._radius(state)-p._slack(state))
    p._absorb_native_search(state, result)
    outcome = (RoadmapOutcome.SUCCESS, RoadmapOutcome.GRAPH_DISCONNECTED,
               RoadmapOutcome.SEARCH_BUDGET_EXHAUSTED)[result.status]
    if not len(path) and outcome is RoadmapOutcome.SUCCESS: outcome = RoadmapOutcome.GRAPH_DISCONNECTED
    context.attempts.append(RoadmapAttempt(context.span, strategy, outcome, len(points), sum(map(len, graph)),
        result.searches, result.tested, result.search_ms, result.collision_ms))
    return tuple(points[int(i)] for i in path) if outcome is RoadmapOutcome.SUCCESS else None


def _check_route(state, route, start, end, validate):
    if validate and not p._route_clear(state, route, start.owner_id, end.owner_id):
        rows = state.search_context.attempts
        rows[-1] = replace(rows[-1], outcome=RoadmapOutcome.CORRIDOR_VALIDATION_FAILED)
        return None
    return p._shortcut_route(state, route, start.owner_id, end.owner_id)


def _expanded_steps(session, start, end):
    state = session.state; context = state.search_context; trigger = context.outcome
    existing, original = context.last_graph; timings = []; prepare = session.policy.preparation or prep.NATIVE_PREPARATION
    points = yield from _pool_steps(state, start, end, existing, prepare, timings)
    tick = perf_counter(); graph = prepare.neighbors(points, original, 48)
    timings.append(("neighbors_ms", 1000*(perf_counter()-tick))); yield "EXPANDED_NEIGHBORS"
    checked = yield from _timed_steps(prepare.anchors(state, points, graph, start, end), "anchors_ms", timings)
    if session.policy.observe_graph: session.policy.observe_graph(context.span, points, graph, checked)
    tick = perf_counter(); route = _search(state, "EXPANDED", points, checked, start, end)
    timings.append(("search_ms", 1000*(perf_counter()-tick))); yield "EXPANDED_SEARCH"
    tick = perf_counter()
    if route is not None: route = _check_route(state, route, start, end, True)
    timings.append(("corridor_ms", 1000*(perf_counter()-tick)))
    _record_recovery(context, trigger, existing, original, points, timings)
    return route


def _record_recovery(context, trigger, existing, original, points, timings):
    context.recoveries.append(RoadmapRecovery(context.span, trigger, context.outcome, len(existing),
        len(points), sum(map(len, original)), tuple(timings)))


def _timed_steps(iterator, name, timings):
    elapsed = 0.0
    while True:
        tick = perf_counter()
        try: phase = next(iterator)
        except StopIteration as stop:
            timings.append((name, elapsed+1000*(perf_counter()-tick)))
            return stop.value
        elapsed += 1000*(perf_counter()-tick)
        yield phase


def _pool_steps(state, start, end, existing, prepare, timings):
    samples = []; elapsed = 0.0; iterator = iter(prep.shell_samples(state, start, end))
    while True:
        tick = perf_counter()
        try: samples.extend(next(iterator))
        except StopIteration: break
        elapsed += 1000*(perf_counter()-tick); yield "EXPANDED_SAMPLES"
    timings.append(("generation_ms", elapsed)); tick = perf_counter()
    combined = prepare.unique(existing, samples)
    timings.append(("dedup_ms", 1000*(perf_counter()-tick))); yield "EXPANDED_DEDUP"
    kept = []; elapsed = 0.0
    for first in range(len(existing), len(combined), 512):
        tick = perf_counter(); kept.extend(prep.valid_points(state, combined, first, min(first+512, len(combined))))
        elapsed += 1000*(perf_counter()-tick); yield "EXPANDED_POINT_VALIDATION"
    timings.append(("point_validation_ms", elapsed)); return (*existing, *kept)
