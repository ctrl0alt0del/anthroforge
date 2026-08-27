from dataclasses import dataclass, field
from time import perf_counter

from ..deps.runtime_trace import (current_request_telemetry, telemetry_count,
                                  telemetry_fiber_engine, telemetry_slice,
                                  telemetry_timing)
from .fiber_collision import CollisionOracle
from .fiber_engine import FiberPhase, FiberTermination
from .fiber_loop import loop_pin_targets
from .fiber_microbatch import (
    advance_contacts, advance_global, advance_line_search, clear_iteration,
    iteration_result, start_iteration,
)
from .fiber_modes import is_loop_fiber
from .fiber_engine_selection import FiberEngineKind
from .fiber_engine_registry import (adapter_for_selection, selected_backend_status,
                                    selection_for_fiber)
from .fiber_planner import DIRECT, LOCAL_FALLBACK, ROADMAP
from .fiber_planner_progressive import begin_progressive_plan, advance_progressive_plan
from .fiber_validation import (
    advance_validation, begin_final_validation, begin_post_validation,
)


_SLICE_HEADROOM_MS = 3.0


@dataclass
class FiberSolveResult:
    points: list = field(default_factory=list)
    done: bool = False
    converged: bool = False
    stalled: bool = False
    blocked: bool = False
    invalid_reason: str = ""
    mode: str = LOCAL_FALLBACK
    planner_ms: float = 0.0
    refine_ms: float = 0.0
    active_count: int = 0
    max_disp: float = 0.0
    max_pen: float = 0.0
    termination_reason: str = ""
    validated: bool = False
    engine_version: str = ""
    diagnostics: object = None
    telemetry: object = None
    engine: str = "V1"
    backend_version: str = ""
    selection: object = None
    display_mode: str = ""


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
    blocked: bool = False
    max_disp: float = 0.0
    max_pen: float = 0.0


@dataclass
class FiberSolveSession:
    solver: object
    root: object
    fiber: object
    scene: object
    depsgraph: object
    quality: str = "FINAL"
    oracle: object = None
    anchors: list = field(default_factory=list)
    guides: list = field(default_factory=list)
    params: dict = field(default_factory=dict)
    preview: list = field(default_factory=list)
    preview_validated: bool = False
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
    phase: str = FiberPhase.CAPTURE.value
    termination_reason: str = ""
    planner_work: object = None
    iteration_work: object = None
    validation_work: object = None
    selection: object = None

    def step(self, time_budget_ms=12.0):
        if self.done:
            return self.result()
        started, planner_before = perf_counter(), _planner_elapsed(self)
        budget = max(0.0, float(time_budget_ms) - _SLICE_HEADROOM_MS)
        deadline = started + budget / 1000.0
        _step_until_deadline(self, deadline)
        elapsed = (perf_counter() - started) * 1000.0
        planner_delta = max(0.0, _planner_elapsed(self) - planner_before)
        self.refine_ms += max(0.0, elapsed - planner_delta)
        telemetry_slice(elapsed, self.phase, self.telemetry)
        telemetry_timing(f"progressive.{self.phase}", elapsed, self.telemetry)
        return self.result()

    def result(self):
        level = self.level
        points = self.preview if level is None else level.nodes
        disp = 0.0 if level is None else level.max_disp
        pen = 0.0 if level is None else level.max_pen
        blocked = False if level is None else level.blocked
        reason = self.termination_reason or _termination_reason(self)
        return FiberSolveResult(
            points=_copy_points(points), done=self.done, converged=self.converged,
            stalled=self.stalled, blocked=blocked, invalid_reason=self.invalid_reason,
            mode=self.mode, planner_ms=self.planner_ms, refine_ms=self.refine_ms,
            active_count=self.active_count, max_disp=disp, max_pen=pen,
            termination_reason=reason,
            validated=bool(self.done and self.converged and pen < 1.0e-5),
            engine="V1", engine_version="fiber-v1-legacy-1", selection=self.selection)


