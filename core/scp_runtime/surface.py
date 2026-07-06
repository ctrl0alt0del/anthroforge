from heapq import heappop, heappush

from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from ..utils import depsgraph_for_scene, scene_cache_get, scene_cache_set, scene_for_id
from .common import _EPS, matrix_flat16

_AXIS_VECTORS = {
    "POS_X": Vector((1.0, 0.0, 0.0)),
    "NEG_X": Vector((-1.0, 0.0, 0.0)),
    "POS_Y": Vector((0.0, 1.0, 0.0)),
    "NEG_Y": Vector((0.0, -1.0, 0.0)),
    "POS_Z": Vector((0.0, 0.0, 1.0)),
    "NEG_Z": Vector((0.0, 0.0, -1.0)),
}


def _normalized(vector, fallback):
    value = Vector(vector)
    if value.length <= _EPS:
        return Vector(fallback)
    value.normalize()
    return value


def basis_from_tangent_normal(tangent, normal):
    tangent_vec = _normalized(tangent, (1.0, 0.0, 0.0))
    normal_vec = Vector(normal) - tangent_vec * Vector(normal).dot(tangent_vec)
    normal_vec = _fallback_normal(tangent_vec, normal_vec)
    bitangent = _normalized(normal_vec.cross(tangent_vec), (0.0, 1.0, 0.0))
    tangent_vec = _normalized(bitangent.cross(normal_vec), (1.0, 0.0, 0.0))
    return Matrix((tangent_vec, bitangent, normal_vec)).transposed(), tangent_vec, normal_vec


def _fallback_normal(tangent_vec, normal_vec):
    if normal_vec.length > _EPS:
        return _normalized(normal_vec, (0.0, 0.0, 1.0))
    axis = Vector((0.0, 0.0, 1.0)) if abs(tangent_vec.dot(Vector((0.0, 0.0, 1.0)))) <= 0.99 else Vector((0.0, 1.0, 0.0))
    return _normalized(axis - tangent_vec * axis.dot(tangent_vec), (0.0, 0.0, 1.0))


def _plane_project(vector, normal):
    return Vector(vector) - Vector(normal) * Vector(vector).dot(Vector(normal))


def project_tangent_hint(tangent_hint, normal, fallback):
    hint = _plane_project(tangent_hint, normal)
    return _normalized(hint, _projected_fallback(normal, fallback))


def _projected_fallback(normal, fallback):
    tangent = _plane_project(fallback, normal)
    if tangent.length > _EPS:
        return tangent
    axis = Vector((1.0, 0.0, 0.0)) if abs(Vector(normal).dot(Vector((1.0, 0.0, 0.0)))) <= 0.99 else Vector((0.0, 1.0, 0.0))
    return _plane_project(axis, normal)


def resolve_tangent_strategy(parent_obj, strategy):
    mode = str(strategy or "STABLE_SURFACE")
    return "DEFORMATION_FLOW" if mode == "AUTO" and _curve_modifier(parent_obj) else mode


def flow_hint_world(parent_obj):
    return _rotation(parent_obj) @ _flow_axis_local(parent_obj)


def _rotation(parent_obj):
    return Matrix.Identity(3) if parent_obj is None else parent_obj.matrix_world.to_quaternion().to_matrix()


def _flow_axis_local(parent_obj):
    modifier = _curve_modifier(parent_obj)
    axis = "POS_X" if modifier is None else str(modifier.deform_axis or "POS_X")
    return _AXIS_VECTORS.get(axis, _AXIS_VECTORS["POS_X"]).copy()


def _curve_modifier(parent_obj):
    modifiers = () if parent_obj is None else parent_obj.modifiers
    return next((mod for mod in modifiers if mod.type == "CURVE" and mod.show_viewport and getattr(mod, "object", None)), None)


def _cache_key(mesh_obj):
    return None if mesh_obj is None else int(mesh_obj.as_pointer())


def _surface_entry_key(mesh_obj):
    return None if mesh_obj is None else f"surface:{_cache_key(mesh_obj)}"


def _data_id(data):
    try:
        return int(data.as_pointer())
    except Exception:
        return id(data)


def _mesh_counts(data):
    return (0, 0) if data is None else (len(data.vertices), len(data.polygons))


def _surface_stamp(obj_eval):
    data = getattr(obj_eval, "data", None)
    return (_data_id(data), _mesh_counts(data), tuple(matrix_flat16(obj_eval.matrix_world)))


