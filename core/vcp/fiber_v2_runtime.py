"""Opt-in Blender capture adapter for the pure-data Fiber V2 engine."""

from collections import OrderedDict
from dataclasses import dataclass, field
from hashlib import blake2b
from time import perf_counter

import numpy as np
from mathutils import Vector

from ..deps.runtime_trace import current_request_telemetry, telemetry_slice, telemetry_timing
from ..scp_runtime.surface import build_mesh_collision_data
from .fiber_collision import CollisionOracle
from .fiber_engine import FiberPhase, FiberTermination
from .fiber_modes import is_loop_fiber
from .v2.collision import collision_backend_status
from .v2.contracts import (V2Anchor, V2AnchorRole, V2ArrayColliderSnapshot,
                           V2CollisionPolicy, V2Quality, V2Request,
                           V2ResolvedTolerances, V2Settings, V2Termination,
                           V2Topology)
from .v2.production import V2_PRODUCTION_VERSION, begin_v2


_CAPTURE_LIMIT = 128
_CAPTURE_BYTES_LIMIT = 256 * 1024 * 1024
_CAPTURE_CACHE = OrderedDict()


@dataclass
class V2RuntimeSession:
    solver: object
    root: object
    fiber: object
    scene: object
    depsgraph: object
    quality: str
    engine: str = "V2"
    engine_version: str = V2_PRODUCTION_VERSION
    solver_version: int = 2
    core_factory: object = None
    checkpoint_steps: int = 0
    anchors: list = field(default_factory=list)
    params: dict = field(default_factory=dict)
    oracle: object = None
    preview: list = field(default_factory=list)
    colliders: list = field(default_factory=list)
    source_colliders: tuple = ()
    capture_index: int = 0
    package: object = None
    core_session: object = None
    request: object = None
    warm_key: tuple = ()
    warm_seed: tuple = ()
    invalid_reason: str = ""
    runtime_error: str = ""
    termination_reason: str = ""
    done: bool = False
    generation: int = 0
    phase: str = FiberPhase.COLLIDERS.value
    elapsed_ms: float = 0.0
    telemetry: object = None
    selection: object = None
    loop: bool = False

    def step(self, time_budget_ms=12.0):
        started = perf_counter()
        deadline = started + max(0.0, float(time_budget_ms)) / 1000.0
        if not self.done and self.capture_index < len(self.source_colliders):
            _advance_capture(self, deadline)
        if not self.done and self.capture_index >= len(self.source_colliders):
            _advance_solve(self, deadline)
        elapsed = _elapsed(started); self.elapsed_ms += elapsed
        telemetry_slice(elapsed, self.phase, self.telemetry)
        telemetry_timing(f"progressive.{self.phase}", elapsed, self.telemetry)
        return self.result()

    def result(self):
        from .fiber_progressive import FiberSolveResult
        if self.package is None:
            error = self.invalid_reason or self.runtime_error
            return FiberSolveResult(points=list(self.preview), done=self.done, invalid_reason=error,
                                    termination_reason=self.termination_reason, engine=self.engine,
                                    engine_version=self.engine_version,
                                    backend_version=collision_backend_status().version,
                                    selection=self.selection, display_mode=_display_mode(self),
                                    validated=_preview_validated(self))
        return _solve_result(self, FiberSolveResult)

    def cancel(self):
        cancel = getattr(self.core_session, "cancel", None)
        if callable(cancel): cancel()
        self.done = True; self.source_colliders = (); self.colliders = []
        self.oracle = self.depsgraph = None

    @property
    def pending_native_sweep(self):
        core = self.core_session
        return None if core is None else getattr(core, "pending_native_sweep", None)


def begin_v2_runtime(solver, root, fiber, scene, depsgraph, quality, selection):
    from .fiber_authority import capture_session
    from .free_path import require_controlled
    require_controlled(fiber)
    session = capture_session(V2RuntimeSession(solver, root, fiber, scene, depsgraph, _quality(quality)))
    session.core_factory = begin_v2
    session.selection = selection
    session.telemetry = current_request_telemetry()
    _initialize(session)
    return session