def begin_fiber_solve(solver, root, fiber, scene, depsgraph, quality="FINAL",
                      selection=None, explicit_engine=None):
    telemetry_count("fiber_solves")
    selection = selection or selection_for_fiber(fiber, explicit_engine)
    adapter, backend = adapter_for_selection(selection), selected_backend_status(selection)
    telemetry_fiber_engine(selection, getattr(fiber, "solver_version", 1),
                           engine_version="" if adapter is None else adapter.version,
                           backend_version="" if backend is None else backend.version)
    return _begin_selected(solver, root, fiber, scene, depsgraph, quality, selection)


def _begin_selected(solver, root, fiber, scene, depsgraph, quality, selection):
    if not selection.valid:
        return _invalid_engine_session(solver, root, fiber, scene, depsgraph, quality, selection)
    if selection.actual in {FiberEngineKind.V2, FiberEngineKind.V3}:
        return _begin_numeric(solver, root, fiber, scene, depsgraph, quality, selection)
    session = FiberSolveSession(solver, root, fiber, scene, depsgraph, _quality(quality))
    session.selection = selection
    session.telemetry = current_request_telemetry()
    session.loop = is_loop_fiber(fiber)
    session = _init_loop(session) if session.loop else _init_open(session)
    if not session.done:
        _init_colliders(session)
    return session


def _begin_numeric(solver, root, fiber, scene, depsgraph, quality, selection):
    from .fiber_v2_runtime import begin_v2_runtime, begin_v3_runtime
    factory = begin_v3_runtime if selection.actual is FiberEngineKind.V3 else begin_v2_runtime
    return factory(solver, root, fiber, scene, depsgraph, quality, selection)


def _invalid_engine_session(solver, root, fiber, scene, depsgraph, quality, selection):
    session = FiberSolveSession(solver, root, fiber, scene, depsgraph, _quality(quality))
    session.selection = selection
    _finish_invalid(session, selection.error)
    return session


def _init_open(session):
    _init_common(session, session.solver._open_anchors)
    if session.done:
        return session
    if _invalid_configuration(session):
        return session
    session.params = session.solver._with_endpoint_owners(session.params, session.anchors)
    session.preview = [anchor.point.copy() for anchor in session.anchors]
    session.phase = FiberPhase.COLLIDERS.value
    return session


def _init_loop(session):
    _init_common(session, session.solver._loop_anchors)
    if session.done:
        return session
    if _invalid_configuration(session):
        return session
    session.preview = [anchor.point.copy() for anchor in session.anchors]
    session.phase = FiberPhase.COLLIDERS.value
    return session


def _invalid_configuration(session):
    issue = session.solver._configuration_issue(session.anchors, session.params)
    if issue:
        _finish_invalid(session, issue)
    return bool(issue)


def _init_common(session, anchor_fn):
    session.phase = FiberPhase.CAPTURE.value
    _runtime, anchors, issue = anchor_fn(session.root, session.scene, session.depsgraph, session.fiber)
    if issue:
        _finish_invalid(session, issue)
        return
    session.anchors = anchors
    session.params = session.solver._runtime_params(session.fiber, _is_final(session))
    session.params["solver_version"] = 1
    session.params["segment_collisions"] = bool(
        getattr(session.fiber, "use_segment_collisions", False))


def _init_colliders(session):
    session.oracle = CollisionOracle(session.root, session.scene, session.depsgraph,
                                     session.params["margin"], session.solver.surface_offset)
    session.solver._attach_cache_signature(
        session.root, session.scene, session.fiber, session.anchors, session.params,
        session.oracle, session.quality, session.loop)
    session.phase = FiberPhase.PLAN.value


def _init_open_planner(session):
    session.guides = session.solver._planner_guides(
        session.fiber, session.oracle, session.anchors)
    session.planner_work = begin_progressive_plan(
        session.oracle, session.anchors, allow_dense=_is_final(session))


