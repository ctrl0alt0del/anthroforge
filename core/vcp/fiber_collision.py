from math import floor

from mathutils import Vector

from ..perf_trace import perf_count, perf_time, perf_timer
from ..scp_runtime.common import iter_geometry_mesh_scp_objects
from ..scp_runtime.surface import build_mesh_surface_bounds, build_mesh_surface_data, surface_shortest_param_path, surface_shortest_vertex_path
from ..utils import scene_cache_get, scene_cache_set


_SPATIAL_INDEX_THRESHOLD = 32
_SPATIAL_CELL_LIMIT = 96
_SPATIAL_QUERY_CELL_LIMIT = 512
_SHELL_VERTEX_LIMIT = 32
_SHELL_VERTEX_LIMIT_DENSE = 128
_SHELL_BOUNDARY_LIMIT = 32
_SHELL_BOUNDARY_LIMIT_DENSE = 128


class CollisionOracle:
    def __init__(self, root, scene, depsgraph, margin=0.0, surface_offset=0.002):
        self.root, self.scene, self.depsgraph = root, scene, depsgraph
        self.margin = max(0.0, float(margin))
        self.clearance = max(0.01, self.margin * 2.0, float(surface_offset) * 4.0)
        self._colliders = None
        self._segment_hit_cache = {}
        self._push_cache = {}

    def colliders(self):
        self._colliders = self._colliders or _build_colliders(self.root, self.scene, self.depsgraph)
        return self._colliders

    def active_colliders_for_segment(self, a, b, owners=(), padding=0.0):
        return _active_segment(self.scene, self.colliders(), a, b, self.margin, padding)

    def active_colliders_for_polyline(self, points, padding=0.0):
        return _active_polyline(self.scene, self.colliders(), points, self.margin, padding)

    def segment_visible(self, a, b, owners=(), colliders=None):
        cols = colliders or self.active_colliders_for_segment(a, b, owners=owners)
        return all(_segment_clear(self, c, a, b, owners) for c in cols)

    def segment_hit_samples(self, a, b, colliders=None):
        cols = colliders or self.active_colliders_for_segment(a, b)
        trim = max(1.0e-5, self.margin * 0.25)
        key = _segment_query_key(a, b, cols, trim)
        if key not in self._segment_hit_cache:
            self._segment_hit_cache[key] = _segment_hit_samples(cols, a, b, trim)
        return self._segment_hit_cache[key]

    def push_out_point(self, point, colliders=None):
        cols = colliders or self.active_colliders_for_polyline((point,))
        key = _point_query_key(point, cols)
        if key not in self._push_cache:
            self._push_cache[key] = _cached_push_result(_push_out_world(self, point, cols))
        pushed, pen = self._push_cache[key]
        return Vector(pushed), pen

    def shell_nodes(self, collider, dense=False):
        return _shell_nodes(self.scene, collider, max(self.margin, self.clearance), dense)

    def surface_path(self, owner_id, start_vertex, end_vertex):
        collider = _collider_by_id(self.colliders(), owner_id)
        surface = None if collider is None else _collider_surface(collider)
        return None if surface is None else surface_shortest_vertex_path(surface, start_vertex, end_vertex)

    def surface_param_path(self, owner_id, start_param, end_param):
        collider = _collider_by_id(self.colliders(), owner_id)
        surface = None if collider is None else _collider_surface(collider)
        return None if surface is None else surface_shortest_param_path(surface, start_param, end_param)


def _build_colliders(root, scene, depsgraph):
    start = perf_timer()
    try:
        return _build_colliders_uncached(root, scene, depsgraph)
    finally:
        perf_time(scene, "collider_build", start)


def _build_colliders_uncached(root, scene, depsgraph):
    items = []
    for obj in iter_geometry_mesh_scp_objects(scene, root.name):
        item = _collider_entry(obj, build_mesh_surface_bounds(obj, depsgraph), depsgraph)
        if item is not None:
            items.append(item)
    perf_count(scene, "collider_records_built", len(items))
    return sorted(items, key=lambda item: item["sid"])