def _remember_surface(cache, key, stamp, surface):
    if cache is not None and key is not None:
        cache[key] = {"stamp": stamp, "surface": surface}
    return surface


def _local_surface(cache, key, stamp):
    entry = None if cache is None or key is None else cache.get(key)
    return None if entry is None or entry.get("stamp") != stamp else entry.get("surface")


def _cached_surface(mesh_obj, depsgraph):
    scene = scene_for_id(mesh_obj)
    if scene is None or mesh_obj is None or depsgraph is None:
        return None, None, None
    obj_eval = mesh_obj.evaluated_get(depsgraph)
    return scene, _surface_stamp(obj_eval), scene_cache_get(scene, _surface_entry_key(mesh_obj))


def _store_surface(scene, mesh_obj, stamp, surface):
    if scene is not None and mesh_obj is not None and surface is not None:
        scene_cache_set(scene, _surface_entry_key(mesh_obj), {"stamp": stamp, "surface": surface})


def build_mesh_surface_data(mesh_obj, depsgraph, cache=None):
    key = _cache_key(mesh_obj)
    scene, stamp, entry = _cached_surface(mesh_obj, depsgraph)
    local = _local_surface(cache, key, stamp)
    if local is not None:
        return local
    if entry and entry.get("stamp") == stamp:
        return _remember_surface(cache, key, stamp, entry["surface"])
    surface = _build_surface(mesh_obj, depsgraph)
    _store_surface(scene, mesh_obj, stamp, surface)
    return _remember_surface(cache, key, stamp, surface)


def _build_surface(mesh_obj, depsgraph):
    obj_eval = mesh_obj.evaluated_get(depsgraph)
    mesh_eval = obj_eval.to_mesh()
    if mesh_eval is None:
        return None
    try:
        return _surface_payload(obj_eval, mesh_eval)
    finally:
        obj_eval.to_mesh_clear()


def _surface_payload(obj_eval, mesh_eval):
    if len(mesh_eval.vertices) <= 0:
        return None
    mesh_eval.calc_loop_triangles()
    verts_local = [v.co.copy() for v in mesh_eval.vertices]
    verts = [obj_eval.matrix_world @ v for v in verts_local]
    triangles = [tuple(tri.vertices) for tri in mesh_eval.loop_triangles]
    return _surface_payload_data(obj_eval, mesh_eval, verts_local, verts, triangles)


def _surface_payload_data(obj_eval, mesh_eval, verts_local, verts_world, triangles):
    bvh_local = None if not triangles else BVHTree.FromPolygons(verts_local, triangles, all_triangles=True)
    bvh_world = None if not triangles else BVHTree.FromPolygons(verts_world, triangles, all_triangles=True)
    if bvh_local is None or bvh_world is None:
        return None
    return {
        "bvh_local": bvh_local, "bvh_world": bvh_world, "face_centers": _face_centers(obj_eval, mesh_eval),
        "triangles": triangles, "verts_world": verts_world, "bounds_world": _world_bounds(verts_world),
        "route_graph": _surface_route_graph(verts_world, triangles),
    }


def _surface_route_graph(verts_world, triangles):
    graph = {i: [] for i in range(len(verts_world))}
    seen = set()
    for tri in triangles:
        _link_surface_edges(graph, verts_world, tri, seen)
    return graph


def _link_surface_edges(graph, verts_world, tri, seen):
    for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
        _link_surface_edge(graph, verts_world, seen, a, b)


def _link_surface_edge(graph, verts_world, seen, a, b):
    edge = tuple(sorted((int(a), int(b))))
    if edge in seen:
        return
    seen.add(edge)
    cost = (verts_world[edge[1]] - verts_world[edge[0]]).length
    graph[edge[0]].append((edge[1], cost))
    graph[edge[1]].append((edge[0], cost))


def _face_centers(obj_eval, mesh_eval):
    matrix_world = obj_eval.matrix_world.copy()
    return [matrix_world @ poly.center for poly in mesh_eval.polygons]


def _world_bounds(verts_world):
    xs = [v.x for v in verts_world]
    ys = [v.y for v in verts_world]
    zs = [v.z for v in verts_world]
    return Vector((min(xs), min(ys), min(zs))), Vector((max(xs), max(ys), max(zs)))


def build_face_centers(mesh_obj, depsgraph, cache=None):
    surface = build_mesh_surface_data(mesh_obj, depsgraph, cache=cache)
    return None if not surface else surface["face_centers"]


