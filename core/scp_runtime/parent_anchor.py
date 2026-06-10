from mathutils import Vector

from .common import as_id
from .runtime_state import attach_parent_param
from .surface import basis_from_tangent_normal, frame_from_parent_param, nearest_parent_param_from_world

_MODES = {"SURFACE_NEAREST", "OBJECT_ORIGIN"}


def anchor_mode(child_scp):
    mode = as_id(getattr(child_scp, "attach_parent_anchor_mode", "")).upper()
    return mode if mode in _MODES else "SURFACE_NEAREST"


def is_surface_mode(mode):
    return str(mode or "").upper() == "SURFACE_NEAREST"


def is_surface_binding(binding):
    return is_surface_mode((binding or {}).get("mode"))


def parent_frame_obj(parent_transform_obj, parent_geometry_obj):
    return parent_transform_obj or parent_geometry_obj


def parent_origin_world(parent_transform_obj, parent_geometry_obj):
    obj = parent_frame_obj(parent_transform_obj, parent_geometry_obj)
    return None if obj is None else obj.matrix_world.to_translation().copy()


def capture_parent_binding(child_scp, parent_transform_obj, parent_geometry_obj, child_anchor_world, depsgraph, surface_cache):
    mode = anchor_mode(child_scp)
    return _capture_surface(parent_geometry_obj, child_anchor_world, depsgraph, surface_cache) if is_surface_mode(mode) else {"mode": "OBJECT_ORIGIN"}


def _capture_surface(parent_geometry_obj, child_anchor_world, depsgraph, surface_cache):
    if parent_geometry_obj is None:
        return None
    param = nearest_parent_param_from_world(parent_geometry_obj, child_anchor_world, depsgraph, cache=surface_cache)
    return None if param is None else {"mode": "SURFACE_NEAREST", "param": param}


def stored_parent_binding(child_scp):
    mode = anchor_mode(child_scp)
    return {"mode": "OBJECT_ORIGIN"} if not is_surface_mode(mode) else {"mode": mode, "param": _stored_param(child_scp)}


def _stored_param(child_scp):
    return attach_parent_param(child_scp) or {"tri_vidx": (-1, -1, -1), "tri_weights": (1.0, 0.0, 0.0)}


def resolve_parent_frame(binding, parent_transform_obj, parent_geometry_obj, depsgraph, surface_cache, tangent_hint=None, tangent_strategy="STABLE_SURFACE", flow_param=None):
    if not is_surface_binding(binding):
        return _origin_frame(parent_transform_obj, parent_geometry_obj)
    param = dict((binding or {}).get("param", {}) or {})
    return frame_from_parent_param(parent_geometry_obj, param, depsgraph, cache=surface_cache, tangent_hint=tangent_hint, tangent_strategy=tangent_strategy, flow_param=flow_param)


def _origin_frame(parent_transform_obj, parent_geometry_obj):
    obj = parent_frame_obj(parent_transform_obj, parent_geometry_obj)
    if obj is None:
        return None
    rot = obj.matrix_world.to_quaternion().to_matrix()
    basis, tangent, normal = basis_from_tangent_normal(rot @ Vector((1.0, 0.0, 0.0)), rot @ Vector((0.0, 0.0, 1.0)))
    point = obj.matrix_world.to_translation().copy()
    return {"point_world": point, "basis_world": basis, "tangent_world": tangent, "normal_world": normal}
