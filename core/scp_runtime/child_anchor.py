from mathutils import Vector

from .common import as_id
from ..shortcuts.session_state import active_child_override
from .parent_anchor import anchor_mode as parent_anchor_mode, capture_parent_binding, parent_origin_world
from .surface import build_face_centers, build_vertex_points, closest_child_face_center_to_parent, closest_child_vertex_to_parent

_MODES = {"FACE_CENTER", "VERTEX_NEAREST", "OBJECT_ORIGIN"}


def capture_child_anchor(child_scp, child_geometry_obj, parent_transform_obj, parent_geometry_obj, depsgraph, origin_obj=None, surface_cache=None):
    mode = anchor_mode(child_scp)
    origin = origin_obj or child_geometry_obj
    if parent_anchor_mode(child_scp) == "OBJECT_ORIGIN":
        return _capture_to_parent_origin(mode, child_scp, child_geometry_obj, parent_transform_obj, parent_geometry_obj, depsgraph, origin, surface_cache)
    return _capture_to_parent_surface(mode, child_scp, child_geometry_obj, parent_transform_obj, parent_geometry_obj, depsgraph, origin, surface_cache)


def anchor_mode(child_scp):
    override = active_child_override(child_scp)
    if override in _MODES:
        return override
    mode = as_id(getattr(child_scp, "attach_child_anchor_mode", "")).upper()
    return mode if mode in _MODES else "FACE_CENTER"


def _capture_to_parent_surface(mode, child_scp, child_geometry_obj, parent_transform_obj, parent_geometry_obj, depsgraph, origin_obj, surface_cache):
    if mode == "OBJECT_ORIGIN":
        return _capture_fixed_origin(child_scp, origin_obj, parent_transform_obj, parent_geometry_obj, depsgraph, surface_cache)
    candidate = _surface_candidate(mode, child_geometry_obj, parent_geometry_obj, depsgraph, surface_cache)
    return _wrap_surface_candidate(candidate)


def _capture_to_parent_origin(mode, child_scp, child_geometry_obj, parent_transform_obj, parent_geometry_obj, depsgraph, origin_obj, surface_cache):
    if mode == "OBJECT_ORIGIN":
        return _capture_fixed_origin(child_scp, origin_obj, parent_transform_obj, parent_geometry_obj, depsgraph, surface_cache)
    target = parent_origin_world(parent_transform_obj, parent_geometry_obj)
    points = _candidate_points(mode, child_geometry_obj, depsgraph, surface_cache)
    return _candidate_from_points(points, target)


def _capture_fixed_origin(child_scp, origin_obj, parent_transform_obj, parent_geometry_obj, depsgraph, surface_cache):
    if origin_obj is None:
        return None
    anchor = origin_obj.matrix_world.to_translation().copy()
    binding = capture_parent_binding(child_scp, parent_transform_obj, parent_geometry_obj, anchor, depsgraph, surface_cache)
    return None if binding is None else _candidate(anchor, -1, binding)


def _surface_candidate(mode, child_geometry_obj, parent_geometry_obj, depsgraph, surface_cache):
    if child_geometry_obj is None or parent_geometry_obj is None:
        return None
    builder = closest_child_face_center_to_parent if mode == "FACE_CENTER" else closest_child_vertex_to_parent
    return builder(child_geometry_obj, parent_geometry_obj, depsgraph, cache=surface_cache)


def _wrap_surface_candidate(candidate):
    if candidate is None:
        return None
    binding = {"mode": "SURFACE_NEAREST", "param": candidate["parent_param"]}
    return _candidate(candidate["child_anchor_world"], int(candidate.get("child_index", -1)), binding)


def _candidate_points(mode, child_geometry_obj, depsgraph, surface_cache):
    if child_geometry_obj is None:
        return None
    builder = build_face_centers if mode == "FACE_CENTER" else build_vertex_points
    return builder(child_geometry_obj, depsgraph, cache=surface_cache)


def _candidate_from_points(points, target_world):
    index = _nearest_point_index(points, target_world)
    return None if index < 0 else _candidate(points[index], index, {"mode": "OBJECT_ORIGIN"})


def _nearest_point_index(points, target_world):
    if target_world is None:
        return -1
    best_index, best_d2 = -1, None
    for index, point in enumerate(points or ()):
        d2 = (Vector(point) - Vector(target_world)).length_squared
        best_index, best_d2 = (index, d2) if best_d2 is None or d2 < best_d2 else (best_index, best_d2)
    return best_index


def _candidate(anchor, index, binding):
    return {"child_anchor_world": anchor, "parent_binding": binding, "child_anchor_index": int(index)}
