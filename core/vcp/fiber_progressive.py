from dataclasses import dataclass, field
from time import perf_counter

from .fiber_collision import CollisionOracle
from .fiber_loop import loop_pin_targets
from .fiber_modes import is_loop_fiber
from .fiber_planner import DIRECT, LOCAL_FALLBACK, plan_route


@dataclass
class FiberSolveResult:
    points: list = field(default_factory=list)
    done: bool = False
    converged: bool = False
    stalled: bool = False
    invalid_reason: str = ""
    mode: str = LOCAL_FALLBACK
    planner_ms: float = 0.0
    refine_ms: float = 0.0
    active_count: int = 0
    max_disp: float = 0.0
    max_pen: float = 0.0


@dataclass
class FiberLevelState:
    nodes: list
    pinned: object
    targets: dict
    params: dict
    prev_nodes: list
    colliders: list
    safe: object
    first_safe: object
    guards: dict = field(default_factory=dict)
    iteration: int = 0
    stall_count: int = 0
    last_residual: object = None
    converged: bool = False
    stalled: bool = False
    max_disp: float = 0.0
    max_pen: float = 0.0


@dataclass
class FiberSolveSession:
    solver: object
    root: object
    fiber: object
    scene: object
    depsgraph: object
    oracle: object = None
    anchors: list = field(default_factory=list)
    guides: list = field(default_factory=list)
    params: dict = field(default_factory=dict)
    preview: list = field(default_factory=list)
    mode: str = LOCAL_FALLBACK
    planner_ms: float = 0.0
    planned_ids: tuple = ()
    counts: list = field(default_factory=list)
    iterations: list = field(default_factory=list)
    level_index: int = 0
    level: object = None
    route_seed: object = None
    seed: object = None
    loop: bool = False
    done: bool = False
    converged: bool = False
    stalled: bool = False
    invalid_reason: str = ""
    refine_ms: float = 0.0
    active_count: int = 0
    generation: int = 0

    def step(self, time_budget_ms=12.0):
        if self.done:
            return self.result()
        started = perf_counter()
        deadline = started + max(0.0, float(time_budget_ms)) / 1000.0
        _step_until_deadline(self, deadline)
        self.refine_ms += (perf_counter() - started) * 1000.0
        return self.result()

    def result(self):
        level = self.level
        points = self.preview if level is None else level.nodes
        disp = 0.0 if level is None else level.max_disp
        pen = 0.0 if level is None else level.max_pen
        return FiberSolveResult(_copy_points(points), self.done, self.converged, self.stalled,
                                self.invalid_reason, self.mode, self.planner_ms,
                                self.refine_ms, self.active_count, disp, pen)


def begin_fiber_solve(solver, root, fiber, scene, depsgraph):
    session = FiberSolveSession(solver, root, fiber, scene, depsgraph)
    session.loop = is_loop_fiber(fiber)
    return _init_loop(session) if session.loop else _init_open(session)


def _init_open(session):
    _init_common(session, session.solver._open_anchors)
    if session.done:
        return session
    session.params = session.solver._with_endpoint_owners(session.params, session.anchors)
    session.guides = session.solver._planner_guides(session.fiber, session.oracle, session.anchors)
    _plan_open(session)
    if _can_finish_direct(session):
        return _finish_direct(session)
    _init_open_levels(session)
    return session


def _init_loop(session):
    _init_common(session, session.solver._loop_anchors)
    if session.done:
        return session
    route, mode, planner_ms, planned = session.solver._loop_seed_route(session.oracle, session.anchors, True)
    session.preview, session.mode = _copy_points(route), mode
    session.planner_ms, session.planned_ids = planner_ms, planned
    _init_loop_level(session)
    return session


