from collections import Counter, OrderedDict
from math import floor

from mathutils import Vector

from ..deps.runtime_trace import telemetry_collision_query
from ..perf_trace import perf_count, perf_time, perf_timer
from ..scp_runtime.common import iter_geometry_mesh_scp_objects
from ..scp_runtime.surface import (build_mesh_surface_bounds, build_mesh_surface_data,
                                   surface_shortest_param_path, surface_shortest_param_samples,
                                   surface_shortest_vertex_path)
from ..utils import bounded_scene_cache_adopt, bounded_scene_cache_get, bounded_scene_cache_set


_SPATIAL_INDEX_THRESHOLD = 32
_SPATIAL_CELL_LIMIT = 96
_SPATIAL_QUERY_CELL_LIMIT = 512
_SHELL_VERTEX_LIMIT = 32
_SHELL_VERTEX_LIMIT_DENSE = 128
_SHELL_BOUNDARY_LIMIT = 32
_SHELL_BOUNDARY_LIMIT_DENSE = 128
_QUERY_CACHE_LIMIT = 32768
_ACTIVE_LOCAL_CACHE_LIMIT = 256
_VOXEL_PAYLOAD_LIMIT = 4
_VOXEL_VALUE_LIMIT = 16384
_ACTIVE_CACHE_NAMESPACE = "fiber_collision_active"
_GEOMETRY_CACHE_NAMESPACE = "fiber_collision_geometry"
_SCENE_CACHE_ENTRY_LIMIT = 128
_ACTIVE_CACHE_BYTE_LIMIT = 8 * 1024 * 1024
_GEOMETRY_CACHE_BYTE_LIMIT = 256 * 1024 * 1024
_COLLIDER_GENERATIONS = {}
_RAY_COUNT_LIMIT = 256
_RAY_DIRECTIONS = tuple(Vector(v) for v in (
    (0.9273095, 0.3440318, 0.1474422), (-0.2429726, 0.8965780, 0.3702867),
    (0.1793772, -0.3225071, 0.9294154)))
_SURFACE_OFFSET_FACTORS = (1.0, 2.0, 2.5, 3.0, 3.5, 4.0)


class CollisionOracle:
    def __init__(self, root, scene, depsgraph, margin=0.0, surface_offset=0.002, supports=()):
        self.root, self.scene, self.depsgraph = root, scene, depsgraph
        self.margin = max(0.0, float(margin))
        self.clearance = max(0.01, self.margin * 2.0, float(surface_offset) * 4.0)
        self._colliders = None
        self._collider_lookup = None
        self._segment_hit_cache = OrderedDict()
        self._push_cache = OrderedDict()
        self._active_cache = OrderedDict()
        self._required_ids = ()
        self.supports = tuple(supports)

    def colliders(self):
        if self._colliders is None:
            self._colliders = _build_colliders(self.root, self.scene, self.depsgraph, self.supports)
        return self._colliders

    def collider_by_id(self, owner_id):
        if self._collider_lookup is None:
            self._collider_lookup = _build_collider_lookup(self.colliders())
        return self._collider_lookup.get(str(owner_id or ""))

    def active_colliders_for_segment(self, a, b, owners=(), padding=0.0):
        _ = owners
        return self._active_cached((a, b), padding)

    def active_colliders_for_polyline(self, points, padding=0.0):
        return self._active_cached(points, padding)

    def active_padding(self):
        return max(0.05, self.clearance * 2.0, self.margin * 4.0)

    def require_colliders(self, collider_ids):
        values = (*self._required_ids, *tuple(collider_ids or ()))
        self._required_ids = tuple(dict.fromkeys(str(value) for value in values if value))

    def _active_cached(self, points, padding):
        points = tuple(points or ())
        if not points:
            return self.colliders()
        bounds = _line_bounds(points, self.margin + padding)
        key = _round_bounds(bounds)
        factory = lambda: _active_for_bounds(self.scene, self.colliders(), bounds)
        active = _cache_result(self._active_cache, key, factory, _ACTIVE_LOCAL_CACHE_LIMIT)
        return self._with_required(active)

    def _with_required(self, active):
        if not self._required_ids:
            return active
        lookup = _build_collider_lookup(self.colliders())
        required = tuple(lookup[sid] for sid in self._required_ids if sid in lookup)
        return _merge_collider_sets(active, required)

    def segment_visible(self, a, b, owners=(), colliders=None):
        cols = _provided_or_active(colliders, lambda: self.active_colliders_for_segment(a, b, owners=owners))
        return all(_segment_clear(self, c, a, b, owners) for c in cols)

    def segment_hit_samples(self, a, b, colliders=None):
        cols = _provided_or_active(colliders, lambda: self.active_colliders_for_segment(a, b))
        trim = max(1.0e-5, self.margin * 0.25)
        key = _segment_query_key(a, b, cols, trim)
        factory = lambda: _segment_hit_samples(cols, a, b, trim)
        return _cache_result(self._segment_hit_cache, key, factory, _QUERY_CACHE_LIMIT)

    def push_out_point(self, point, colliders=None):
        cols = _provided_or_active(colliders, lambda: self.active_colliders_for_polyline((point,)))
        key = _point_query_key(point, cols)
        factory = lambda: _cached_push_result(_push_out_world(self, point, cols))
        pushed, pen = _cache_result(self._push_cache, key, factory, _QUERY_CACHE_LIMIT)
        return Vector(pushed), pen

    def shell_nodes(self, collider, dense=False):
        return _shell_nodes(self.scene, collider, max(self.margin, self.clearance), dense)

    def surface_path(self, owner_id, start_vertex, end_vertex):
        collider = self.collider_by_id(owner_id)
        surface = None if collider is None else _collider_surface(collider)
        return None if surface is None else surface_shortest_vertex_path(surface, start_vertex, end_vertex)

    def surface_param_path(self, owner_id, start_param, end_param):
        collider = self.collider_by_id(owner_id)
        surface = None if collider is None else _collider_surface(collider)
        return None if surface is None else surface_shortest_param_path(surface, start_param, end_param)

    def surface_local_path(self, owner_id, start_param, end_param):
        routes = self.surface_local_paths(owner_id, start_param, end_param)
        return None if not routes else routes[0]

    def surface_local_paths(self, owner_id, start_param, end_param):
        collider = self.collider_by_id(owner_id)
        surface = None if collider is None else _collider_surface(collider)
        samples = None if surface is None else surface_shortest_param_samples(surface, start_param, end_param)
        return () if not samples else tuple(_offset_surface_samples(self, collider, samples, factor)
                                            for factor in _SURFACE_OFFSET_FACTORS)

    def surface_route_shortcut(self, points, owner_id, colliders=None):
        owner = self.collider_by_id(owner_id)
        if owner is None:
            return [Vector(point) for point in tuple(points or ())]
        active = _provided_or_active(colliders, lambda: self.active_colliders_for_polyline(points))
        return _surface_shortcut(self, owner, points, _merge_collider_sets(active, (owner,)))

    def surface_route_relax(self, points, owner_id, colliders=None):
        owner = self.collider_by_id(owner_id)
        if owner is None:
            return [Vector(point) for point in tuple(points or ())]
        active = _provided_or_active(colliders, lambda: self.active_colliders_for_polyline(points))
        return _relax_surface_route(self, owner, points, _merge_collider_sets(active, (owner,)))

    def surface_route_visible(self, points, owner_id, colliders=None):
        owner = self.collider_by_id(owner_id)
        active = _provided_or_active(colliders, lambda: self.active_colliders_for_polyline(points))
        return bool(owner and _surface_polyline_clear(self, owner, points, _merge_collider_sets(active, (owner,))))


