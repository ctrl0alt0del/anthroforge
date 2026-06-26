from ..queries.root import root_for_context
from .results import failure, success


def delete_vcp_in_tree(context, node_type, node_id):
    root = root_for_context(context)
    target = _resolved_target(root, node_type, node_id)
    if target is None:
        return failure("VCP not found.")
    kind, entity_id = target
    _clear_runtime_cache(kind, entity_id)
    if not _delete_target(root, context.scene, kind, entity_id):
        return failure("VCP not found.")
    _sync_delete(root, context.scene)
    return success(value=entity_id)


def _resolved_target(root, node_type, node_id):
    kind, entity_id = _target_key(node_type, node_id)
    if root is None or not kind or not entity_id:
        return None
    return (kind, entity_id) if _has_target(root.af_vcp_system, kind, entity_id) else None


def _target_key(node_type, node_id):
    kind = str(node_type or "").upper()
    entity_id = str(node_id or "")
    return (kind if kind in {"FIBER", "MUSCLE"} else "", entity_id)


def _has_target(vcp, kind, entity_id):
    items = vcp.fibers if kind == "FIBER" else vcp.muscles
    return any(str(getattr(item, "id", "")) == entity_id for item in items)


def _clear_runtime_cache(kind, entity_id):
    if kind == "FIBER":
        _fiber_sync().clear_solver_cache(entity_id)


def _delete_target(root, scene, kind, entity_id):
    return _delete_reconcile()(root, scene, {_delete_key(kind, entity_id)})


def _delete_key(kind, entity_id):
    role = "PROXY" if kind == "FIBER" else "BASE"
    return kind, entity_id, role


def _sync_delete(root, scene):
    hints = _empty_dirty_hints()()
    _sync_scene()(root=root, scene=scene, dirty_hints=hints, source="operator", event_type="DELETE")


def _delete_reconcile():
    try:
        from ...core.visualization.delete_reconcile import reconcile_deleted_entities
    except ImportError:
        from core.visualization.delete_reconcile import reconcile_deleted_entities
    return reconcile_deleted_entities


def _sync_scene():
    try:
        from ...app.runtime_api import sync_scene
    except ImportError:
        from app.runtime_api import sync_scene
    return sync_scene


def _empty_dirty_hints():
    try:
        from ...core.deps.dirty_hints import empty_dirty_hints
    except ImportError:
        from core.deps.dirty_hints import empty_dirty_hints
    return empty_dirty_hints


def _fiber_sync():
    try:
        from ...core.visualization.fiber_sync import register_fiber_sync
    except ImportError:
        from core.visualization.fiber_sync import register_fiber_sync
    return register_fiber_sync()