def begin_v3_runtime(solver, root, fiber, scene, depsgraph, quality, selection):
    from .fiber_authority import capture_session
    from .free_path import require_controlled
    require_controlled(fiber)
    from .v3.production import V3_PRODUCTION_VERSION, begin_v3
    session = capture_session(V2RuntimeSession(solver, root, fiber, scene, depsgraph, _quality(quality)))
    session.engine, session.engine_version, session.solver_version = "V3", V3_PRODUCTION_VERSION, 3
    session.warm_key = _v3_warm_key(scene, root, fiber)
    session.core_factory = begin_v3; session.selection = selection
    session.checkpoint_steps = max(0, int(getattr(fiber, "iterations_interactive", 0) or 0))
    session.telemetry = current_request_telemetry(); _initialize(session)
    return session


def _initialize(session):
    if not _backend_ready(session): return
    session.loop = is_loop_fiber(session.fiber)
    _runtime, anchors, issue = _capture_anchors(session)
    if issue or not anchors: return _fail_anchors(session, issue)
    session.anchors = anchors; _initialize_params(session); _initialize_oracle(session)


def _capture_anchors(session):
    method = session.solver._loop_anchors if session.loop else session.solver._open_anchors
    return method(session.root, session.scene, session.depsgraph, session.fiber)


def _fail_anchors(session, issue):
    session.invalid_reason, session.done = str(issue or "Invalid Fiber anchors."), True
    session.termination_reason = FiberTermination.INVALID_ATTACHMENT.value


def _initialize_params(session):
    final_budget = session.quality == "FINAL" or session.engine == "V3"
    session.params = session.solver._runtime_params(session.fiber, final_budget)
    session.params["solver_version"], session.params["segment_collisions"] = session.solver_version, True
    _initialize_warm(session)


def _initialize_warm(session):
    session.warm_seed = _prepared_v3_warm_seed(session) if session.engine == "V3" else ()
    source = session.warm_seed or tuple(tuple(row.point) for row in session.anchors)
    session.preview = [Vector(row) for row in source]


def _initialize_oracle(session):
    from .attachment_surface import support_keys
    session.oracle = CollisionOracle(session.root, session.scene, session.depsgraph,
                                     session.params["margin"], session.solver.surface_offset, support_keys(session.fiber))
    _attach_sources(session)


def _prepared_v3_warm_seed(session):
    from .v3.warm import prepare_v3_warm_seed
    status = collision_backend_status()
    return prepare_v3_warm_seed(session.warm_key, bool(session.fiber.use_warm_start),
        session.params["node_count"], session.anchors, session.engine_version, status.version,
        cyclic=session.loop)


def _backend_ready(session):
    status = collision_backend_status()
    if status.available:
        return True
    session.invalid_reason = status.message or "V2 collision backend unavailable."
    session.termination_reason = FiberTermination.BACKEND_UNAVAILABLE.value
    session.done = True
    return False


def _attach_sources(session):
    session.solver._attach_cache_signature(
        session.root, session.scene, session.fiber, session.anchors, session.params,
        session.oracle, session.quality, session.loop)
    session.source_colliders = tuple(session.oracle.colliders())


def _advance_capture(session, deadline):
    while session.capture_index < len(session.source_colliders):
        _capture_one(session)
        if perf_counter() >= deadline:
            return


def _capture_one(session):
    index = session.capture_index; source = session.source_colliders[index]
    try:
        row = _capture_collider(source, index)
        if row is not None:
            session.colliders.append(row)
    except Exception as error:
        session.runtime_error, session.done = str(error), True
    session.capture_index += 1


def _capture_collider(source, index):
    key = _capture_key(source, index); cached = _CAPTURE_CACHE.get(key)
    if cached is not None:
        _CAPTURE_CACHE.move_to_end(key); return cached
    surface = build_mesh_collision_data(source["obj"], source["depsgraph"])
    if not surface or not surface.get("triangles"): return None
    value = _captured_snapshot(source, surface, index)
    return _store_capture(key, value)