def _build_colliders(root, scene, depsgraph, supports=()):
    start = perf_timer()
    try:
        return _build_colliders_uncached(root, scene, depsgraph, supports)
    finally:
        perf_time(scene, "collider_build", start)


def _build_colliders_uncached(root, scene, depsgraph, supports=()):
    items = []
    for obj in iter_geometry_mesh_scp_objects(scene, root.name):
        item = _build_collider_entry(obj, scene, depsgraph)
        if item is not None:
            items.append(item)
    items.extend(_muscle_colliders(root, scene, depsgraph, supports))
    perf_count(scene, "collider_records_built", len(items))
    return sorted(items, key=lambda item: item["sid"])


def _build_collider_entry(obj, scene, depsgraph):
    bounds = build_mesh_surface_bounds(obj, depsgraph)
    _adopt_evaluated_cache(scene, obj, "bounds", bounds)
    return _collider_entry(obj, bounds, depsgraph, scene)


def _collider_entry(obj, bounds, depsgraph, scene=None):
    from .surface_reference import key, from_object
    if not bounds:
        return None
    return {
        "sid": key(from_object(obj)), "obj": obj, "depsgraph": depsgraph, "scene": scene,
        "bvh": None, "surface": None,
        "m_inv": obj.matrix_world.inverted(), "m": obj.matrix_world.copy(), "m3": obj.matrix_world.to_3x3(),
        "orientation": _matrix_orientation(obj.matrix_world.to_3x3()),
        "mn": bounds[0], "mx": bounds[1], "stamp": _collider_stamp(obj),
    }


def _muscle_colliders(root, scene, depsgraph, supports):
    from .attachment_surface import resolve_object
    from .surface_reference import is_muscle
    result = []
    for value in dict.fromkeys(supports):
        if not is_muscle(value): continue
        obj = resolve_object(root, scene, value)
        item = None if obj is None else _build_collider_entry(obj, scene, depsgraph)
        if item is None: raise ValueError('Selected muscle support is unavailable.')
        result.append(item)
    return result


def _collider_surface(collider):
    if collider is None:
        return None
    if collider.get("surface") is None:
        _materialize_collider(collider)
    return collider.get("surface")


def _collider_bvh(collider):
    surface = _collider_surface(collider)
    return None if surface is None else collider.get("bvh")


def _materialize_collider(collider):
    surface = build_mesh_surface_data(collider["obj"], collider.get("depsgraph"))
    if surface is None:
        return None
    _adopt_evaluated_cache(collider.get("scene"), collider["obj"], "full", surface)
    collider["surface"], collider["bvh"] = surface, surface["bvh_world"]
    collider["mn"], collider["mx"] = surface["bounds_world"]
    return surface


