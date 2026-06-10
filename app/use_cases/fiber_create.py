from mathutils import Vector

from ..queries.root import root_for_context
from .results import failure, success

try:
    from ...core.vcp.runtime_state import reset_fiber_runtime
except ImportError:
    from core.vcp.runtime_state import reset_fiber_runtime

try:
    from ...core.id_utils import next_prefixed_id
except ImportError:
    from core.id_utils import next_prefixed_id


def create_fiber_vcp(context):
    root = root_for_context(context)
    if root is None:
        return failure("No AF_ROOT found.")
    resolved = _resolved_inputs(context, root)
    if resolved is None:
        return failure("Select valid SCP geometry endpoints.")
    fiber = _new_fiber(root, *resolved)
    _activate(root.af_vcp_system, "FIBER", fiber.id)
    _sync_entity(root, context.scene, "FIBER", {fiber.id})
    proxy = _find_proxy(context.scene, root.name, fiber.id)
    _select_if_found(context, proxy)
    _sync_selection(context.scene, proxy)
    return success(f"Added {fiber.id}", value=fiber)


def _resolved_inputs(context, root):
    origin_id, insert_id = _endpoint_ids(context)
    if not origin_id or not insert_id:
        return None
    origin_raw = _first_attach_param(context.scene, root, origin_id)
    insert_raw = _first_attach_param(context.scene, root, insert_id)
    return None if origin_raw is None or insert_raw is None else (origin_id, insert_id, origin_raw, insert_raw)


def _endpoint_ids(context):
    origin = getattr(context.scene, "af_new_fiber_origin_obj", None)
    insert = getattr(context.scene, "af_new_fiber_insertion_obj", None)
    if not origin or not insert:
        return None, None
    return origin.get("af_scp_id", ""), insert.get("af_scp_id", "")


def _first_attach_param(scene, root, parent_id):
    parent = _find_geometry_mesh_scp_obj()(scene, root.name, parent_id)
    if parent is None:
        return None
    point = _nearest_parent_vertex()(parent, scene.cursor.location.copy())
    point = Vector((0.0, 0.0, 0.0)) if point is None else point
    return _encode_fiber_anchor()(point)


def _new_fiber(root, origin_id, insert_id, origin_raw, insert_raw):
    fibers = root.af_vcp_system.fibers
    fiber = fibers.add()
    fiber.id = next_prefixed_id(fibers, "FIBER")
    fiber.name = fiber.id
    fiber.a_parent_id, fiber.a_attach_param = origin_id, origin_raw
    fiber.b_parent_id, fiber.b_attach_param = insert_id, insert_raw
    _apply_values(fiber, _fiber_defaults())
    reset_fiber_runtime(fiber)
    return fiber


def _fiber_defaults():
    return {
        "node_count": 64,
        "iterations_interactive": 12,
        "iterations_bake": 180,
        "stretch_stiffness": 0.9,
        "bend_stiffness": 0.02,
        "collision_margin": 0.002,
        "damping": 0.01,
        "thickness": 0.01,
    }


def _apply_values(item, values):
    for key, value in values.items():
        setattr(item, key, value)


def _activate(vcp, kind, entity_id):
    vcp.active_vcp_type, vcp.active_vcp_id = str(kind or ""), str(entity_id or "")


def _select_if_found(context, obj):
    if obj is None:
        return
    for item in getattr(context, "selected_objects", ()):
        item.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def _sync_entity(root, scene, kind, entity_ids):
    hints = _dirty_hints_for()(kind, entity_ids)
    _sync_scene()(root=root, scene=scene, dirty_hints=hints)


def _sync_selection(scene, active_object):
    if active_object is None:
        return
    _notify_selection_changed()(scene, force=True, active_object=active_object)


def _sync_scene():
    try:
        from ...app.runtime_api import sync_scene
    except ImportError:
        from app.runtime_api import sync_scene
    return sync_scene


def _dirty_hints_for():
    try:
        from ...core.deps.dirty_hints import dirty_hints_for
    except ImportError:
        from core.deps.dirty_hints import dirty_hints_for
    return dirty_hints_for


def _find_geometry_mesh_scp_obj():
    try:
        from ...core.scp_runtime.common import find_geometry_mesh_scp_obj
    except ImportError:
        from core.scp_runtime.common import find_geometry_mesh_scp_obj
    return find_geometry_mesh_scp_obj


def _find_proxy(scene, root_name, fiber_id):
    for obj in getattr(scene, "objects", ()):
        if obj.get("af_fiber_proxy") and obj.get("af_root_name") == root_name and obj.get("af_fiber_id") == fiber_id:
            return obj
    return None


def _nearest_parent_vertex():
    try:
        from ...core.visualization.fiber_sync_helpers import nearest_parent_mesh_vertex_local_point
    except ImportError:
        from core.visualization.fiber_sync_helpers import nearest_parent_mesh_vertex_local_point
    return nearest_parent_mesh_vertex_local_point


def _encode_fiber_anchor():
    try:
        from ...core.attachment_codec import encode_fiber_mesh_anchor
    except ImportError:
        from core.attachment_codec import encode_fiber_mesh_anchor
    return encode_fiber_mesh_anchor


def _notify_selection_changed():
    try:
        from ...core.visualization.control_runtime import notify_selection_changed
    except ImportError:
        from core.visualization.control_runtime import notify_selection_changed
    return notify_selection_changed