def _init_common(session, anchor_fn):
    _runtime, anchors, issue = anchor_fn(session.root, session.scene, session.depsgraph, session.fiber)
    if issue:
        _finish_invalid(session, issue)
        return
    session.anchors = anchors
    session.params = session.solver._runtime_params(session.fiber, True)
    session.oracle = CollisionOracle(session.root, session.scene, session.depsgraph,
                                     session.params["margin"], session.solver.surface_offset)


def _plan_open(session):
    started = perf_counter()
    result = plan_route(session.oracle, session.anchors, allow_dense=True)
    session.planner_ms = (perf_counter() - started) * 1000.0
    session.preview = _copy_points(result.points)
    session.mode, session.planned_ids = result.mode, result.active_ids


def _can_finish_direct(session):
    ready = session.mode == DIRECT and not session.guides and len(session.preview) >= 2
    return bool(ready and _authored_segments_clear(session))


def _authored_segments_clear(session):
    colliders = session.oracle.colliders()
    for start, end in zip(session.anchors[:-1], session.anchors[1:]):
        owners = (start.owner_id, end.owner_id)
        if not session.oracle.segment_visible(start.point, end.point, owners, colliders):
            return False
    return True


def _finish_direct(session):
    count = int(session.params["node_count"])
    nodes, pinned, targets = session.solver._build_level_nodes(
        session.fiber, session.anchors, (), count, session.preview)
    session.level = _new_level(session, nodes, pinned, targets, session.params)
    session.level.converged = True
    return _finish_session(session, True, False)


def _init_open_levels(session):
    anchor_count = len(session.guides) + 2
    session.counts = session.solver._level_counts(session.params["node_count"], anchor_count)
    session.iterations = session.solver._split_iterations(session.params["iterations"], len(session.counts))
    session.route_seed = _copy_points(session.preview)
    _start_open_level(session)


def _start_open_level(session):
    count = session.counts[session.level_index]
    nodes, pinned, targets = session.solver._build_level_nodes(
        session.fiber, session.anchors, session.guides, count, session.seed)
    params = session.solver._level_params(session.params, session.iterations[session.level_index])
    session.level = _new_level(session, nodes, pinned, targets, params)
    session.generation += 1


def _init_loop_level(session):
    sig = session.solver._loop_cache_signature(session.anchors, session.params)
    cached = session.solver._cached_loop_result(session.fiber, sig, session.params["node_count"])
    if cached is not None:
        session.level = _new_level(session, cached, set(), {}, session.params)
        _finish_session(session, True, False)
        return
    _start_loop_level(session)


def _start_loop_level(session):
    route = session.preview or [anchor.point.copy() for anchor in session.anchors]
    nodes = session.solver._loop_nodes(session.fiber, route, session.params["node_count"])
    targets = loop_pin_targets(route, [anchor.point.copy() for anchor in session.anchors], len(nodes))
    session.solver._restore_pins(nodes, targets)
    session.level = _new_level(session, nodes, set(targets), targets, session.params, cyclic=True)
    session.generation += 1


def _new_level(session, nodes, pinned, targets, params, cyclic=False):
    colliders = session.solver._active_colliders(session.oracle, nodes, params["margin"])
    safe = session.solver._safe_snapshot(nodes, session.oracle, colliders, params,
                                         cyclic=cyclic, skip_ends=not cyclic, pinned=pinned)
    session.active_count = max(session.active_count, len(colliders))
    return FiberLevelState(nodes, pinned, targets, params, _copy_points(nodes),
                           colliders, safe, safe)


def _step_until_deadline(session, deadline):
    ran = False
    while not session.done and (not ran or perf_counter() < deadline):
        _step_loop(session) if session.loop else _step_open(session)
        ran = True


def _step_open(session):
    level, local = session.level, session.solver._collision_context_params(session.level.params)
    level.colliders = session.solver._active_colliders(session.oracle, level.nodes, level.params["margin"])
    next_guards = {}
    disp, pen, alpha = session.solver._open_step(
        level.nodes, level.prev_nodes, level.pinned, level.targets, session.oracle,
        level.colliders, local, level.iteration, level.guards, next_guards)
    _after_step(session, local, next_guards, disp, pen, alpha, False)