def build_vertex_points(mesh_obj, depsgraph, cache=None):
    surface = build_mesh_surface_data(mesh_obj, depsgraph, cache=cache)
    return None if not surface else surface["verts_world"]


def surface_shortest_vertex_path(surface, start_vertex, end_vertex):
    if not _route_vertices_ok(surface, start_vertex, end_vertex):
        return None
    path = _route_vertex_path(surface["route_graph"], surface["verts_world"], start_vertex, end_vertex)
    return None if path is None else [surface["verts_world"][i].copy() for i in path]


def surface_shortest_param_path(surface, start_param, end_param):
    setup = _param_route_setup(surface, start_param, end_param)
    if setup is None:
        return None
    points, start, end, extra = setup
    path = _route_path(surface["route_graph"], points, start, end, extra)
    return None if path is None else [points[i].copy() for i in path]


def _param_route_setup(surface, start_param, end_param):
    verts = tuple(surface.get("verts_world", ())) if surface else ()
    endpoints = (_route_param_endpoint(verts, start_param), _route_param_endpoint(verts, end_param))
    if not verts or any(endpoint is None for endpoint in endpoints):
        return None
    points = verts + tuple(endpoint["point"] for endpoint in endpoints if endpoint["vertex"] < 0)
    nodes = _endpoint_node_indices(endpoints, len(verts))
    extra = _temp_route_edges(verts, endpoints, nodes)
    _add_direct_param_edge(extra, endpoints, nodes)
    return points, nodes[0], nodes[1], extra


def _route_param_endpoint(verts, param):
    tri = tuple(dict(param or {}).get("tri_vidx", (-1, -1, -1)))
    weights = tuple(dict(param or {}).get("tri_weights", (1.0, 0.0, 0.0)))
    abc = _tri_points(verts, tri) if len(tri) == 3 and len(weights) == 3 else None
    if abc is None:
        return None
    point = _weighted_point(abc, weights)
    return {"tri": tuple(int(v) for v in tri), "weights": weights, "point": point, "vertex": _weighted_vertex(tri, weights)}


def _weighted_vertex(tri, weights, eps=1.0e-6):
    for vidx, weight in zip(tuple(tri or ()), tuple(weights or ())):
        if abs(float(weight) - 1.0) <= eps:
            return int(vidx)
    return -1


def _endpoint_node_indices(endpoints, base):
    out, temp = [], 0
    for endpoint in endpoints:
        if endpoint["vertex"] >= 0:
            out.append(endpoint["vertex"])
        else:
            out.append(base + temp); temp += 1
    return tuple(out)


def _temp_route_edges(verts, endpoints, nodes):
    extra = {}
    for endpoint, node in zip(endpoints, nodes):
        if endpoint["vertex"] < 0:
            _link_temp_route_node(extra, verts, endpoint, node)
    return extra


def _link_temp_route_node(extra, verts, endpoint, node):
    extra.setdefault(node, [])
    for vidx in endpoint["tri"]:
        cost = (endpoint["point"] - verts[int(vidx)]).length
        extra[node].append((int(vidx), cost))
        extra.setdefault(int(vidx), []).append((node, cost))


def _add_direct_param_edge(extra, endpoints, nodes):
    if nodes[0] == nodes[1] or endpoints[0]["tri"] != endpoints[1]["tri"]:
        return
    cost = (endpoints[0]["point"] - endpoints[1]["point"]).length
    extra.setdefault(nodes[0], []).append((nodes[1], cost))
    extra.setdefault(nodes[1], []).append((nodes[0], cost))


def _route_vertices_ok(surface, start_vertex, end_vertex):
    graph = None if surface is None else surface.get("route_graph")
    size = 0 if graph is None else len(graph)
    return 0 <= int(start_vertex) < size and 0 <= int(end_vertex) < size


def _route_vertex_path(graph, verts_world, start_vertex, end_vertex):
    return _route_path(graph, verts_world, int(start_vertex), int(end_vertex), {})


def _route_path(graph, points, start, end, extra):
    heap, came, dist, seen = [(0.0, int(start))], {}, {int(start): 0.0}, set()
    while heap:
        _score, node = heappop(heap)
        if node == int(end):
            return _route_reconstruct(came, node)
        if node in seen:
            continue
        seen.add(node)
        for nxt, cost in _route_neighbors(graph, extra, node):
            _push_route_neighbor(heap, came, dist, points, node, nxt, cost, end)
    return None


def _route_neighbors(graph, extra, node):
    return tuple(graph.get(node, ())) + tuple(extra.get(node, ()))