def _offset_surface_route(oracle, collider, route):
    return [_offset_surface_point(oracle, collider, point) for point in tuple(route or ())]


def _offset_surface_samples(oracle, collider, samples, factor):
    distance = max(float(oracle.margin), float(oracle.clearance), 1.0e-6) * float(factor)
    return [_choose_exterior_offset(collider, Vector(point), Vector(normal), distance)
            for point, normal in tuple(samples or ())]


def _offset_surface_point(oracle, collider, point):
    hit = _query_nearest(_collider_bvh(collider), point)
    return Vector(point) if not hit or hit[0] is None else _offset_surface_hit(oracle, collider, hit)


def _offset_surface_hit(oracle, collider, hit):
    co, normal, _index, _distance = hit
    offset = max(float(oracle.margin), float(oracle.clearance), 1.0e-6)
    direction = _world_normal(collider, normal)
    return _choose_exterior_offset(collider, Vector(co), direction, offset)


def _choose_exterior_offset(collider, point, normal, offset):
    first, second = point + normal * offset, point - normal * offset
    return first if _sample_distance(collider, first) >= _sample_distance(collider, second) else second


def _surface_polyline_clear(oracle, owner, points, colliders):
    route = tuple(points or ())
    for index in range(len(route) - 1):
        owners = _surface_edge_owners(owner["sid"], index, len(route))
        if not _surface_edge_clear(oracle, owner, route[index], route[index + 1], owners, colliders):
            return False
    return True


def _surface_shortcut(oracle, owner, points, colliders):
    route = tuple(points or ())
    if owner is None or len(route) < 3:
        return [point.copy() for point in route]
    out, index = [route[0].copy()], 0
    while index < len(route) - 1:
        index = _surface_shortcut_index(oracle, owner, route, colliders, index)
        out.append(route[index].copy())
    return out


def _surface_shortcut_index(oracle, owner, route, colliders, index):
    for candidate in range(len(route) - 1, index, -1):
        owners = _surface_edge_owners(owner["sid"], index, len(route), candidate)
        if _surface_edge_clear(oracle, owner, route[index], route[candidate], owners, colliders):
            return candidate
    return index + 1


def _relax_surface_route(oracle, owner, points, colliders, iterations=2):
    out = [Vector(point) for point in tuple(points or ())]
    for _iteration in range(iterations):
        for index in range(1, len(out) - 1):
            out[index] = _relaxed_surface_point(oracle, owner, out, colliders, index)
    return out


def _relaxed_surface_point(oracle, owner, points, colliders, index):
    target = (points[index - 1] + points[index + 1]) * 0.5
    for alpha in (0.5, 0.25, 0.125, 0.0625):
        candidate = points[index].lerp(target, alpha)
        if _relaxed_surface_edges_clear(oracle, owner, points, colliders, index, candidate):
            return candidate
    return points[index].copy()


def _relaxed_surface_edges_clear(oracle, owner, points, colliders, index, candidate):
    left = (owner["sid"] if index == 1 else "", "")
    right = ("", owner["sid"] if index + 2 == len(points) else "")
    return (_surface_edge_clear(oracle, owner, points[index - 1], candidate, left, colliders) and
            _surface_edge_clear(oracle, owner, candidate, points[index + 1], right, colliders))


def _surface_edge_owners(owner_id, index, count, end_index=None):
    end = index + 1 if end_index is None else end_index
    return (owner_id if index == 0 else "", owner_id if end + 1 == count else "")


def _surface_edge_clear(oracle, owner, start, end, owners, colliders):
    for collider in tuple(colliders or ()):
        check = _surface_owner_clear if _same_collider(collider, owner) else _segment_clear
        if not check(oracle, collider, start, end, owners):
            return False
    return True


def _same_collider(first, second):
    first_id, second_id = str(first.get("sid", "") or ""), str(second.get("sid", "") or "")
    return first is second or bool(first_id and first_id == second_id)


def _surface_owner_clear(oracle, collider, start, end, owners):
    if not _aabb_overlap(*_line_bounds((start, end), oracle.margin), collider["mn"], collider["mx"], 0.0):
        return True
    first, last = _trimmed_segment(oracle, collider, start, end, owners)
    return first is None or (not _segment_ray_hit(collider, first, last) and
                             _surface_segment_clear(oracle, collider, first, last))


def _surface_segment_clear(oracle, collider, start, end):
    tolerance = max(1.0e-7, float(oracle.margin) * 1.0e-5)
    return all(_sample_distance(collider, start.lerp(end, step / 8.0)) + tolerance >= oracle.margin
               for step in range(1, 8))


def _unsigned_segment_clear(oracle, collider, start, end):
    tolerance = max(1.0e-7, float(oracle.margin) * 1.0e-5)
    return all(_bvh_unsigned_distance(collider, start.lerp(end, step / 8.0)) + tolerance >= oracle.margin
               for step in range(1, 8))