def _finish_open_plan(session, result):
    session.preview = _copy_points(result.points)
    session.mode, session.planned_ids = result.mode, result.active_ids
    session.solver._set_planned_colliders(session.oracle, result.active_ids)
    if session.solver._preview_planner_route(session.fiber):
        _finish_planner_preview(session)
        return
    if _can_finish_direct(session):
        _finish_direct(session)
        return
    _init_open_levels(session)


def _finish_planner_preview(session):
    valid = session.mode != LOCAL_FALLBACK
    session.done, session.converged = True, valid
    session.preview_validated = valid
    session.active_count = len(session.planned_ids)
    session.solver._store_status(session.fiber, valid, 0.0, 0.0)
    session.solver._store_metrics(session.fiber, session.mode, session.planner_ms,
                                  0.0, session.active_count)
    session.generation += 1
    session.phase = FiberPhase.DONE.value
    reason = FiberTermination.PLANNER_PREVIEW if valid else FiberTermination.NO_FEASIBLE_PATH
    session.termination_reason = reason.value


def _plan_loop(session):
    route, mode, planner_ms, planned = session.solver._loop_seed_route(
        session.oracle, session.anchors, _is_final(session))
    session.preview, session.mode = _copy_points(route), mode
    session.planner_ms, session.planned_ids = planner_ms, planned
    _init_loop_level(session)


def _can_finish_direct(session):
    if session.solver._uses_v2(session.params):
        return False
    ready = session.mode == DIRECT and not session.guides and len(session.anchors) == 2
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
    session.route_seed = _route_seed(session)
    minimum = session.solver._route_level_minimum(
        session.params["node_count"], session.anchors, session.route_seed)
    session.counts, session.iterations = session.solver._level_schedule(
        session.params["node_count"], minimum, session.params["iterations"])
    _install_route_preview(session)
    session.phase = FiberPhase.LEVEL_SETUP.value


def _install_route_preview(session):
    count = int(session.params["node_count"])
    _nodes, _pinned, targets = session.solver._build_level_nodes(
        session.fiber, session.anchors, session.guides, count, session.route_seed)
    candidate = session.solver._validated_route_seed(
        session.route_seed, count, session.oracle,
        dict(session.params, pin_owners=session.solver._pin_owners(session.anchors, targets)), targets)
    session.preview = _copy_points(candidate) if candidate else []
    session.preview_validated = bool(candidate)
    session.generation += int(session.preview_validated)


def _route_seed(session):
    if session.mode == ROADMAP or len(tuple(session.preview or ())) > len(session.anchors):
        return _copy_points(session.preview)
    if not session.guides:
        return _copy_points(session.preview)
    return [session.anchors[0].point.copy(), *_copy_points(session.guides),
            session.anchors[-1].point.copy()]


def _start_open_level(session):
    count = session.counts[session.level_index]
    seed = session.route_seed if session.seed is None else session.seed
    nodes, pinned, targets = session.solver._build_level_nodes(
        session.fiber, session.anchors, session.guides, count, seed,
        session.params.get("_cache_signature"))
    params = session.solver._level_params(session.params, session.iterations[session.level_index])
    params["surface_route_seed"] = bool(session.guides)
    params["pin_owners"] = session.solver._pin_owners(session.anchors, targets)
    session.level = _new_level(session, nodes, pinned, targets, params)
    session.generation += 1
    session.phase = FiberPhase.LOCAL_STEP.value


def _init_loop_level(session):
    sig = session.solver._loop_cache_signature(session.anchors, session.params)
    cached = session.solver._cached_loop_result(session.fiber, sig, session.params["node_count"])
    if cached is not None and _finish_cached_loop(session, cached):
        return
    session.phase = FiberPhase.LEVEL_SETUP.value