def _captured_snapshot(source, surface, index):
    local = np.asarray(surface["verts_local"], dtype=np.float64)
    triangles = np.asarray(surface["triangles"], dtype=np.int64); matrix = _capture_matrix(source)
    vertices = _world_vertices(source, local)
    owner = str(source.get("sid", "") or ""); generation = tuple(map(str, source.get("stamp", ())))
    topology = (owner, str(len(local)), str(len(triangles)), _topology_digest(triangles))
    geometry = (str(len(local)), _geometry_digest(local))
    return V2ArrayColliderSnapshot(f"{owner}:{index}", owner, vertices, triangles, generation,
        matrix, topology, geometry)


def _world_vertices(source, local):
    obj = source["obj"].evaluated_get(source["depsgraph"]);matrix = obj.matrix_world
    return np.asarray(tuple(tuple(matrix @ Vector(row)) for row in local), dtype=np.float64)


def _capture_matrix(source):
    obj = source["obj"].evaluated_get(source["depsgraph"])
    return np.asarray([[float(value) for value in row] for row in obj.matrix_world], dtype=np.float64)


def _topology_digest(triangles):
    return blake2b(np.ascontiguousarray(triangles).tobytes(), digest_size=12).hexdigest()


def _geometry_digest(vertices):
    return blake2b(np.ascontiguousarray(vertices).tobytes(), digest_size=12).hexdigest()


def _capture_key(source, index):
    backend = collision_backend_status().version
    return (backend, str(source.get("sid", "") or ""), int(index), repr(source.get("stamp", ())))


def _store_capture(key, value):
    _CAPTURE_CACHE[key] = value; _CAPTURE_CACHE.move_to_end(key)
    _trim_capture_cache()
    return value


def _trim_capture_cache():
    while len(_CAPTURE_CACHE) > _CAPTURE_LIMIT or _capture_bytes() > _CAPTURE_BYTES_LIMIT:
        _CAPTURE_CACHE.popitem(last=False)


def _capture_bytes():
    return sum(row.vertices.nbytes + row.triangles.nbytes for row in _CAPTURE_CACHE.values())


def clear_v2_runtime_capture_cache():
    _CAPTURE_CACHE.clear()


def v2_runtime_capture_cache_stats():
    return {"entries": len(_CAPTURE_CACHE), "bytes": _capture_bytes(),
            "entry_limit": _CAPTURE_LIMIT, "byte_limit": _CAPTURE_BYTES_LIMIT}


def _advance_solve(session, deadline):
    _solve(session)
    while not session.done and perf_counter() < deadline and _planner_batches_pending(session):
        _solve(session)


def _planner_batches_pending(session):
    planner = getattr(session.core_session, "planner_session", None)
    return planner is not None and not planner.done


def _solve(session):
    session.phase = FiberPhase.LOCAL_STEP.value
    if session.core_session is None:
        _begin_core(session); return
    try:
        session.package = session.core_session.step()
    except Exception as error:
        session.runtime_error = str(error)
        session.termination_reason = FiberTermination.UNSAFE_OUTPUT.value
    _update_core_runtime(session)


def _begin_core(session):
    try:
        session.core_session = _start_core(session)
    except Exception as error:
        session.runtime_error, session.done = str(error), True
    _update_core_runtime(session)


def _start_core(session):
    factory = session.core_factory or begin_v2
    values = dict(preview=session.quality != "FINAL")
    if session.engine == "V3": values["checkpoint_steps"] = session.checkpoint_steps
    session.request = _request(session)
    return factory(session.request, **values)


def _update_core_runtime(session):
    core = session.core_session
    if core is None:
        session.generation += 1; session.phase = FiberPhase.DONE.value; return
    if core is not None and len(core.points): session.preview = [Vector(row) for row in core.points]
    session.generation += 1; session.done = bool(core is not None and core.done)
    session.phase = _core_phase(core)
    if session.done: session.package = core.package