def _adopt_evaluated_cache(scene, obj, kind, payload):
    key = _evaluated_cache_key(obj, kind)
    if scene is None or key is None or payload is None:
        return
    bounded_scene_cache_adopt(
        scene, key, _GEOMETRY_CACHE_NAMESPACE, _SCENE_CACHE_ENTRY_LIMIT,
        _GEOMETRY_CACHE_BYTE_LIMIT, _evaluated_payload_bytes(payload))


def _evaluated_cache_key(obj, kind):
    try:
        return f"surface:{str(kind)}:{int(obj.as_pointer())}"
    except Exception:
        return None


def _evaluated_payload_bytes(payload):
    if not isinstance(payload, dict):
        return 512 + 96 * len(tuple(payload or ()))
    verts = len(tuple(payload.get("verts_world", ()) or ()))
    tris = len(tuple(payload.get("triangles", ()) or ()))
    centers = len(tuple(payload.get("face_centers", ()) or ()))
    edges = sum(len(tuple(v or ())) for v in dict(payload.get("route_graph", {})).values())
    return 1024 + 160 * verts + 384 * tris + 96 * centers + 48 * edges


def _collider_by_id(colliders, owner_id):
    return next((collider for collider in colliders if collider["sid"] == str(owner_id or "")), None)


def _build_collider_lookup(colliders):
    lookup = {}
    for collider in tuple(colliders or ()):
        lookup.setdefault(str(collider["sid"]), collider)
    return lookup


def _merge_collider_sets(first, second):
    values = (*tuple(first or ()), *tuple(second or ()))
    lookup = {str(collider["sid"]): collider for collider in values}
    return tuple(lookup[sid] for sid in sorted(lookup))


def _matrix_orientation(matrix):
    return -1.0 if matrix.determinant() < 0.0 else 1.0


def _collider_stamp(obj):
    data = getattr(obj, "data", None)
    counts = len(getattr(data, "vertices", ())), len(getattr(data, "polygons", ()))
    matrix = tuple(float(value) for row in obj.matrix_world for value in row)
    generations = _collider_generation(obj), _collider_generation(data), int(obj.get('af_surface_generation', 0))
    return _id_token(obj), _id_token(data), counts, matrix, generations


def note_collider_updates(depsgraph):
    for update in tuple(getattr(depsgraph, "updates", ()) or ()):
        if _geometry_update(update):
            key = _id_token(getattr(update, "id", None))
            _COLLIDER_GENERATIONS[key] = _COLLIDER_GENERATIONS.get(key, 0) + 1


def clear_collider_generations():
    _COLLIDER_GENERATIONS.clear()


def _geometry_update(update):
    return bool(getattr(update, "is_updated_geometry", False) or
                getattr(update, "is_updated_transform", False))


def _collider_generation(value):
    return int(_COLLIDER_GENERATIONS.get(_id_token(value), 0))


def _id_token(value):
    if value is None:
        return ("", 0)
    uid = int(getattr(value, "session_uid", 0) or 0)
    pointer = uid or _id_pointer(value)
    return type(value).__name__, pointer


def _id_pointer(value):
    try:
        return int(value.as_pointer())
    except Exception:
        return id(value)


def _segment_query_key(a, b, colliders, trim):
    return ("seg", _vec_key(a), _vec_key(b), round(float(trim), 9), _collider_query_key(colliders))


def _point_query_key(point, colliders):
    return ("pt", _vec_key(point), _collider_query_key(colliders))


def _vec_key(point):
    return tuple(float(v) for v in point)


def _collider_query_key(colliders):
    return tuple(id(collider) for collider in tuple(colliders or ()))


def _cached_push_result(result):
    pushed, pen = result
    return _vec_key(pushed), float(pen)


def _provided_or_active(colliders, factory):
    return factory() if colliders is None else colliders


def _cache_result(cache, key, factory, limit):
    if key in cache:
        value = cache.pop(key)
        cache[key] = value
        return value
    cache[key] = factory()
    while len(cache) > max(1, int(limit)):
        cache.popitem(last=False)
    return cache[key]


def _active_segment(scene, colliders, a, b, margin, padding):
    return _active_for_bounds(scene, colliders, _line_bounds((a, b), margin + padding))


def _active_polyline(scene, colliders, points, margin, padding):
    return colliders if not points else _active_for_bounds(scene, colliders, _line_bounds(points, margin + padding))


def _active_for_bounds(scene, colliders, bounds):
    ids = bounded_scene_cache_get(scene, _active_key(colliders, bounds), _ACTIVE_CACHE_NAMESPACE)
    return _colliders_from_ids(colliders, ids) if ids is not None else _store_active(scene, colliders, bounds)


def _store_active(scene, colliders, bounds):
    hits = _active_hits(scene, tuple(colliders or ()), bounds)
    _set_active_cache(scene, _active_key(colliders, bounds), tuple(c["sid"] for c in hits))
    return hits


def _set_active_cache(scene, key, value):
    return bounded_scene_cache_set(
        scene, key, value, _ACTIVE_CACHE_NAMESPACE,
        _SCENE_CACHE_ENTRY_LIMIT, _ACTIVE_CACHE_BYTE_LIMIT)


def _active_hits(scene, colliders, bounds):
    if len(colliders) < _SPATIAL_INDEX_THRESHOLD:
        return _linear_active_hits(colliders, bounds)
    index = _spatial_index(scene, colliders)
    return _spatial_active_hits(colliders, bounds, index)