def _push_route_neighbor(heap, came, dist, verts_world, node, nxt, cost, end_vertex):
    cand = dist[node] + cost
    if cand >= dist.get(nxt, 1.0e18):
        return
    dist[nxt], came[nxt] = cand, node
    goal = verts_world[int(end_vertex)]
    heappush(heap, (cand + (goal - verts_world[int(nxt)]).length, int(nxt)))


def _route_reconstruct(came, goal):
    node, out = int(goal), [int(goal)]
    while node in came:
        node = came[node]
        out.append(node)
    return list(reversed(out))


def surface_bvh_local(mesh_obj, depsgraph=None, cache=None):
    if mesh_obj is None or mesh_obj.type != "MESH":
        return None
    depsgraph = depsgraph or depsgraph_for_scene(scene_for_id(mesh_obj))
    surface = build_mesh_surface_data(mesh_obj, depsgraph, cache=cache)
    return None if not surface else surface["bvh_local"]


def _closest_point_barycentric(a, b, c, point):
    return _exact_hit_weights(a, b, c, point) or _triangle_weights(a, b, c, point)


def _exact_hit_weights(a, b, c, point):
    if _same_point(point, a):
        return 1.0, 0.0, 0.0
    if _same_point(point, b):
        return 0.0, 1.0, 0.0
    return (0.0, 0.0, 1.0) if _same_point(point, c) else None


def _same_point(a, b, eps=_EPS):
    return (a - b).dot(a - b) <= float(eps) * float(eps)


def _triangle_weights(a, b, c, point):
    v0, v1, v2 = b - a, c - a, point - a
    d00, d01, d11 = v0.dot(v0), v0.dot(v1), v1.dot(v1)
    d20, d21 = v2.dot(v0), v2.dot(v1)
    denom = (d00 * d11) - (d01 * d01)
    return None if _small_denom(denom, d00, d01, d11) else _normalized_weights(d00, d01, d11, d20, d21, denom)


def _small_denom(denom, d00, d01, d11, eps=1.0e-12):
    scale = max(abs(d00 * d11), abs(d01 * d01))
    tol = float(eps) if scale <= 0.0 else scale * float(eps)
    return abs(denom) <= tol


def _normalized_weights(d00, d01, d11, d20, d21, denom):
    v = ((d11 * d20) - (d01 * d21)) / denom
    w = ((d00 * d21) - (d01 * d20)) / denom
    weights = [0.0 if abs(value) < 1.0e-8 else float(value) for value in (1.0 - v - w, v, w)]
    total = sum(weights)
    return None if abs(total) <= _EPS else tuple(weight / total for weight in weights)


def _nearest_triangle_hit(surface, target_world):
    if not surface:
        return None
    hit = surface["bvh_world"].find_nearest(target_world)
    return _hit_from_bvh(surface, hit)


def _hit_from_bvh(surface, hit):
    if not hit or hit[2] is None:
        return None
    cp, _normal, index, dist = hit
    if not (0 <= int(index) < len(surface["triangles"])):
        return None
    tri = surface["triangles"][int(index)]
    abc = tuple(surface["verts_world"][int(i)] for i in tri)
    return {"tri": tri, "abc": abc, "cp": cp, "d2": float(dist) * float(dist)}


def _param_from_hit(hit):
    weights = _closest_point_barycentric(*hit["abc"], hit["cp"])
    if weights is None:
        return None
    return {"tri_vidx": hit["tri"], "tri_weights": tuple(float(value) for value in weights)}


def nearest_parent_param_from_world(parent_obj, target_world, depsgraph, cache=None):
    surface = build_mesh_surface_data(parent_obj, depsgraph, cache=cache)
    hit = _nearest_triangle_hit(surface, target_world)
    return None if hit is None else _param_from_hit(hit)


def closest_child_face_center_to_parent(child_obj, parent_obj, depsgraph, cache=None):
    centers = build_face_centers(child_obj, depsgraph, cache=cache)
    parent_surface = build_mesh_surface_data(parent_obj, depsgraph, cache=cache)
    return _closest_child_points_to_parent(centers, parent_surface)


def closest_child_vertex_to_parent(child_obj, parent_obj, depsgraph, cache=None):
    points = build_vertex_points(child_obj, depsgraph, cache=cache)
    parent_surface = build_mesh_surface_data(parent_obj, depsgraph, cache=cache)
    return _closest_child_points_to_parent(points, parent_surface)


