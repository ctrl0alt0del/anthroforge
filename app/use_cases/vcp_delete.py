from ..queries.root import root_for_context
from .results import failure, success
try:
    from ...core.vcp.surface_target import effective_tissue_target
except ImportError:
    from core.vcp.surface_target import effective_tissue_target


def delete_vcp_in_tree(context, node_type, node_id):
    root = root_for_context(context)
    target = _resolved_target(root, node_type, node_id)
    if target is None:
        return failure("VCP not found.")
    kind, entity_id = target
    blocked = _consumer_error(root, kind, entity_id)
    if blocked:
        return failure(blocked)
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
    return (kind if kind in {"FIBER", "FIBER_SURFACE", "MUSCLE", "SOFT_TISSUE"} else "", entity_id)


def _has_target(vcp, kind, entity_id):
    if kind == "FIBER":
        items = vcp.fibers
    elif kind == "FIBER_SURFACE":
        items = vcp.fiber_surfaces
    elif kind == "MUSCLE":
        items = vcp.muscles
    else:
        items = getattr(vcp, "soft_tissues", ())
    return any(str(getattr(item, "id", "")) == entity_id for item in items)


def _clear_runtime_cache(kind, entity_id):
    if kind == "FIBER":
        sync = _fiber_sync()
        try:
            sync.clear_solver_cache()
        except TypeError:
            sync.clear_solver_cache(entity_id)


def _delete_target(root, scene, kind, entity_id):
    if kind == "SOFT_TISSUE":
        return _delete_soft_tissue(root, scene, entity_id)
    if kind == "FIBER_SURFACE":
        return _delete_fiber_surface(root, scene, entity_id)
    deleted = _delete_reconcile()(root, scene, {_delete_key(kind, entity_id)}, explicit=True)
    _clear_active_entity(root.af_vcp_system, kind, entity_id)
    return deleted


def _clear_active_entity(vcp, kind, entity_id):
    if str(vcp.active_vcp_type) == kind and str(vcp.active_vcp_id) == entity_id:
        vcp.active_vcp_type, vcp.active_vcp_id = "NONE", ""


def _consumer_error(root, kind, entity_id):
    if kind == "FIBER":
        users = [surface.id for surface in getattr(root.af_vcp_system, "fiber_surfaces", ())
                 if any(ref.fiber_id == entity_id for ref in surface.fiber_refs)]
        return "Fiber is used by: " + ", ".join(users) if users else ""
    if kind == "FIBER_SURFACE":
        users = _surface_consumers(root, entity_id)
        return "Fiber Surface is used by: " + ", ".join(users) if users else ""
    if kind == "MUSCLE":
        users = target_tissue_consumers(root, kind, entity_id)
        return "Muscle is targeted by: " + ", ".join(users) if users else ""
    return ""


def target_tissue_consumers(root, kind, entity_id):
    out = []
    for tissue in getattr(root.af_vcp_system, "soft_tissues", ()):
        target = effective_tissue_target(tissue)
        if target.kind.value == str(kind) and target.entity_id == str(entity_id):
            out.append(str(tissue.id))
    return out


def _surface_consumers(root, surface_id):
    muscles = [muscle.id for muscle in root.af_vcp_system.muscles
               if str(getattr(muscle, "surface_source_mode", "")) == "FIBER_SURFACE"
               and str(getattr(muscle, "fiber_surface_id", "")) == surface_id]
    tissues = [tissue.id for tissue in root.af_vcp_system.soft_tissues
               if str(getattr(tissue, "base_source_type", "")) == "FIBER_SURFACE"
               and str(getattr(tissue, "base_source_id", "")) == surface_id]
    return muscles + tissues


def _delete_fiber_surface(root, scene, entity_id):
    surfaces = root.af_vcp_system.fiber_surfaces
    index = next((i for i, item in enumerate(surfaces) if item.id == entity_id), -1)
    if index < 0:
        return False
    _remove_surface_proxy(scene, root.name, entity_id)
    surfaces.remove(index)
    _clear_active_surface(root.af_vcp_system, entity_id)
    return True


def _remove_surface_proxy(scene, root_name, entity_id):
    for obj in tuple(scene.objects):
        owned = obj.get("af_fiber_surface_proxy") and obj.get("af_root_name") == root_name
        if owned and obj.get("af_fiber_surface_id") == entity_id:
            _remove_object(obj)


def _clear_active_surface(vcp, entity_id):
    if vcp.active_vcp_type == "FIBER_SURFACE" and vcp.active_vcp_id == entity_id:
        vcp.active_vcp_type, vcp.active_vcp_id = "NONE", ""


def _delete_soft_tissue(root, scene, entity_id):
    vcp = root.af_vcp_system
    tissues = vcp.soft_tissues
    index = next((i for i, item in enumerate(tissues) if item.id == entity_id), -1)
    if index < 0:
        return False
    tissue = tissues[index]
    _remove_tissue_objects(scene, root.name, tissue)
    tissues.remove(index)
    if vcp.active_vcp_type == "SOFT_TISSUE" and vcp.active_vcp_id == entity_id:
        vcp.active_vcp_type, vcp.active_vcp_id = "NONE", ""
    return True


def _remove_tissue_objects(scene, root_name, tissue):
    for obj in tuple(scene.objects):
        owned_proxy = obj.get("af_root_name") == root_name and obj.get("af_soft_tissue_id") == tissue.id
        if owned_proxy and (obj.get("af_soft_tissue_proxy") or obj.get("af_soft_tissue_rest_proxy")):
            _remove_object(obj)
    if tissue.base_owned and tissue.base_object_ref is not None:
        _remove_object(tissue.base_object_ref)
    elif tissue.base_object_ref is not None:
        _clear_tissue_tags(tissue.base_object_ref)


def _clear_tissue_tags(obj):
    for key in ("af_soft_tissue_base", "af_soft_tissue_id", "af_root_name"):
        if key in obj:
            del obj[key]


def _remove_object(obj):
    import bpy
    data = getattr(obj, "data", None)
    bpy.data.objects.remove(obj, do_unlink=True)
    if data is not None and data.users == 0:
        bpy.data.meshes.remove(data)


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
