from ..queries.root import root_for_context
from .results import failure, success


def move_active_origin_to_attachment(context):
    if getattr(context, "mode", "OBJECT") != "OBJECT":
        return failure("Switch to Object Mode first.")
    root = root_for_context(context)
    pair, error = _resolved_active_child(root, context)
    if pair is None:
        return failure(error)
    ok, error = _move_origin_for_child(context, root, *pair)
    return success("Moved SCP origin to attachment.") if ok else failure(error)


def _resolved_active_child(root, context):
    scp = None if root is None else _active_scp()(root, context)
    obj = None if scp is None or root is None else _find_transform()(context.scene, root.name, scp.id)
    return ((scp, obj), "") if obj is not None else (None, "Active object must belong to an SCP.")


def _move_origin_for_child(context, root, child_scp, child_obj):
    point = _attachment_world(child_scp, child_obj)
    if point is None:
        return False, "Attachment has not been captured yet."
    if not _can_move_origin(child_obj):
        return False, "Transform object does not support origin moves."
    worlds = _bound_worlds(child_scp, child_obj)
    if not _move_origin_world(child_obj, point):
        return False, "Failed to move SCP origin."
    _restore_bound_worlds(worlds)
    _after_origin_move(context, root, child_scp)
    return True, ""


def _attachment_world(child_scp, child_obj):
    if not _attach_initialized()(child_scp):
        return None
    return child_obj.matrix_world @ _child_anchor_local(child_scp)


def _child_anchor_local(child_scp):
    return _as_vec3()(_attach_child_origin_local()(child_scp), (0.0, 0.0, 0.0))


def _can_move_origin(obj):
    data = getattr(obj, "data", None)
    return data is None or hasattr(data, "transform")


def _move_origin_world(obj, point):
    world = obj.matrix_world.copy()
    local = world.inverted() @ point
    if not _shift_object_data(getattr(obj, "data", None), local):
        return False
    obj.matrix_world = world @ _translation_matrix()(local)
    _update_data(getattr(obj, "data", None))
    return True


def _shift_object_data(data, local):
    if data is None:
        return True
    try:
        data.transform(_translation_matrix()(-local), shape_keys=True)
    except TypeError:
        data.transform(_translation_matrix()(-local))
    except Exception:
        return False
    return True


def _update_data(data):
    data.update() if hasattr(data, "update") else None


def _bound_worlds(scp, child_obj):
    rows = []
    for entry in getattr(scp, "bound_objects", ()):
        obj = getattr(entry, "object_ref", None)
        rows.append((obj, obj.matrix_world.copy())) if obj is not None and obj != child_obj else None
    return rows


def _restore_bound_worlds(rows):
    for obj, world in tuple(rows or ()):
        obj.matrix_world = world


def _after_origin_move(context, root, child_scp):
    _update_scene()(context.scene)
    ids = _subtree_ids(root, child_scp.id)
    _recapture_subtree(root, context.scene, ids)
    _sync_context()(context, dirty_hints=_dirty_hints_for()("SCP", ids), source="operator", event_type="UPDATE")


def _subtree_ids(root, scp_id):
    scp_by_id = _scp_prop_map()(root)
    kids, out, stack = _children_map()(scp_by_id), set(), [str(scp_id or "")]
    while stack:
        sid = stack.pop()
        if not sid or sid in out:
            continue
        out.add(sid)
        stack.extend(reversed(kids.get(sid, ())))
    return out


def _recapture_subtree(root, scene, ids):
    scp_by_id = _scp_prop_map()(root)
    wanted = set(ids or set())
    for sid in [sid for sid in _children_depth_order()(scp_by_id) if sid in wanted]:
        _recapture_one(scene, root.name, scp_by_id, sid)


def _recapture_one(scene, root_name, scp_by_id, sid):
    scp = scp_by_id.get(str(sid or ""))
    pid = "" if scp is None else str(getattr(scp, "parent_id", "") or "")
    child = None if scp is None else _find_transform()(scene, root_name, sid)
    parent = None if not pid else _find_transform()(scene, root_name, pid)
    cgeo = None if scp is None else _find_geometry()(scene, root_name, sid)
    pgeo = None if not pid else _find_geometry()(scene, root_name, pid)
    return bool(child and parent and _capture_attachment()(scp, child, cgeo, parent, pgeo))


def _translation_matrix():
    from mathutils import Matrix
    return Matrix.Translation


def _sync_context():
    try:
        from ...app.runtime_api import sync_context
    except ImportError:
        from app.runtime_api import sync_context
    return sync_context


def _dirty_hints_for():
    try:
        from ...core.deps.dirty_hints import dirty_hints_for
    except ImportError:
        from core.deps.dirty_hints import dirty_hints_for
    return dirty_hints_for


def _update_scene():
    try:
        from ...core.utils import update_scene_view_layer
    except ImportError:
        from core.utils import update_scene_view_layer
    return update_scene_view_layer


def _active_scp():
    try:
        from ...core.scp_runtime.object_roles import active_scp_from_context
    except ImportError:
        from core.scp_runtime.object_roles import active_scp_from_context
    return active_scp_from_context


def _find_transform():
    try:
        from ...core.scp_runtime.common import find_transform_scp_obj
    except ImportError:
        from core.scp_runtime.common import find_transform_scp_obj
    return find_transform_scp_obj


def _find_geometry():
    try:
        from ...core.scp_runtime.common import find_geometry_mesh_scp_obj
    except ImportError:
        from core.scp_runtime.common import find_geometry_mesh_scp_obj
    return find_geometry_mesh_scp_obj


def _scp_prop_map():
    try:
        from ...core.scp_runtime.common import scp_prop_map
    except ImportError:
        from core.scp_runtime.common import scp_prop_map
    return scp_prop_map


def _children_map():
    try:
        from ...core.scp_runtime.tree import children_map
    except ImportError:
        from core.scp_runtime.tree import children_map
    return children_map


def _children_depth_order():
    try:
        from ...core.scp_runtime.tree import children_depth_order
    except ImportError:
        from core.scp_runtime.tree import children_depth_order
    return children_depth_order


def _attach_initialized():
    try:
        from ...core.scp_runtime.runtime_state import attach_initialized
    except ImportError:
        from core.scp_runtime.runtime_state import attach_initialized
    return attach_initialized


def _attach_child_origin_local():
    try:
        from ...core.scp_runtime.runtime_state import attach_child_origin_local
    except ImportError:
        from core.scp_runtime.runtime_state import attach_child_origin_local
    return attach_child_origin_local


def _as_vec3():
    try:
        from ...core.scp_runtime.common import as_vec3
    except ImportError:
        from core.scp_runtime.common import as_vec3
    return as_vec3


def _capture_attachment():
    try:
        from ...core.scp_runtime.attachment_runtime import capture_attachment_from_link
    except ImportError:
        from core.scp_runtime.attachment_runtime import capture_attachment_from_link
    return capture_attachment_from_link
