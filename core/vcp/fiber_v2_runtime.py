"""Opt-in Blender capture adapter for the pure-data Fiber V2 engine."""

from collections import OrderedDict
from dataclasses import dataclass, field
from time import perf_counter

import numpy as np
from mathutils import Vector

from ..deps.runtime_trace import current_request_telemetry, telemetry_slice, telemetry_timing
from .fiber_collision import CollisionOracle, _collider_surface
from .fiber_engine import FiberPhase, FiberTermination
from .v2.collision import collision_backend_status
from .v2.contracts import (V2Anchor, V2AnchorRole, V2ArrayColliderSnapshot,
                           V2CollisionPolicy, V2Quality, V2Request,
                           V2ResolvedTolerances, V2Settings, V2Termination,
                           V2Topology)
from .v2.production import V2_PRODUCTION_VERSION, solve_v2


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
    anchors: list = field(default_factory=list)
    params: dict = field(default_factory=dict)
    oracle: object = None
    preview: list = field(default_factory=list)
    colliders: list = field(default_factory=list)
    source_colliders: tuple = ()
    capture_index: int = 0
    package: object = None
    invalid_reason: str = ""
    runtime_error: str = ""
    termination_reason: str = ""
    done: bool = False
    generation: int = 0
    phase: str = FiberPhase.COLLIDERS.value
    elapsed_ms: float = 0.0
    telemetry: object = None
    selection: object = None

    def step(self, time_budget_ms=12.0):
        started = perf_counter()
        deadline = started + max(0.0, float(time_budget_ms)) / 1000.0
        if not self.done and self.capture_index < len(self.source_colliders):
            _advance_capture(self, deadline)
        if not self.done and self.capture_index >= len(self.source_colliders):
            _solve(self)
        elapsed = _elapsed(started); self.elapsed_ms += elapsed
        telemetry_slice(elapsed, self.phase, self.telemetry)
        telemetry_timing(f"progressive.{self.phase}", elapsed, self.telemetry)
        return self.result()

    def result(self):
        from .fiber_progressive import FiberSolveResult
        if self.package is None:
            error = self.invalid_reason or self.runtime_error
            return FiberSolveResult(points=list(self.preview), done=self.done, invalid_reason=error,
                                    termination_reason=self.termination_reason, engine="V2",
                                    engine_version=V2_PRODUCTION_VERSION,
                                    backend_version=collision_backend_status().version,
                                    selection=self.selection)
        return _solve_result(self, FiberSolveResult)


def begin_v2_runtime(solver, root, fiber, scene, depsgraph, quality, selection):
    session = V2RuntimeSession(solver, root, fiber, scene, depsgraph, _quality(quality))
    session.selection = selection
    session.telemetry = current_request_telemetry()
    _initialize(session)
    return session


def _initialize(session):
    if not _backend_ready(session):
        return
    _runtime, anchors, issue = session.solver._open_anchors(
        session.root, session.scene, session.depsgraph, session.fiber)
    if issue or not anchors:
        session.invalid_reason, session.done = str(issue or "Invalid Fiber anchors."), True
        session.termination_reason = FiberTermination.INVALID_ATTACHMENT.value
        return
    session.anchors, session.preview = anchors, [row.point.copy() for row in anchors]
    session.params = session.solver._runtime_params(session.fiber, session.quality == "FINAL")
    session.params["solver_version"], session.params["segment_collisions"] = 2, True
    session.oracle = CollisionOracle(session.root, session.scene, session.depsgraph,
                                     session.params["margin"], session.solver.surface_offset)
    _attach_sources(session)


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
        session.oracle, session.quality, False)
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
    surface = _collider_surface(source)
    if not surface or not surface.get("triangles"):
        return None
    vertices = np.asarray([tuple(row) for row in surface["verts_world"]], dtype=np.float64)
    triangles = np.asarray(surface["triangles"], dtype=np.int64)
    owner = str(source.get("sid", "") or "")
    generation = tuple(map(str, source.get("stamp", ())))
    value = V2ArrayColliderSnapshot(f"{owner}:{index}", owner, vertices, triangles, generation)
    return _store_capture(key, value)


def _capture_key(source, index):
    backend = collision_backend_status().version
    return (V2_PRODUCTION_VERSION, backend, str(source.get("sid", "") or ""),
            int(index), repr(source.get("stamp", ())))


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


def _solve(session):
    session.phase = FiberPhase.LOCAL_STEP.value
    try:
        request = _request(session)
        session.package = solve_v2(request, preview=session.quality != "FINAL")
    except Exception as error:
        session.runtime_error = str(error)
        session.termination_reason = FiberTermination.UNSAFE_OUTPUT.value
    session.done, session.generation = True, session.generation + 1
    session.phase = FiberPhase.DONE.value


def _request(session):
    quality = V2Quality.FINAL if session.quality == "FINAL" else V2Quality.INTERACTIVE
    anchors = tuple(_anchor(row, index, len(session.anchors)) for index, row in enumerate(session.anchors))
    settings = V2Settings(V2Topology.OPEN, quality, session.params["node_count"],
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
                     engine_version=V2_PRODUCTION_VERSION)


def _anchor(anchor, index, count):
    role = V2AnchorRole.TOUCH
    role = V2AnchorRole.ENDPOINT_A if index == 0 else role
    role = V2AnchorRole.ENDPOINT_B if index + 1 == count else role
    return V2Anchor(tuple(anchor.point), str(anchor.owner_id or ""), role, index)


def _tolerances(colliders, radius, quality):
    low, high, coordinate = _bounds(colliders)
    diagonal = float(np.linalg.norm(high - low)) if low is not None else float(radius)
    length = max(diagonal, float(radius), 1.0e-6); coordinate = max(1.0, coordinate, length)
    floor = max(1.0e-9 * length, 8.0 * np.finfo(np.float32).eps * coordinate)
    slack = max(floor, 0.01 * float(radius)) if radius > 0.0 else floor
    fixed = 1.0e-6 if quality is V2Quality.FINAL else 1.0e-4
    return V2ResolvedTolerances(length, coordinate, floor, slack,
                                max(1.0e-7, 1.0e-6 * length), fixed, fixed,
                                1.0e-7 if quality is V2Quality.FINAL else 1.0e-5)


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
                validated=succeeded, engine_version=V2_PRODUCTION_VERSION,
                diagnostics=planner.diagnostics, telemetry=session.telemetry, engine="V2",
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
    values.update(engine="V2", backend_version=result.backend_version,
                  selection=session.selection)
    return values


def _result_error(result):
    failures = {V2Termination.INVALID_ATTACHMENT, V2Termination.INVALID_CONFIGURATION,
                V2Termination.UNSAFE_OUTPUT, V2Termination.BACKEND_UNAVAILABLE}
    return str(result.message or result.termination.value) if result.termination in failures else ""


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