def _linear_active_hits(colliders, bounds):
    return [c for c in colliders if _aabb_overlap(bounds[0], bounds[1], c["mn"], c["mx"], 0.0)]


def _active_key(colliders, bounds):
    return ("fiber_active", _round_bounds(bounds), tuple((c["sid"], c["stamp"]) for c in colliders))


def _round_bounds(bounds):
    return tuple(round(v, 5) for p in bounds for v in (p.x, p.y, p.z))


def _colliders_from_ids(colliders, ids):
    index = {c["sid"]: c for c in colliders}
    return [index[sid] for sid in tuple(ids or ()) if sid in index]


def _spatial_index(scene, colliders):
    key = ("fiber_spatial_index", tuple((c["sid"], c["stamp"]) for c in colliders))
    cached = bounded_scene_cache_get(scene, key, _GEOMETRY_CACHE_NAMESPACE)
    return cached if cached is not None else _set_geometry_cache(scene, key, _build_spatial_index(colliders))


def _set_geometry_cache(scene, key, value):
    return bounded_scene_cache_set(
        scene, key, value, _GEOMETRY_CACHE_NAMESPACE,
        _SCENE_CACHE_ENTRY_LIMIT, _GEOMETRY_CACHE_BYTE_LIMIT)


def _build_spatial_index(colliders):
    origin, cell = _spatial_origin(colliders), _spatial_cell_size(colliders)
    out = {"origin": origin, "cell": cell, "cells": {}, "large": [], "lookup": {}}
    for i, collider in enumerate(colliders):
        out["lookup"][collider["sid"]] = i
        _insert_spatial_collider(out, collider)
    return out


def _spatial_origin(colliders):
    xs, ys, zs = [c["mn"].x for c in colliders], [c["mn"].y for c in colliders], [c["mn"].z for c in colliders]
    return Vector((min(xs), min(ys), min(zs)))