def _core_phase(core):
    if core is None or core.done: return FiberPhase.DONE.value
    return FiberPhase.CONTACTS.value if core.infeasible else FiberPhase.GLOBAL_STEP.value


def _display_mode(session):
    core = session.core_session
    return "SOLVING_INFEASIBLE" if core is not None and core.infeasible and not core.done else ""


def _preview_validated(session):
    core = session.core_session
    return bool(core is not None and not core.infeasible)


def _request(session):
    quality = V2Quality.FINAL if session.quality == "FINAL" else V2Quality.INTERACTIVE
    anchors = tuple(_anchor(row, index, len(session.anchors), session.loop)
                    for index, row in enumerate(session.anchors))
    topology = V2Topology.CYCLIC if session.loop else V2Topology.OPEN
    settings = V2Settings(topology, quality, session.params["node_count"],
                          session.params["iterations"], session.params["shorten_strength"],
                          session.params["bend_strength"], 1.0)
    status = collision_backend_status()
    policy = V2CollisionPolicy(session.params["margin"], backend_version=status.version)
    return _request_value(session, settings, policy, anchors)


def _request_value(session, settings, policy, anchors):
    token = max(1, int(session.fiber.get("af_fiber_request_token", 0) or 0) + 1)
    revision = repr(session.params.get("_cache_signature", ()))
    axis = _axis_vector(getattr(session.fiber, "symmetry_axis", "X"))
    origin = tuple(float(value) for value in session.fiber.symmetry_origin)
    tolerances = _tolerances(session.colliders, policy.collision_radius, settings.quality)
    return V2Request(token, _runtime_id(session.scene), _runtime_id(session.root), revision,
                     settings, tolerances, policy, anchors, tuple(session.colliders),
                     str(session.fiber.symmetry_mode), axis, origin,
                     warm_seed=session.warm_seed,
                     engine_version=session.engine_version)


def _anchor(anchor, index, count, cyclic=False):
    if cyclic: return V2Anchor(tuple(anchor.point), str(anchor.owner_id or ""),
                               V2AnchorRole.LOOP, index)
    role = V2AnchorRole.TOUCH
    role = V2AnchorRole.ENDPOINT_A if index == 0 else role
    role = V2AnchorRole.ENDPOINT_B if index + 1 == count else role
    return V2Anchor(tuple(anchor.point), str(anchor.owner_id or ""), role, index)


def _tolerances(colliders, radius, quality):
    from .v2.scales import resolve_tolerances
    return resolve_tolerances(colliders, radius, quality)


def _bounds(colliders):
    if not colliders:
        return None, None, 1.0
    lows = np.asarray([row.vertices.min(axis=0) for row in colliders])
    highs = np.asarray([row.vertices.max(axis=0) for row in colliders])
    coordinate = max(float(np.max(np.abs(lows))), float(np.max(np.abs(highs))))
    return lows.min(axis=0), highs.max(axis=0), coordinate


def _solve_result(session, result_type):
    if _planner_preview_requested(session):
        return result_type(**_planner_result_values(session))
    result, trace = session.package.result, session.package.trace
    diagnostics = result.diagnostics
    penetration = max(float(diagnostics.node_clearance_residual),
                      float(diagnostics.edge_clearance_residual))
    values = _result_values(session, result, trace, penetration)
    return result_type(**values)


def _planner_preview_requested(session):
    return bool(getattr(session.fiber, "preview_planner_route", False) and
                getattr(session.package, "planner", None) is not None)


