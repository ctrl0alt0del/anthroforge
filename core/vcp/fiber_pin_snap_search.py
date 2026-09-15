"""Same-owner fallback extracted from the qualified finger resnapping reference.

No planner search or numerical Fiber solve is performed here. Surface projection
and local native collision queries only; all search state is operation-local.
"""
from dataclasses import dataclass
from time import perf_counter
import numpy as np
from mathutils import Vector
from . import fiber_pin_repair as repair
from .fiber_pin_snap_validation import component_worlds, qualification_reason
from .v2 import planner
from .v2.contracts import V2Anchor


@dataclass(frozen=True)
class FiberPinSnapResult:
    raw: str = ''
    point: tuple = ()
    surface: tuple = ()
    mode: str = 'FAILED'
    reason: str = ''
    displacement: float = 0.0
    tests: int = 0
    elapsed_ms: float = 0.0

    @property
    def valid(self):
        return bool(self.raw)


def binding_row(obj, raw, runtime, offset):
    frame = repair.resolve_surface_frame(obj, raw, runtime) if raw else None
    if frame is None: return None
    point = frame['point_world'] + frame['normal_world'] * float(offset)
    return dict(raw=raw, surface=frame['point_world'], point=point)


def candidate_rows(surface, origin, subdivision, offset):
    rows = [repair._triangle_row(surface, tuple(map(int, tri)), weights, offset)
            for tri in surface['triangles'] for weights in repair._weights(subdivision)]
    rows.extend(closest_triangle_row(surface, tri, origin, offset) for tri in surface['triangles'])
    rows.sort(key=lambda row: np.linalg.norm(np.asarray(row['point']) - origin))
    return rows


def closest_triangle_row(surface, tri, origin, offset):
    from mathutils.geometry import closest_point_on_tri
    abc = tuple(Vector(surface['verts_world'][i]) for i in tri)
    nearest = closest_point_on_tri(Vector(origin), *abc)
    a, b, c = map(np.asarray, abc)
    uv = np.linalg.lstsq(np.column_stack((b-a, c-a)), np.asarray(nearest)-a, rcond=None)[0]
    return repair._triangle_row(surface, tuple(map(int, tri)), (1-uv.sum(), *uv), offset)


class FiberPinSnapSearch:
    def __init__(self, request, obj, owner, raw, runtime, offset=0., parts=None, origin=None):
        self.obj = obj; self.owner = owner; self.runtime = runtime; self.offset = float(offset)
        self.nearest = binding_row(obj, raw, runtime, offset)
        self.origin = np.asarray(self.nearest['point'] if origin is None else origin)
        self.anchor = V2Anchor(tuple(self.origin), owner)
        world = planner.cached_native_collision_world(request.colliders)
        self.state = planner._PlannerState(request, None, {}, {}, native_world=world)
        self.parts = component_worlds(request.colliders, owner) if parts is None else parts
        self.radius = request.collision_policy.collision_radius; self.guard = repair.serialization_guard(self.radius)
        self.threshold = max(0., self.radius - request.tolerances.clearance_slack + self.guard)
        self.outward_sign = -1 if obj.evaluated_get(runtime['depsgraph']).matrix_world.determinant() < 0 else 1
        self.tests = 0; self.memo = {}; self.reason = ''; self.started = perf_counter()

    def project(self, point):
        return repair._candidate_from_target(self.obj, self.runtime, point, self.offset)

    def valid(self, row):
        if row is None: return False
        key = tuple(np.round(row['point'], 10))
        if key not in self.memo:
            self.tests += 1; self.memo[key] = qualification_reason(self, row)
        return not self.memo[key]

    def seeds(self, subdivision):
        surface = repair.build_mesh_surface_data(self.obj, self.runtime['depsgraph'], self.runtime['surface_cache'])
        rows = candidate_rows(surface, self.origin, subdivision, self.offset); valid = []
        for row in rows:
            if self.valid(row): valid.append(row)
            if len(valid) == 8: break
        return valid

    def refine(self, seed):
        goal = np.asarray(seed['surface']); low = 0.; high = 1.; best = seed
        for step in range(1, 33):
            fraction = step / 32; row = self.project(self.origin + fraction * (goal - self.origin))
            if self.valid(row): high = fraction; best = row; break
            low = fraction
        for _iteration in range(18):
            fraction = (low + high) * .5; row = self.project(self.origin + fraction * (goal - self.origin))
            if self.valid(row): high = fraction; best = row
            else: low = fraction
        return best

    def run(self):
        if self.valid(self.nearest): return self.result(self.nearest, 'NEAREST')
        self.reason = self.memo[tuple(np.round(self.nearest['point'], 10))]
        rows = self.seeds(4); mode = 'SUBDIVISION_4'
        if not rows: rows = self.seeds(8); mode = 'SUBDIVISION_8'
        candidates = [self.refine(row) for row in rows]
        best = min(candidates, key=lambda row: np.linalg.norm(np.asarray(row['point'])-self.origin), default=None)
        return self.result(best, mode if best else 'FAILED')

    def result(self, row, mode):
        elapsed = 1000 * (perf_counter() - self.started)
        if row is None: return FiberPinSnapResult(reason=self.reason, tests=self.tests, elapsed_ms=elapsed)
        row = binding_row(self.obj, row['raw'], self.runtime, self.offset)
        if row is None or qualification_reason(self, row):
            return FiberPinSnapResult(reason='PIN_SNAP_VALIDATION_FAILED', tests=self.tests, elapsed_ms=elapsed)
        distance = float(np.linalg.norm(np.asarray(row['point']) - self.nearest['point']))
        return FiberPinSnapResult(row['raw'], tuple(row['point']), tuple(row['surface']), mode,
                                  self.reason, distance, self.tests, elapsed)