def _spatial_cell_size(colliders):
    spans = sorted(max((c["mx"] - c["mn"]).x, (c["mx"] - c["mn"]).y, (c["mx"] - c["mn"]).z) for c in colliders)
    return max(1.0e-6, spans[len(spans) // 2])


def _insert_spatial_collider(index, collider):
    ranges = _spatial_ranges(index, collider["mn"], collider["mx"])
    if _spatial_cell_count(ranges) > _SPATIAL_CELL_LIMIT:
        index["large"].append(collider["sid"])
        return
    for cell in _spatial_cells_from_ranges(ranges):
        index["cells"].setdefault(cell, []).append(collider["sid"])


def _spatial_cells_for(index, mn, mx):
    return _spatial_cells_from_ranges(_spatial_ranges(index, mn, mx))


def _spatial_cells_from_ranges(ranges):
    return ((x, y, z) for x in ranges[0] for y in ranges[1] for z in ranges[2])


def _spatial_ranges(index, mn, mx):
    low = _cell_coord(index, mn)
    high = _cell_coord(index, mx)
    return tuple(range(low[i], high[i] + 1) for i in range(3))


def _spatial_cell_count(ranges):
    out = 1
    for values in ranges:
        out *= len(values)
    return out


def _cell_coord(index, point):
    origin, cell = index["origin"], index["cell"]
    return tuple(int(floor((point[i] - origin[i]) / cell)) for i in range(3))


def _spatial_active_hits(colliders, bounds, index):
    ids = _spatial_query_ids(index, bounds)
    candidates = tuple(colliders[index["lookup"][sid]] for sid in ids if sid in index["lookup"])
    return _linear_active_hits(candidates, bounds)


def _spatial_query_ids(index, bounds):
    ranges = _spatial_ranges(index, bounds[0], bounds[1])
    if _spatial_cell_count(ranges) > _SPATIAL_QUERY_CELL_LIMIT:
        ids = tuple(index["large"]) + tuple(sid for bucket in index["cells"].values() for sid in bucket)
        return _dedupe_ids(ids)
    cells = tuple(_spatial_cells_from_ranges(ranges))
    return _dedupe_ids(tuple(index["large"]) + tuple(sid for cell in cells for sid in index["cells"].get(cell, ())))


def _dedupe_ids(ids):
    return tuple(dict.fromkeys(ids))


def _line_bounds(points, pad):
    xs, ys, zs = [p.x for p in points], [p.y for p in points], [p.z for p in points]
    mn = Vector((min(xs) - pad, min(ys) - pad, min(zs) - pad))
    mx = Vector((max(xs) + pad, max(ys) + pad, max(zs) + pad))
    return mn, mx


def _aabb_overlap(a_mn, a_mx, b_mn, b_mx, margin):
    return not (
        a_mx.x < (b_mn.x - margin) or b_mx.x < (a_mn.x - margin)
        or a_mx.y < (b_mn.y - margin) or b_mx.y < (a_mn.y - margin)
        or a_mx.z < (b_mn.z - margin) or b_mx.z < (a_mn.z - margin)
    )


def _segment_clear(oracle, collider, a, b, owners):
    if not _aabb_overlap(*_line_bounds((a, b), oracle.margin), collider["mn"], collider["mx"], 0.0):
        return True
    p0, p1 = _trimmed_segment(oracle, collider, a, b, owners)
    if p0 is None:
        return True
    return not _segment_ray_hit(collider, p0, p1) and not _segment_sample_hit(oracle, collider, p0, p1)


def _trimmed_segment(oracle, collider, a, b, owners):
    length = (b - a).length
    if length <= 1.0e-9:
        return None, None
    t0 = _trim_t(collider["sid"] == str((owners or ("", ""))[0] or ""), oracle.clearance, length)
    t1 = 1.0 - _trim_t(collider["sid"] == str((owners or ("", ""))[1] or ""), oracle.clearance, length)
    return (None, None) if t1 <= t0 else (a.lerp(b, t0), a.lerp(b, t1))


def _trim_t(enabled, clearance, length):
    return 0.0 if not enabled else min(0.45, max(0.0, clearance / max(length, 1.0e-9)))


def _segment_ray_hit(collider, a, b):
    return _segment_ray_world_hit(collider, a, b) is not None


def _segment_ray_world_hit(collider, a, b):
    bvh = _collider_bvh(collider)
    if bvh is None:
        return None
    delta = b - a
    length = delta.length
    if length <= 1.0e-9:
        return None
    hit = _query_ray(bvh, a, delta.normalized(), length)
    return None if not hit or hit[0] is None else Vector(hit[0])


def _segment_hit_samples(colliders, a, b, trim):
    hits = []
    for collider in _segment_hit_candidates(colliders, a, b, trim):
        t = _segment_hit_t(collider, a, b, trim)
        if t is not None:
            hits.append(t)
    return tuple(hits)


def _segment_hit_candidates(colliders, a, b, trim):
    bounds = _line_bounds((a, b), max(0.0, trim))
    return tuple(c for c in tuple(colliders or ()) if _aabb_overlap(bounds[0], bounds[1], c["mn"], c["mx"], 0.0))


def _segment_hit_t(collider, a, b, trim):
    delta = b - a
    if delta.length <= 1.0e-9:
        return None
    t0 = min(0.45, max(0.0, trim / delta.length))
    hit = _segment_ray_world_hit(collider, a.lerp(b, t0), a.lerp(b, 1.0 - t0))
    return None if hit is None else _world_hit_t(a, b, hit)


def _world_hit_t(a, b, hit):
    delta = b - a
    return max(0.0, min(1.0, (hit - a).dot(delta) / max(delta.length_squared, 1.0e-12)))


def _segment_sample_hit(oracle, collider, a, b):
    return any(_sample_pen(collider, a.lerp(b, step / 6.0), oracle.margin) > 0.0 for step in range(1, 6))


def _sample_pen(collider, point, margin):
    return max(0.0, margin - _sample_distance(collider, point))


def _sample_distance(collider, point):
    return _bvh_unsigned_distance(collider, point) if _open_surface(collider) else _bvh_signed_distance(collider, point)


def _bvh_unsigned_distance(collider, point):
    bvh = _collider_bvh(collider)
    hit = None if bvh is None else _query_nearest(bvh, point)
    return 1.0e9 if not hit or hit[0] is None else (Vector(point) - Vector(hit[0])).length


def _open_surface(collider):
    if "_open_surface" not in collider:
        surface = _collider_surface(collider) or {}
        collider["_open_surface"] = _has_boundary(surface.get("triangles", ()))
    return bool(collider["_open_surface"])


def _has_boundary(triangles):
    edges = (tuple(sorted(edge)) for tri in tuple(triangles or ())
             for edge in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])))
    return any(count == 1 for count in Counter(edges).values())


def _bvh_signed_distance(collider, point):
    bvh = _collider_bvh(collider)
    if bvh is None:
        return 1.0e9
    hit = _query_nearest(bvh, point)
    return 1.0e9 if not hit or hit[0] is None else _signed_hit(collider, point, hit)


def _signed_hit(collider, point, hit):
    co, normal, _index, _dist = hit
    dist = (point - co).length
    sign = _ray_sign(collider, point)
    return dist * (_normal_sign(collider, point, co, normal) if sign is None else sign)


def _ray_sign(collider, point):
    votes = tuple(_ray_parity(collider, point, direction) for direction in _RAY_DIRECTIONS)
    valid = tuple(value for value in votes if value is not None)
    if not valid or sum(valid) * 2 == len(valid):
        return None
    return -1.0 if sum(valid) * 2 > len(valid) else 1.0


def _ray_parity(collider, point, direction):
    bvh = _collider_bvh(collider)
    if bvh is None:
        return False
    origin, remaining = Vector(point), _ray_limit(collider, point)
    epsilon, crossings = _ray_epsilon(collider), 0
    for _index in range(_RAY_COUNT_LIMIT):
        hit = _query_ray(bvh, origin, direction, remaining)
        if not hit or hit[0] is None:
            return bool(crossings % 2)
        step = (Vector(hit[0]) - origin).length + epsilon
        origin, remaining = origin + direction * step, remaining - step
        crossings += 1
    return None


def _ray_limit(collider, point):
    diagonal = (collider["mx"] - collider["mn"]).length
    center = (collider["mx"] + collider["mn"]) * 0.5
    return diagonal + (Vector(point) - center).length + 1.0