def _collider_entry(obj, bounds, depsgraph):
    if not bounds:
        return None
    return {
        "sid": str(obj.get("af_scp_id", "") or ""), "obj": obj, "depsgraph": depsgraph,
        "bvh": None, "surface": None,
        "m_inv": obj.matrix_world.inverted(), "m": obj.matrix_world.copy(), "m3": obj.matrix_world.to_3x3(),
        "mn": bounds[0], "mx": bounds[1], "stamp": _collider_stamp(obj),
    }


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
    collider["surface"], collider["bvh"] = surface, surface["bvh_local"]
    collider["mn"], collider["mx"] = surface["bounds_world"]
    return surface


def _collider_by_id(colliders, owner_id):
    return next((collider for collider in colliders if collider["sid"] == str(owner_id or "")), None)


def _collider_stamp(obj):
    data = getattr(obj, "data", None)
    return (int(data.as_pointer()) if data else 0, len(getattr(data, "vertices", ())), tuple(float(v) for row in obj.matrix_world for v in row))


def _segment_query_key(a, b, colliders, trim):
    return ("seg", _vec_key(a), _vec_key(b), round(float(trim), 9), _collider_query_key(colliders))


def _point_query_key(point, colliders):
    return ("pt", _vec_key(point), _collider_query_key(colliders))


def _vec_key(point):
    return tuple(float(v) for v in point)


def _collider_query_key(colliders):
    return tuple((str(c["sid"]), c["stamp"]) for c in tuple(colliders or ()))


def _cached_push_result(result):
    pushed, pen = result
    return _vec_key(pushed), float(pen)


def _active_segment(scene, colliders, a, b, margin, padding):
    return _active_for_bounds(scene, colliders, _line_bounds((a, b), margin + padding))


def _active_polyline(scene, colliders, points, margin, padding):
    return colliders if not points else _active_for_bounds(scene, colliders, _line_bounds(points, margin + padding))


def _active_for_bounds(scene, colliders, bounds):
    ids = scene_cache_get(scene, _active_key(colliders, bounds))
    return _colliders_from_ids(colliders, ids) if ids is not None else _store_active(scene, colliders, bounds)


def _store_active(scene, colliders, bounds):
    hits = _active_hits(scene, tuple(colliders or ()), bounds)
    scene_cache_set(scene, _active_key(colliders, bounds), tuple(c["sid"] for c in hits))
    return hits


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
    cached = scene_cache_get(scene, key)
    return cached if cached is not None else scene_cache_set(scene, key, _build_spatial_index(colliders))


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
    return p0 is None or (not _segment_ray_hit(collider, p0, p1) and not _segment_sample_hit(oracle, collider, p0, p1))


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
    local_a, local_b = collider["m_inv"] @ a, collider["m_inv"] @ b
    delta = local_b - local_a
    length = delta.length
    if length <= 1.0e-9:
        return None
    hit = bvh.ray_cast(local_a, delta.normalized(), length)
    return None if not hit or hit[0] is None else collider["m"] @ hit[0]


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
    return max(0.0, margin - _bvh_signed_distance(collider, point))


def _bvh_signed_distance(collider, point):
    bvh = _collider_bvh(collider)
    if bvh is None:
        return 1.0e9
    local = collider["m_inv"] @ point
    hit = bvh.find_nearest(local)
    return 1.0e9 if not hit or hit[0] is None else _signed_hit(collider, local, hit)


def _signed_hit(collider, local, hit):
    co, normal, _index, _dist = hit
    dist = (local - co).length
    sign = _ray_sign(collider, local)
    return dist * (_normal_sign(local, co, normal) if sign is None else sign)


def _ray_sign(collider, local):
    bvh = _collider_bvh(collider)
    if bvh is None:
        return 1.0
    limit = (collider["mx"] - collider["mn"]).length + 1.0
    pos = _ray_hit(bvh, local, Vector((1.0, 0.0, 0.0)), limit)
    neg = _ray_hit(bvh, local, Vector((-1.0, 0.0, 0.0)), limit)
    return -1.0 if pos and neg else (1.0 if (not pos and not neg) else None)


