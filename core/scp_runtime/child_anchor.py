from .common import as_id
from .surface import closest_child_face_center_to_parent, closest_child_vertex_to_parent, nearest_parent_param_from_world

_MODES = {"FACE_CENTER", "VERTEX_NEAREST", "OBJECT_ORIGIN"}


def capture_child_anchor(child_scp, child_obj, parent_obj, depsgraph, origin_obj=None):
    return _capture_for_mode(_mode(child_scp))(child_obj, parent_obj, depsgraph, origin_obj or child_obj)


def _mode(child_scp):
    mode = as_id(getattr(child_scp, "attach_child_anchor_mode", "")).upper()
    return mode if mode in _MODES else "FACE_CENTER"


def _capture_for_mode(mode):
    return {
        "FACE_CENTER": _capture_face_center,
        "VERTEX_NEAREST": _capture_vertex_nearest,
        "OBJECT_ORIGIN": _capture_object_origin,
    }.get(mode, _capture_face_center)


def _capture_face_center(child_obj, parent_obj, depsgraph, origin_obj):
    _ = origin_obj
    return _capture_candidate(closest_child_face_center_to_parent(child_obj, parent_obj, depsgraph))


def _capture_vertex_nearest(child_obj, parent_obj, depsgraph, origin_obj):
    _ = origin_obj
    return _capture_candidate(closest_child_vertex_to_parent(child_obj, parent_obj, depsgraph))


def _capture_object_origin(child_obj, parent_obj, depsgraph, origin_obj):
    _ = child_obj
    anchor = origin_obj.matrix_world.to_translation().copy()
    param = nearest_parent_param_from_world(parent_obj, anchor, depsgraph)
    return None if param is None else _candidate(anchor, param)


def _capture_candidate(candidate):
    return None if candidate is None else _candidate(candidate["child_anchor_world"], candidate["parent_param"])


def _candidate(anchor, param):
    return {"child_anchor_world": anchor, "parent_param": param}
