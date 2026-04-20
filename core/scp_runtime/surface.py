from mathutils import Matrix, Vector
from mathutils.geometry import closest_point_on_tri

from .common import _EPS, as_vec3


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


def build_mesh_surface_data(mesh_obj, depsgraph):
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
    return None if not triangles else {"verts_world": verts, "triangles": triangles}


def _iter_triangles(surface):
    verts = surface["verts_world"]
    for tri in surface["triangles"]:
        i0, i1, i2 = (int(tri[0]), int(tri[1]), int(tri[2]))
        if min(i0, i1, i2) >= 0 and max(i0, i1, i2) < len(verts):
            yield (i0, i1, i2), (verts[i0], verts[i1], verts[i2])


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


def nearest_parent_param_from_world(parent_obj, target_world, depsgraph):
    surface = build_mesh_surface_data(parent_obj, depsgraph)
    hit = _nearest_triangle_hit(surface, target_world)
    if hit is None:
        return None
    weights = _closest_point_barycentric(*hit["abc"], hit["cp"])
    return None if weights is None else {"tri_vidx": hit["tri"], "tri_weights": tuple(float(v) for v in weights)}


def _nearest_triangle_hit(surface, target_world):
    if not surface:
        return None
    hits = [_triangle_hit(tri, abc, target_world) for tri, abc in _iter_triangles(surface)]
    hits = [hit for hit in hits if hit is not None]
    return None if not hits else min(hits, key=lambda hit: hit["d2"])


def _triangle_hit(tri, abc, target_world):
    cp = closest_point_on_tri(target_world, *abc)
    if cp is None:
        return None
    return {"tri": tri, "abc": abc, "cp": cp, "d2": (cp - target_world).length_squared}


def frame_from_parent_param(parent_obj, param, depsgraph):
    surface = build_mesh_surface_data(parent_obj, depsgraph)
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


def nearest_world_point_on_surface(mesh_obj, target_world, depsgraph):
    surface = build_mesh_surface_data(mesh_obj, depsgraph)
    hit = _nearest_triangle_hit(surface, target_world)
    return None if hit is None else hit["cp"]