def _ray_hit(bvh, origin, direction, distance):
    hit = bvh.ray_cast(origin, direction, distance)
    return bool(hit and hit[0] is not None)


def _normal_sign(local, co, normal):
    return 1.0 if (Vector(local) - Vector(co)).dot(_safe_normal(normal)) >= 0.0 else -1.0


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
    if not _point_needs_push(oracle, collider, point):
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
    local = collider["m_inv"] @ point
    hit = bvh.find_nearest(local)
    if not hit or hit[0] is None:
        return point, 0.0
    return _push_from_hit(collider, local, hit, margin)


def _push_from_hit(collider, local, hit, margin):
    co, normal, _index, _dist = hit
    normal = _safe_normal(normal)
    signed = (local - co).dot(normal)
    if signed >= margin:
        return collider["m"] @ local, 0.0
    return collider["m"] @ (local + normal * (margin - signed)), margin - signed


def _voxel_signed_distance(scene, collider, point, margin):
    return _trilinear_distance(scene, collider, collider["m_inv"] @ point, margin)


def _trilinear_distance(scene, collider, local, margin):
    payload = _voxel_payload(scene, collider, margin)
    coords = _grid_coords(payload, local)
    base = tuple(max(0, min(payload["dims"][i] - 2, int(floor(coords[i])))) for i in range(3))
    frac = tuple(coords[i] - base[i] for i in range(3))
    return _trilinear_mix(_grid_values(scene, collider, payload, base), frac)


def _voxel_payload(scene, collider, margin):
    key = ("fiber_voxel", collider["sid"], collider["stamp"], round(margin, 6))
    cached = scene_cache_get(scene, key)
    return cached if cached is not None else scene_cache_set(scene, key, _new_voxel_payload(collider, margin))


def _new_voxel_payload(collider, margin):
    mn, mx = _local_voxel_bounds(collider, margin)
    dims = _grid_dims(mx - mn)
    step = Vector(tuple((mx[i] - mn[i]) / float(max(1, dims[i] - 1)) for i in range(3)))
    return {"mn": mn, "mx": mx, "dims": dims, "step": step, "values": {}}


def _inflate_bounds(mn, mx, margin):
    pad = Vector((margin, margin, margin))
    return mn - pad, mx + pad


def _local_voxel_bounds(collider, margin):
    corners = [collider["m_inv"] @ point for point in _corner_points(*_inflate_bounds(collider["mn"], collider["mx"], margin))]
    return _point_bounds(corners)


def _point_bounds(points):
    xs, ys, zs = [p.x for p in points], [p.y for p in points], [p.z for p in points]
    return Vector((min(xs), min(ys), min(zs))), Vector((max(xs), max(ys), max(zs)))


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
    if index not in payload["values"]:
        payload["values"][index] = _signed_grid_sample(collider, _grid_point(payload, index))
    return payload["values"][index]


def _grid_point(payload, index):
    return Vector(tuple(payload["mn"][i] + payload["step"][i] * float(index[i]) for i in range(3)))


def _signed_grid_sample(collider, local):
    bvh = _collider_bvh(collider)
    hit = None if bvh is None else bvh.find_nearest(local)
    return 1.0e9 if not hit or hit[0] is None else _signed_hit(collider, local, hit)


def _trilinear_mix(values, frac):
    c00 = _lerp(values[0], values[1], frac[0]), _lerp(values[2], values[3], frac[0])
    c01 = _lerp(values[4], values[5], frac[0]), _lerp(values[6], values[7], frac[0])
    return _lerp(_lerp(c00[0], c00[1], frac[1]), _lerp(c01[0], c01[1], frac[1]), frac[2])


def _lerp(a, b, t):
    return float(a) + (float(b) - float(a)) * float(t)


def _shell_nodes(scene, collider, margin, dense):
    key = ("fiber_shell", collider["sid"], collider["stamp"], round(margin, 6), bool(dense))
    cached = scene_cache_get(scene, key)
    return cached if cached is not None else scene_cache_set(scene, key, _build_shell_nodes(collider, margin, dense))


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