def _ray_epsilon(collider):
    return max(1.0e-7, (collider["mx"] - collider["mn"]).length * 1.0e-8)


def _query_ray(bvh, origin, direction, distance):
    telemetry_collision_query()
    return bvh.ray_cast(origin, direction, distance)


def _query_nearest(bvh, point):
    telemetry_collision_query()
    return bvh.find_nearest(point)


def _normal_sign(collider, point, co, normal):
    return 1.0 if (Vector(point) - Vector(co)).dot(_world_normal(collider, normal)) >= 0.0 else -1.0


def _world_normal(collider, normal):
    return _safe_normal(normal) * float(collider.get("orientation", 1.0))


def _safe_normal(normal):
    return Vector((0.0, 0.0, 1.0)) if Vector(normal).length <= 1.0e-8 else Vector(normal).normalized()


def _push_out_world(oracle, point, colliders):
    best_point, max_pen = point, 0.0
    for collider in colliders:
        best_point, max_pen = _push_out_one(oracle, collider, best_point, max_pen)
    return best_point, max_pen


def _push_out_one(oracle, collider, point, max_pen):
    if not _aabb_overlap(*_line_bounds((point,), oracle.margin * 2.0), collider["mn"], collider["mx"], 0.0):
        return point, max_pen
    pushed, pen = _nearest_push(collider, point, oracle.margin)
    return (pushed, max(max_pen, pen)) if pen > 0.0 else (point, max_pen)


def _point_needs_push(oracle, collider, point):
    if _voxel_signed_distance(oracle.scene, collider, point, oracle.margin) < oracle.margin:
        return True
    return _sample_pen(collider, point, oracle.margin) > 0.0


def _nearest_push(collider, point, margin):
    bvh = _collider_bvh(collider)
    if bvh is None:
        return point, 0.0
    hit = _query_nearest(bvh, point)
    if not hit or hit[0] is None:
        return point, 0.0
    return _push_from_hit(collider, point, hit, margin)


def _push_from_hit(collider, point, hit, margin):
    co, normal, _index, _dist = hit
    signed = _signed_hit(collider, point, hit)
    if signed >= margin:
        return Vector(point), 0.0
    penetration = margin - signed
    direction = _push_direction(collider, point, co, normal, signed)
    return Vector(point) + direction * penetration, penetration


def _push_direction(collider, point, co, normal, signed):
    delta = Vector(point) - Vector(co)
    if delta.length <= 1.0e-9:
        return _world_normal(collider, normal)
    direction = delta.normalized()
    return direction if signed >= 0.0 else -direction


def _voxel_signed_distance(scene, collider, point, margin):
    return _trilinear_distance(scene, collider, point, margin)


def _trilinear_distance(scene, collider, point, margin):
    payload = _voxel_payload(scene, collider, margin)
    coords = _grid_coords(payload, point)
    base = tuple(max(0, min(payload["dims"][i] - 2, int(floor(coords[i])))) for i in range(3))
    frac = tuple(coords[i] - base[i] for i in range(3))
    return _trilinear_mix(_grid_values(scene, collider, payload, base), frac)


def _voxel_payload(scene, collider, margin):
    cache = collider.setdefault("_voxel_cache", OrderedDict())
    key = round(float(margin), 6)
    factory = lambda: _new_voxel_payload(collider, margin)
    return _cache_result(cache, key, factory, _VOXEL_PAYLOAD_LIMIT)


def _new_voxel_payload(collider, margin):
    mn, mx = _inflate_bounds(collider["mn"], collider["mx"], margin)
    dims = _grid_dims(mx - mn)
    step = Vector(tuple((mx[i] - mn[i]) / float(max(1, dims[i] - 1)) for i in range(3)))
    return {"mn": mn, "mx": mx, "dims": dims, "step": step, "values": OrderedDict()}


def _inflate_bounds(mn, mx, margin):
    pad = Vector((margin, margin, margin))
    return mn - pad, mx + pad


def _grid_dims(span):
    scale = 64.0 / max(1.0e-6, max(span.x, span.y, span.z))
    vals = (int(round(span.x * scale)), int(round(span.y * scale)), int(round(span.z * scale)))
    return tuple(max(24, min(96, value)) for value in vals)


def _grid_coords(payload, local):
    return tuple((local[i] - payload["mn"][i]) / max(payload["step"][i], 1.0e-9) for i in range(3))


def _grid_values(scene, collider, payload, base):
    return tuple(_grid_value(scene, collider, payload, base, dx, dy, dz) for dz in (0, 1) for dy in (0, 1) for dx in (0, 1))


def _grid_value(scene, collider, payload, base, dx, dy, dz):
    index = (base[0] + dx, base[1] + dy, base[2] + dz)
    factory = lambda: _signed_grid_sample(collider, _grid_point(payload, index))
    return _cache_result(payload["values"], index, factory, _VOXEL_VALUE_LIMIT)


def _grid_point(payload, index):
    return Vector(tuple(payload["mn"][i] + payload["step"][i] * float(index[i]) for i in range(3)))