def _planner_result_values(session):
    planner, trace = session.package.planner, session.package.trace
    succeeded = bool(getattr(planner, "succeeded", False))
    reason = FiberTermination.PLANNER_PREVIEW.value if succeeded else planner.termination.value
    points = [Vector(row) for row in planner.reference] if succeeded else []
    error = "" if succeeded else str(planner.message or reason)
    return dict(points=points, done=True, converged=False, invalid_reason=error,
                mode=planner.mode.value, planner_ms=float(getattr(trace, "planner_ms", 0.0)),
                active_count=len(session.colliders), termination_reason=reason,
                validated=succeeded, engine_version=session.engine_version,
                diagnostics=planner.diagnostics, telemetry=session.telemetry, engine=session.engine,
                backend_version=collision_backend_status().version, selection=session.selection)


def _result_values(session, result, trace, penetration):
    termination = result.termination
    values = dict(points=[Vector(row) for row in result.points], done=True,
                  converged=termination is V2Termination.CONVERGED,
                  stalled=termination is V2Termination.STALLED,
                  blocked=termination is V2Termination.BLOCKED,
                  invalid_reason=_result_error(result), mode=result.route_branch,
                  planner_ms=float(getattr(trace, "planner_ms", 0.0)),
                  refine_ms=max(0.0, session.elapsed_ms - float(getattr(trace, "planner_ms", 0.0))),
                  active_count=len(session.colliders), max_disp=float(result.diagnostics.fixed_point_residual),
                  max_pen=penetration, termination_reason=termination.value,
                  validated=bool(result.validated), engine_version=result.engine_version,
                  diagnostics=result.diagnostics, telemetry=session.telemetry)
    values.update(engine=session.engine, backend_version=result.backend_version,
                  selection=session.selection)
    return values


def _result_error(result):
    failures = {V2Termination.INVALID_ATTACHMENT, V2Termination.INVALID_CONFIGURATION,
                V2Termination.UNSAFE_OUTPUT, V2Termination.BACKEND_UNAVAILABLE}
    return str(result.message or result.termination.value) if result.termination in failures else ""


def retain_v3_warm_state(session, result=None):
    from .fiber_authority import session_owned
    if not session_owned(session): return False
    if getattr(session, "engine", "") != "V3": return False
    if session.request is None or not session.warm_key: return False
    if result is not None and not bool(getattr(result, "validated", False)): return False
    points = _v3_warm_points(session, result)
    if not points: return False
    from .v3.cyclic import v3_reference
    from .v3.warm import store_v3_warm_state
    pins = tuple(getattr(session.core_session, "pins", ()) or v3_reference(session.request)[1])
    return store_v3_warm_state(session.warm_key, points, pins, session.request.anchors,
        session.engine_version, collision_backend_status().version, cyclic=session.loop)


def clear_v3_runtime_warm_cache(scene=None, root=None, fiber_ids=None):
    from .v3.warm import clear_v3_warm_states
    scene_id = None if scene is None else _runtime_id(scene)
    root_id = None if root is None else _runtime_id(root)
    clear_v3_warm_states(scene_id, root_id, fiber_ids)


def _v3_warm_points(session, result):
    if result is not None:
        numeric = getattr(getattr(session, "package", None), "result", None)
        points = tuple(getattr(numeric, "points", ()) or ())
        return points or tuple(getattr(result, "points", ()) or ())
    core = session.core_session
    if core is None or not tuple(getattr(core, "spans", ()) or ()): return ()
    if bool(getattr(core, "infeasible", True)): return ()
    return tuple(tuple(row) for row in getattr(core, "points", ()))


def _v3_warm_key(scene, root, fiber):
    return _runtime_id(scene), _runtime_id(root), _runtime_id(fiber), str(fiber.id or "")


def _axis_vector(value):
    return {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0),
            "Z": (0.0, 0.0, 1.0)}.get(str(value or "X"), (1.0, 0.0, 0.0))


def _runtime_id(value):
    uid = int(getattr(value, "session_uid", 0) or 0)
    try:
        return str(uid or int(value.as_pointer()))
    except Exception:
        return str(uid or id(value))


def _quality(value):
    return "FINAL" if str(value or "").upper() in {"BAKE", "FINAL"} else "INTERACTIVE"


def _elapsed(started):
    return 1000.0 * (perf_counter() - started)