def _finish_cached_loop(session, cached):
    route = session.preview or [anchor.point.copy() for anchor in session.anchors]
    targets = loop_pin_targets(route, [anchor.point.copy() for anchor in session.anchors], len(cached[0]))
    params = dict(session.params, pin_owners=session.solver._pin_owners(session.anchors, targets))
    points, converged, disp, pen, active = session.solver._validated_loop_cache(
        cached, targets, session.oracle, params)
    if not converged:
        session.solver._discard_loop_exact(session.fiber)
        return False
    session.level = _new_level(session, points, set(targets), targets, params, cyclic=True)
    session.level.max_disp, session.level.max_pen = disp, pen
    session.active_count = max(session.active_count, active)
    _finish_session(session, converged, False)
    return True


def _start_loop_level(session):
    route = session.preview or [anchor.point.copy() for anchor in session.anchors]
    signature = session.params.get("_cache_signature")
    nodes = session.solver._loop_nodes(
        session.fiber, route, session.params["node_count"], signature)
    targets = loop_pin_targets(route, [anchor.point.copy() for anchor in session.anchors], len(nodes))
    session.solver._restore_pins(nodes, targets)
    params = dict(session.params, pin_owners=session.solver._pin_owners(session.anchors, targets))
    session.level = _new_level(session, nodes, set(targets), targets, params, cyclic=True)
    session.generation += 1
    session.phase = FiberPhase.LOCAL_STEP.value


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
        _advance_session(session, deadline)
        ran = True


def _advance_session(session, deadline):
    phase = session.phase
    if phase == FiberPhase.COLLIDERS.value:
        _init_colliders(session)
    elif phase == FiberPhase.PLAN.value:
        _advance_plan(session, deadline)
    elif phase == FiberPhase.LEVEL_SETUP.value:
        _setup_level(session)
    elif phase == FiberPhase.LOCAL_STEP.value:
        start_iteration(session)
    else:
        _advance_iteration_phase(session, deadline)


def _advance_iteration_phase(session, deadline):
    phase = session.phase
    if phase == FiberPhase.GLOBAL_STEP.value:
        advance_global(session)
    elif phase == FiberPhase.CONTACTS.value:
        advance_contacts(session, deadline)
    elif phase == FiberPhase.LINE_SEARCH.value:
        advance_line_search(session)
    elif phase == FiberPhase.ACCEPT.value:
        _advance_accept(session, deadline)
    elif phase == FiberPhase.FINAL_VALIDATE.value:
        _advance_final_validation(session, deadline)


def _advance_plan(session, deadline):
    if session.loop:
        _plan_loop(session)
        return
    if session.planner_work is None:
        _init_open_planner(session)
    if not advance_progressive_plan(session.planner_work, deadline):
        return
    session.planner_ms = session.planner_work.elapsed_ms
    _finish_open_plan(session, session.planner_work.result)


def _setup_level(session):
    _start_loop_level(session) if session.loop else _start_open_level(session)


def _advance_accept(session, deadline):
    if session.validation_work is None:
        payload = iteration_result(session)
        clear_iteration(session)
        session.validation_work = begin_post_validation(session, payload)
    if not advance_validation(session.validation_work, deadline):
        return
    payload, session.validation_work = session.validation_work.result, None
    _finish_accepted_step(session, payload)


def _finish_accepted_step(session, payload):
    _local, _guards, disp, pen, alpha = payload
    _record_step(session.level, disp, pen)
    _check_level_done(session, alpha)


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
    level.blocked = solver._blocked_clear(alpha, level.max_pen, level.params)
    level.stalled = level.iteration >= level.params["min_iters"] and level.stall_count >= 12
    if level.converged or level.stalled or level.blocked or level.iteration >= level.params["iterations"]:
        session.phase = FiberPhase.FINAL_VALIDATE.value
    else:
        session.phase = FiberPhase.LOCAL_STEP.value


def _complete_level(session):
    session.phase = FiberPhase.FINAL_VALIDATE.value
    if session.loop:
        _complete_loop(session)
        return
    _complete_open(session)


def _advance_final_validation(session, deadline):
    if session.validation_work is None:
        session.validation_work = begin_final_validation(session)
    if not advance_validation(session.validation_work, deadline):
        return
    session.validation_work = None
    _finish_validated_level(session)