def _signed_grid_sample(collider, point):
    bvh = _collider_bvh(collider)
    hit = None if bvh is None else _query_nearest(bvh, point)
    return 1.0e9 if not hit or hit[0] is None else _signed_hit(collider, point, hit)


def _trilinear_mix(values, frac):
    c00 = _lerp(values[0], values[1], frac[0]), _lerp(values[2], values[3], frac[0])
    c01 = _lerp(values[4], values[5], frac[0]), _lerp(values[6], values[7], frac[0])
    return _lerp(_lerp(c00[0], c00[1], frac[1]), _lerp(c01[0], c01[1], frac[1]), frac[2])


def _lerp(a, b, t):
    return float(a) + (float(b) - float(a)) * float(t)


def _shell_nodes(scene, collider, margin, dense):
    key = ("fiber_shell", collider["sid"], collider["stamp"], round(margin, 6), bool(dense))
    cached = bounded_scene_cache_get(scene, key, _GEOMETRY_CACHE_NAMESPACE)
    return cached if cached is not None else _set_geometry_cache(scene, key, _build_shell_nodes(collider, margin, dense))


def _build_shell_nodes(collider, margin, dense):
    nodes = _mesh_shell_nodes(collider, margin, dense)
    nodes.extend(_bounds_shell_nodes(collider, margin, dense))
    return tuple(nodes)


def _mesh_shell_nodes(collider, margin, dense):
    surface = _collider_surface(collider) or {}
    verts = [Vector(v) for v in _sample_even(surface.get("verts_world", ()), _shell_vertex_limit(dense))]
    if not verts:
        return []
    center = _points_center(verts)
    nodes = [_offset_shell_point(v, center, margin) for v in verts]
    nodes.extend(_boundary_shell_points(surface, center, margin, dense))
    return nodes


def _shell_vertex_limit(dense):
    return _SHELL_VERTEX_LIMIT_DENSE if dense else _SHELL_VERTEX_LIMIT


def _shell_boundary_limit(dense):
    return _SHELL_BOUNDARY_LIMIT_DENSE if dense else _SHELL_BOUNDARY_LIMIT


def _sample_even(items, limit):
    values = tuple(items or ())
    if len(values) <= int(limit):
        return values
    last = len(values) - 1
    return tuple(values[min(last, round(i * last / float(max(1, int(limit) - 1))))] for i in range(int(limit)))


def _bounds_shell_nodes(collider, margin, dense):
    mn, mx = _inflate_bounds(collider["mn"], collider["mx"], margin)
    return tuple(_corner_points(mn, mx) + _face_points(mn, mx) + ([] if not dense else _edge_points(mn, mx)))


def _points_center(points):
    total = Vector((0.0, 0.0, 0.0))
    for point in points:
        total += point
    return total / max(1, len(points))


def _offset_shell_point(point, center, margin):
    delta = Vector(point) - center
    if delta.length <= 1.0e-9:
        return Vector(point)
    return Vector(point) + delta.normalized() * max(0.002, margin * 4.0)


def _boundary_shell_points(surface, center, margin, dense):
    edges = _sample_even(_boundary_edges(surface.get("triangles", ())), _shell_boundary_limit(dense))
    samples = (0.5,) if not dense else (0.25, 0.5, 0.75)
    return [_offset_shell_point(verts[a].lerp(verts[b], t), center, margin) for a, b, verts in _edge_verts(surface, edges) for t in samples]


def _edge_verts(surface, edges):
    verts = [Vector(v) for v in surface.get("verts_world", ())]
    return [(a, b, verts) for a, b in edges if 0 <= a < len(verts) and 0 <= b < len(verts)]


def _boundary_edges(triangles):
    counts = {}
    for tri in tuple(triangles or ()):
        for edge in _tri_edges(tri):
            counts[edge] = counts.get(edge, 0) + 1
    return tuple(edge for edge, count in counts.items() if count == 1)


def _tri_edges(tri):
    vals = tuple(int(v) for v in tri)
    return tuple(tuple(sorted(edge)) for edge in ((vals[0], vals[1]), (vals[1], vals[2]), (vals[2], vals[0])))


def _corner_points(mn, mx):
    vals = ((mn.x, mx.x), (mn.y, mx.y), (mn.z, mx.z))
    return [Vector((x, y, z)) for x in vals[0] for y in vals[1] for z in vals[2]]


def _face_points(mn, mx):
    center = (mn + mx) * 0.5
    return [Vector((mn.x, center.y, center.z)), Vector((mx.x, center.y, center.z)), Vector((center.x, mn.y, center.z)), Vector((center.x, mx.y, center.z)), Vector((center.x, center.y, mn.z)), Vector((center.x, center.y, mx.z))]


def _edge_points(mn, mx):
    center = (mn + mx) * 0.5
    return [Vector((x, y, center.z)) for x in (mn.x, mx.x) for y in (center.y,)] + [Vector((x, center.y, z)) for x in (mn.x, mx.x) for z in (mn.z, mx.z)] + [Vector((center.x, y, z)) for y in (mn.y, mx.y) for z in (mn.z, mx.z)] + [Vector((center.x, mn.y, center.z)), Vector((center.x, mx.y, center.z))]