def _step_loop(session):
    level, local = session.level, session.solver._collision_context_params(session.level.params)
    level.colliders = session.solver._active_colliders(session.oracle, level.nodes, level.params["margin"])
    next_guards = {}
    disp, pen, alpha = session.solver._cyclic_step(
        level.nodes, level.prev_nodes, level.pinned, level.targets, session.oracle,
        level.colliders, local, level.iteration, level.guards, next_guards)
    _after_step(session, local, next_guards, disp, pen, alpha, True)


def _after_step(session, local, next_guards, disp, pen, alpha, cyclic):
    level = session.level
    level.guards = next_guards if alpha >= 0.999999 else {}
    level.prev_nodes, level.colliders, level.safe = session.solver._post_iteration_state(
        level.nodes, session.oracle, local, level.safe, cyclic=cyclic,
        skip_ends=not cyclic, pinned=level.pinned)
    _record_step(level, disp, pen)
    _check_level_done(session, alpha)


def _record_step(level, disp, pen):
    level.max_disp, level.max_pen = float(disp), float(pen)
    residual = float(disp), float(pen)
    stable = level.last_residual is not None and all(
        abs(value - old) <= 1.0e-9 for value, old in zip(residual, level.last_residual))
    level.stall_count = level.stall_count + 1 if stable else 0
    level.last_residual = residual
    level.iteration += 1


def _check_level_done(session, alpha):
    level, solver = session.level, session.solver
    index = max(0, level.iteration - 1)
    level.converged = solver._iteration_converged(index, level.max_disp, level.max_pen, level.params)
    level.converged = level.converged or solver._blocked_clear(alpha, level.max_pen, level.params)
    level.stalled = level.iteration >= level.params["min_iters"] and level.stall_count >= 12
    if level.converged or level.stalled or level.iteration >= level.params["iterations"]:
        _complete_level(session)


def _complete_level(session):
    if session.loop:
        _complete_loop(session)
        return
    _complete_open(session)


def _complete_open(session):
    level = session.level
    session.solver._finish_open_iterations(
        level.nodes, level.safe, level.first_safe, session.oracle, level.colliders,
        level.params, level.converged, level.max_disp, level.max_pen)
    session.solver._restore_seed_if_needed(level.nodes, session.route_seed, session.oracle, level.params)
    if session.level_index + 1 >= len(session.counts):
        _finish_session(session, level.converged, level.stalled)
        return
    session.seed, session.level_index = _copy_points(level.nodes), session.level_index + 1
    _start_open_level(session)


def _complete_loop(session):
    level = session.level
    if not level.converged:
        session.solver._restore_unconverged(
            level.nodes, level.safe, level.first_safe, session.oracle, level.colliders,
            level.params, level.max_disp, level.max_pen, cyclic=True)
    _finish_session(session, level.converged, level.stalled)


def _finish_session(session, converged, stalled):
    session.done, session.converged, session.stalled = True, bool(converged), bool(stalled)
    level = session.level
    session.solver._store_status(session.fiber, session.converged, level.max_disp, level.max_pen)
    session.solver._store_metrics(session.fiber, session.mode, session.planner_ms,
                                  session.refine_ms, max(session.active_count, len(session.planned_ids)))
    session.solver._cache[session.fiber.id] = _copy_points(level.nodes)
    _store_loop_signature(session)
    session.generation += 1
    return session


def _store_loop_signature(session):
    if session.loop:
        session.solver._store_loop_cache_signature(session.fiber, session.anchors, session.params)


def _finish_invalid(session, issue):
    session.invalid_reason, session.done = str(issue or "Invalid attachment."), True
    session.solver._mark_invalid(session.fiber, session.invalid_reason)


def _copy_points(points):
    return [point.copy() for point in tuple(points or ())]