def _finish_validated_level(session):
    if session.loop or session.level_index + 1 >= len(session.counts):
        _finish_session(session, session.level.converged, session.level.stalled)
        return
    session.seed = _copy_points(session.level.nodes)
    session.level_index += 1
    session.phase = FiberPhase.LEVEL_SETUP.value


def _complete_open(session):
    level = session.level
    level.converged, level.max_disp, level.max_pen = session.solver._finish_open_iterations(
        level.nodes, level.safe, level.first_safe, session.oracle, level.colliders,
        level.params, level.converged, level.max_disp, level.max_pen)
    level.converged, level.max_disp, level.max_pen = session.solver._restore_and_validate_open(
        level.nodes, session.route_seed, session.oracle, level.params, level.targets,
        level.converged, level.max_disp, level.max_pen)
    if session.level_index + 1 >= len(session.counts):
        _finish_session(session, level.converged, level.stalled)
        return
    session.seed, session.level_index = _copy_points(level.nodes), session.level_index + 1
    session.phase = FiberPhase.LEVEL_SETUP.value


def _complete_loop(session):
    level = session.level
    if not level.converged:
        level.converged, level.max_disp, level.max_pen = session.solver._restore_unconverged(
            level.nodes, level.safe, level.first_safe, session.oracle, level.colliders,
            level.params, level.max_disp, level.max_pen, cyclic=True)
    else:
        level.converged, level.max_disp, level.max_pen = session.solver._finish_cyclic_state(
            level.nodes, session.oracle, level.params, True, level.max_disp)
    _finish_session(session, level.converged, level.stalled)


def _finish_session(session, converged, stalled):
    session.done, session.converged, session.stalled = True, bool(converged), bool(stalled)
    level = session.level
    session.solver._store_status(session.fiber, session.converged, level.max_disp, level.max_pen)
    session.solver._store_metrics(session.fiber, session.mode, session.planner_ms,
                                  session.refine_ms, max(session.active_count, len(session.planned_ids)))
    session.generation += 1
    session.phase = FiberPhase.DONE.value
    session.termination_reason = _termination_reason(session)
    return session


def publish_fiber_cache(session, result=None):
    result = result or session.result()
    if not (session.done and result.converged):
        return
    signature = session.params.get("_cache_signature")
    session.solver._store_warm_cache(session.fiber, result.points, signature)
    if session.loop:
        diagnostics = result.converged, result.max_disp, result.max_pen, result.active_count
        session.solver._store_loop_exact_result(
            session.fiber, signature, result.points, diagnostics)


def _finish_invalid(session, issue):
    session.invalid_reason, session.done = str(issue or "Invalid attachment."), True
    session.solver._mark_invalid(session.fiber, session.invalid_reason)
    session.phase = FiberPhase.DONE.value
    session.termination_reason = _invalid_termination(issue)


def _termination_reason(session):
    if session.invalid_reason:
        return _invalid_termination(session.invalid_reason)
    if session.converged:
        return FiberTermination.CONVERGED.value
    if session.level is not None and session.level.blocked:
        return FiberTermination.BLOCKED.value
    if session.stalled:
        return FiberTermination.STALLED.value
    return FiberTermination.BUDGET_EXHAUSTED.value if session.done else ""


def _invalid_termination(issue):
    text = str(issue or "").lower()
    if "legacy attachment" in text:
        return FiberTermination.INVALID_ATTACHMENT.value
    if any(value in text for value in ("anchor", "node", "configuration", "engine")):
        return FiberTermination.INVALID_CONFIGURATION.value
    return FiberTermination.INVALID_ATTACHMENT.value


def _copy_points(points):
    return [point.copy() for point in tuple(points or ())]


def _quality(value):
    return "FINAL" if str(value or "").upper() in {"BAKE", "FINAL"} else "INTERACTIVE"


def _is_final(session):
    return str(session.quality).upper() == "FINAL"


def _planner_elapsed(session):
    work = getattr(session, "planner_work", None)
    return 0.0 if work is None else float(work.elapsed_ms)