def _closest_child_points_to_parent(points, parent_surface):
    best = None
    for index, point in enumerate(points or ()):
        candidate = _child_anchor_candidate(point, parent_surface, index)
        best = candidate if candidate and (best is None or candidate["d2"] < best["d2"]) else best
    return best


def _child_anchor_candidate(child_anchor_world, parent_surface, child_index=-1):
    hit = _nearest_triangle_hit(parent_surface, child_anchor_world)
    param = None if hit is None else _param_from_hit(hit)
    if param is None:
        return None
    return {"child_anchor_world": child_anchor_world, "parent_param": param, "child_index": int(child_index), "d2": hit["d2"]}


def frame_from_parent_param(parent_obj, param, depsgraph, cache=None, tangent_hint=None, tangent_strategy="STABLE_SURFACE", flow_param=None):
    surface = build_mesh_surface_data(parent_obj, depsgraph, cache=cache)
    if not surface:
        return None
    return _frame_from_surface(parent_obj, surface["verts_world"], param, tangent_hint, tangent_strategy, flow_param)


def _frame_from_surface(parent_obj, verts, param, tangent_hint, tangent_strategy, flow_param):
    tri = tuple(param.get("tri_vidx", (-1, -1, -1)))
    weights = tuple(param.get("tri_weights", (1.0, 0.0, 0.0)))
    args = parent_obj, verts, tri, weights, tangent_hint, tangent_strategy, flow_param
    return None if len(tri) != 3 or len(weights) != 3 else _frame_from_tri(*args)


def _frame_from_tri(parent_obj, verts, tri, weights, tangent_hint, tangent_strategy, flow_param):
    abc = _tri_points(verts, tri)
    if abc is None:
        return None
    point = _weighted_point(abc, weights)
    normal = _frame_normal(parent_obj, *abc)
    flow_point = _param_point(verts, flow_param)
    tangent = _frame_tangent(parent_obj, point, normal, tangent_strategy, tangent_hint, flow_point, abc[1] - abc[0])
    basis, tangent, normal = basis_from_tangent_normal(tangent, normal)
    return {"point_world": point, "basis_world": basis, "tangent_world": tangent, "normal_world": normal}


def _tri_points(verts, tri):
    i0, i1, i2 = (int(tri[0]), int(tri[1]), int(tri[2]))
    if min(i0, i1, i2) < 0 or max(i0, i1, i2) >= len(verts):
        return None
    return verts[i0], verts[i1], verts[i2]


def _weighted_point(abc, weights):
    return sum((point * float(weight) for point, weight in zip(abc, weights)), Vector((0.0, 0.0, 0.0)))


def _param_point(verts, param):
    if not isinstance(param, dict):
        return None
    abc = _tri_points(verts, tuple(param.get("tri_vidx", (-1, -1, -1))))
    weights = tuple(param.get("tri_weights", (1.0, 0.0, 0.0)))
    return None if abc is None or len(weights) != 3 else _weighted_point(abc, weights)


def _frame_normal(parent_obj, a, b, c):
    normal = (b - a).cross(c - a)
    return _rotation(parent_obj) @ Vector((0.0, 0.0, 1.0)) if normal.length <= _EPS else normal


def _frame_tangent(parent_obj, point, normal, tangent_strategy, tangent_hint, flow_point, fallback):
    if tangent_strategy == "DEFORMATION_FLOW":
        tangent = _flow_tangent(point, normal, flow_point, fallback)
        if tangent is not None:
            return tangent
    if tangent_hint is not None:
        return _hint_tangent(_rotation(parent_obj), normal, tangent_hint)
    tangent = Vector(fallback)
    return _rotation(parent_obj) @ Vector((1.0, 0.0, 0.0)) if tangent.length <= _EPS else tangent


def _flow_tangent(point, normal, flow_point, fallback):
    # Use the captured secondary surface point so curved deformation can rotate safely.
    if flow_point is None:
        return None
    delta = Vector(flow_point) - Vector(point)
    return None if delta.length <= _EPS else project_tangent_hint(delta, normal, fallback)


def _hint_tangent(rotation, normal, tangent_hint):
    # Reapplying scale here makes flat faces twist, so stored hints use rotation only.
    return project_tangent_hint(rotation @ Vector(tangent_hint), normal, _hint_fallback(rotation, normal))


def _hint_fallback(rotation, normal):
    tangent = _plane_project(rotation @ Vector((1.0, 0.0, 0.0)), normal)
    return tangent if tangent.length > _EPS else _plane_project(rotation @ Vector((0.0, 1.0, 0.0)), normal)
