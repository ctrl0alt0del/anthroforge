from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from .common import _EPS


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


def _cache_key(mesh_obj):
    return None if mesh_obj is None else int(mesh_obj.as_pointer())


def build_mesh_surface_data(mesh_obj, depsgraph, cache=None):
    key = _cache_key(mesh_obj)
    if cache is not None and key in cache:
        return cache[key]
    surface = _build_surface(mesh_obj, depsgraph)
    if cache is not None and key is not None and surface is not None:
        cache[key] = surface
    return surface


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
    verts = [obj_eval.matrix_world @ v.co for v in mesh_eval.vertices]
    triangles = [tuple(tri.vertices) for tri in mesh_eval.loop_triangles]
    bvh = None if not triangles else BVHTree.FromPolygons(verts, triangles, all_triangles=True)
    return None if bvh is None else {"bvh": bvh, "face_centers": _face_centers(obj_eval, mesh_eval), "triangles": triangles, "verts_world": verts}


def _face_centers(obj_eval, mesh_eval):
    matrix_world = obj_eval.matrix_world.copy()
    return [matrix_world @ poly.center for poly in mesh_eval.polygons]


def build_face_centers(mesh_obj, depsgraph, cache=None):
    surface = build_mesh_surface_data(mesh_obj, depsgraph, cache=cache)
    return None if not surface else surface["face_centers"]


def build_vertex_points(mesh_obj, depsgraph, cache=None):
    surface = build_mesh_surface_data(mesh_obj, depsgraph, cache=cache)
    return None if not surface else surface["verts_world"]


def _closest_point_barycentric(a, b, c, point):
    v0 = b - a
    v1 = c - a
    v2 = point - a
    d00, d01, d11 = v0.dot(v0), v0.dot(v1), v1.dot(v1)
    d20, d21 = v2.dot(v0), v2.dot(v1)
    denom = (d00 * d11) - (d01 * d01)
    return None if abs(denom) <= _EPS else _normalized_weights(d00, d01, d11, d20, d21, denom)


def _normalized_weights(d00, d01, d11, d20, d21, denom):
    v = ((d11 * d20) - (d01 * d21)) / denom
    w = ((d00 * d21) - (d01 * d20)) / denom
    weights = [0.0 if abs(value) < 1.0e-8 else float(value) for value in (1.0 - v - w, v, w)]
    total = sum(weights)
    return None if abs(total) <= _EPS else tuple(weight / total for weight in weights)


def _nearest_triangle_hit(surface, target_world):
    if not surface:
        return None
    hit = surface["bvh"].find_nearest(target_world)
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
    for point in points or ():
        candidate = _child_anchor_candidate(point, parent_surface)
        best = candidate if candidate and (best is None or candidate["d2"] < best["d2"]) else best
    return best


def _child_anchor_candidate(child_anchor_world, parent_surface):
    hit = _nearest_triangle_hit(parent_surface, child_anchor_world)
    param = None if hit is None else _param_from_hit(hit)
    if param is None:
        return None
    return {"child_anchor_world": child_anchor_world, "parent_param": param, "d2": hit["d2"]}


def frame_from_parent_param(parent_obj, param, depsgraph, cache=None):
    surface = build_mesh_surface_data(parent_obj, depsgraph, cache=cache)
    if not surface:
        return None
    return _frame_from_surface(parent_obj, surface["verts_world"], param)


def _frame_from_surface(parent_obj, verts, param):
    tri = tuple(param.get("tri_vidx", (-1, -1, -1)))
    weights = tuple(param.get("tri_weights", (1.0, 0.0, 0.0)))
    return None if len(tri) != 3 or len(weights) != 3 else _frame_from_tri(parent_obj, verts, tri, weights)


def _frame_from_tri(parent_obj, verts, tri, weights):
    i0, i1, i2 = (int(tri[0]), int(tri[1]), int(tri[2]))
    if min(i0, i1, i2) < 0 or max(i0, i1, i2) >= len(verts):
        return None
    a, b, c = verts[i0], verts[i1], verts[i2]
    point = (a * float(weights[0])) + (b * float(weights[1])) + (c * float(weights[2]))
    tangent, normal = _frame_axes(parent_obj, a, b, c)
    basis, tangent, normal = basis_from_tangent_normal(tangent, normal)
    return {"point_world": point, "basis_world": basis, "tangent_world": tangent, "normal_world": normal}


def _frame_axes(parent_obj, a, b, c):
    tangent = b - a
    normal = (b - a).cross(c - a)
    world = parent_obj.matrix_world.to_3x3()
    tangent = world @ Vector((1.0, 0.0, 0.0)) if tangent.length <= _EPS else tangent
    normal = world @ Vector((0.0, 0.0, 1.0)) if normal.length <= _EPS else normal
    return tangent, normal
