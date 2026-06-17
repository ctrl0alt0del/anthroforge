from mathutils import Vector

from ..utils import depsgraph_for_scene
from ..scp_runtime.common import as_id, as_vec3, find_scp_by_id, indexed_geometry_mesh_scp_obj, indexed_transform_scp_obj, mark_applied_matrix, scp_object_maps
from ..scp_runtime.runtime_state import attach_child_anchor_index, attach_child_origin_local, attach_initialized


def capture_owner_backsolve_snapshot(root, scene, owner_id):
    try:
        state = _snapshot_state(root, scene, owner_id)
    except Exception:
        return None
    return None if state is None else _snapshot_from_state(*state)


def _snapshot_state(root, scene, owner_id):
    scp, parent_id = find_scp_by_id(root, owner_id), _parent_id(root, owner_id)
    index = None if scene is None else scp_object_maps(scene, root.name)
    owner_obj = _transform_obj(index, owner_id)
    owner_geo = _geometry_obj(index, owner_id)
    parent_obj = _parent_frame(root, scene, parent_id, index)
    depsgraph = None if scene is None else depsgraph_for_scene(scene)
    valid = _can_snapshot(scp, owner_obj, parent_obj, depsgraph)
    return None if not valid else (scp, owner_obj, owner_geo, parent_id, parent_obj, depsgraph)


def _can_snapshot(scp, owner_obj, parent_obj, depsgraph):
    return bool(scp and owner_obj and parent_obj and depsgraph and attach_initialized(scp))


def _snapshot_from_state(scp, owner_obj, owner_geo, parent_id, parent_obj, depsgraph):
    anchor = _anchor_world(_anchor_mode(scp), attach_child_anchor_index(scp), attach_child_origin_local(scp), owner_obj, owner_geo, depsgraph)
    return None if anchor is None else _snapshot_data(scp, parent_id, parent_obj, anchor)


def _snapshot_data(scp, parent_id, parent_obj, anchor):
    return {
        "owner_id": as_id(getattr(scp, "id", "")),
        "parent_id": as_id(parent_id),
        "parent_local": _vec3_tuple(parent_obj.matrix_world.inverted() @ anchor),
        "anchor_mode": _anchor_mode(scp),
        "anchor_index": int(attach_child_anchor_index(scp)),
        "anchor_local": _vec3_tuple(attach_child_origin_local(scp)),
    }


def _vec3_tuple(value):
    vec = as_vec3(value, (0.0, 0.0, 0.0))
    return tuple(float(component) for component in vec)


def apply_owner_backsolve(root, scene, snapshot):
    try:
        state = _backsolve_state(root, scene, snapshot)
    except Exception:
        return False
    return False if state is None else _backsolve_owner(*state)


def _backsolve_state(root, scene, snapshot):
    data = dict(snapshot or {})
    owner_id, parent_id = as_id(data.get("owner_id")), as_id(data.get("parent_id"))
    index = None if scene is None else scp_object_maps(scene, root.name)
    owner_obj = _transform_obj(index, owner_id)
    owner_geo = _geometry_obj(index, owner_id)
    parent_obj = _parent_frame(root, scene, parent_id, index)
    depsgraph = None if scene is None else depsgraph_for_scene(scene)
    anchor = _anchor_world(data.get("anchor_mode"), data.get("anchor_index"), data.get("anchor_local"), owner_obj, owner_geo, depsgraph)
    return None if owner_obj is None or parent_obj is None or anchor is None else (owner_obj, parent_obj, anchor, data)


def _backsolve_owner(owner_obj, parent_obj, anchor_world, snapshot):
    target = parent_obj.matrix_world @ Vector(snapshot.get("parent_local", (0.0, 0.0, 0.0)))
    delta = target - anchor_world
    if delta.length <= 1.0e-7:
        return False
    matrix = owner_obj.matrix_world.copy()
    matrix.translation += delta
    owner_obj.matrix_world = matrix
    mark_applied_matrix(owner_obj)
    return True


def _anchor_world(mode, anchor_index, anchor_local, owner_obj, owner_geo, depsgraph):
    if owner_obj is None or depsgraph is None:
        return None
    if str(mode or "").upper() == "OBJECT_ORIGIN":
        return owner_obj.matrix_world.to_translation().copy()
    point = _surface_anchor_world(mode, anchor_index, owner_geo, depsgraph)
    return point if point is not None else owner_obj.matrix_world @ as_vec3(anchor_local, (0.0, 0.0, 0.0))


def _surface_anchor_world(mode, anchor_index, owner_geo, depsgraph):
    points = _anchor_points(mode, owner_geo, depsgraph)
    return _point_at(points, int(anchor_index if anchor_index is not None else -1))


def _anchor_points(mode, owner_geo, depsgraph):
    builder = _surface_builder(mode)
    return None if owner_geo is None else builder(owner_geo, depsgraph, cache={})


def _point_at(points, index):
    return None if points is None or index < 0 or index >= len(points) else points[index].copy()


def _anchor_mode(scp):
    mode = str(getattr(scp, "attach_child_anchor_mode", "FACE_CENTER") or "FACE_CENTER").upper()
    return mode if mode in {"FACE_CENTER", "VERTEX_NEAREST", "OBJECT_ORIGIN"} else "FACE_CENTER"


def _parent_frame(root, scene, parent_id, index=None):
    parent_frame_obj = _parent_frame_obj()
    transform = _transform_obj(index, parent_id)
    geometry = _geometry_obj(index, parent_id)
    return None if not parent_id else parent_frame_obj(transform, geometry)


def _parent_id(root, owner_id):
    scp = find_scp_by_id(root, owner_id)
    return "" if scp is None else getattr(scp, "parent_id", "")


def _transform_obj(index, scp_id):
    return None if index is None else indexed_transform_scp_obj(index, scp_id)


def _geometry_obj(index, scp_id):
    return None if index is None else indexed_geometry_mesh_scp_obj(index, scp_id)


def _surface_builder(mode):
    if str(mode or "").upper() == "VERTEX_NEAREST":
        from ..scp_runtime.surface import build_vertex_points
        return build_vertex_points
    from ..scp_runtime.surface import build_face_centers
    return build_face_centers


def _parent_frame_obj():
    from ..scp_runtime.parent_anchor import parent_frame_obj
    return parent_frame_obj
