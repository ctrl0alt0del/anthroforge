import bpy
from mathutils import Vector

from ..deps.dirty_hints import dirty_hints_for
from ..deps.controls import classify_control_object, enqueue_control_intent
from ..deps.conflict_resolver import resolve_conflict
from ..utils import get_af_root, scene_for_id
from ..vcp.runtime_state import set_blob_solve_converged, set_blob_solve_iterations, set_blob_solve_max_disp
from .blob_sync_helpers import target_object_for_blob
from .control_runtime import active_entity_id


def _resolve_root_scene(root, scene):
    scene = scene or scene_for_id(root)
    root = root or get_af_root(scene)
    if root is None or not hasattr(root, "af_vcp_system"):
        return None, None
    return root, scene


def _blob_ids_to_sync(vcp, target_blob_ids):
    all_blob_ids = {b.id for b in vcp.blobs}
    if target_blob_ids is None:
        return all_blob_ids, all_blob_ids
    return all_blob_ids, set(target_blob_ids) & all_blob_ids


def _ensure_blob_proxy(sync, vis_col, root, bp):
    obj = sync._find_blob_proxy(vis_col, root.name, bp.id)
    if obj is not None:
        return obj
    obj = sync._create_blob_proxy(vis_col, root, bp.id)
    sync._apply_initial_transform_from_prop(obj, bp)
    return obj


def _ensure_blob_ctrl(sync, vis_col, root, bp, obj):
    ctrl = sync._find_blob_control(vis_col, root.name, bp.id)
    if ctrl is None:
        ctrl = sync._create_blob_control(vis_col, root, bp.id)
    ctrl_loc = Vector((bp.control_point_world[0], bp.control_point_world[1], bp.control_point_world[2]))
    if ctrl_loc.length_squared == 0.0:
        ctrl_loc = obj.matrix_world.to_translation().copy()
    ctrl.location = ctrl_loc
    return ctrl


def _active_blob_id(root):
    return active_entity_id(root, "BLOB")


def _sync_blob_geometry(sync, scene, root, bp, obj, control_world):
    runtime = sync._runtime_from_proxy_transform(bp, obj)
    runtime.control_point_world = control_world.copy()
    target_obj = target_object_for_blob(scene, root, bp)
    unit_local, faces = sync._unit_local_mesh(runtime)
    rest_world = [obj.matrix_world @ v for v in unit_local]
    result = sync._solver.solve(blob=runtime, target_obj=target_obj, rest_world_verts=rest_world, face_indices=faces)
    sync._update_mesh_from_world(obj, result.points, faces)
    return result


def _update_blob_meta(sync, root, vcp, bp, obj, result):
    obj["af_blob_proxy"] = True
    obj["af_root_name"] = root.name
    obj["af_blob_id"] = bp.id
    set_blob_solve_converged(bp, bool(result.converged))
    set_blob_solve_max_disp(bp, float(result.max_disp))
    set_blob_solve_iterations(bp, int(result.iterations_used))
    active = (vcp.active_vcp_type == "BLOB" and vcp.active_vcp_id == bp.id)
    sync._ensure_blob_material(obj, active=active)


def _cleanup_stale_blob_objects(sync, vis_col, root_name, all_blob_ids):
    for o in list(vis_col.objects):
        if _safe_get(o, "af_root_name") != root_name:
            continue
        if _safe_get(o, "af_blob_proxy") and _safe_get(o, "af_blob_id") not in all_blob_ids:
            sync._remove_proxy(o)
        if _safe_get(o, "af_blob_control_gizmo") and _safe_get(o, "af_blob_id") not in all_blob_ids:
            sync._remove_ctrl(o)


def sync_root_to_scene(sync, root=None, scene=None, target_blob_ids=None):
    if sync._syncing:
        return

    root, scene = _resolve_root_scene(root, scene)
    if root is None:
        return

    sync._syncing = True
    try:
        vis_col = sync._get_vis_collection(scene)
        vcp = root.af_vcp_system
        active_blob_id = _active_blob_id(root)

        all_blob_ids, blob_ids_to_sync = _blob_ids_to_sync(vcp, target_blob_ids)

        for bp in vcp.blobs:
            if bp.id not in blob_ids_to_sync:
                continue

            obj = _ensure_blob_proxy(sync, vis_col, root, bp)
            if active_blob_id and bp.id == active_blob_id:
                ctrl = _ensure_blob_ctrl(sync, vis_col, root, bp, obj)
                control_world = ctrl.location.copy()
            else:
                control_world = Vector((bp.control_point_world[0], bp.control_point_world[1], bp.control_point_world[2]))
            result = _sync_blob_geometry(sync, scene, root, bp, obj, control_world)
            _update_blob_meta(sync, root, vcp, bp, obj, result)

        _cleanup_stale_blob_objects(sync, vis_col, root.name, all_blob_ids)
        for o in list(vis_col.objects):
            if not _safe_get(o, "af_blob_control_gizmo") or _safe_get(o, "af_root_name") != root.name:
                continue
            if active_blob_id and _safe_get(o, "af_blob_id") == active_blob_id:
                continue
            sync._remove_ctrl(o)
    finally:
        sync._syncing = False


def _mark_changed_by_target(root, obj, changed_blob_ids):
    for b in root.af_vcp_system.blobs:
        if b.attach_target_type == "OBJECT" and b.attach_target_object_name == obj.name:
            changed_blob_ids.add(b.id)


def _mark_changed_by_proxy(root, obj, changed_blob_ids):
    if (
        obj.get("af_blob_proxy")
        and not obj.get("af_blob_mirror_proxy")
        and obj.get("af_root_name") == root.name
        and obj.get("af_blob_id")
    ):
        changed_blob_ids.add(obj.get("af_blob_id"))


def _mark_changed_by_ctrl(sync, root, obj, blobs_by_id, changed_blob_ids):
    classified = classify_control_object(obj)
    if not classified or str(classified["control_type"]) != "BLOB_CONTROL":
        return
    payload = dict(classified["payload"])
    payload["binding"] = classified.get("binding")
    if enqueue_control_intent(root, classified["control_type"], payload):
        changed_blob_ids |= set(classified["dirty_hints"].get("BLOB", set()) or set())


def apply_blob_control_update(sync, root, scene, obj):
    if not obj.get("af_blob_control_gizmo") or obj.get("af_root_name") != root.name or not obj.get("af_blob_id"):
        return None
    bid = obj.get("af_blob_id")
    blobs_by_id = {b.id: b for b in root.af_vcp_system.blobs}
    b = blobs_by_id.get(bid)
    if b is None:
        return None
    incoming = obj.location.copy()
    current = tuple(b.control_point_world)
    resolved = resolve_conflict(
        entity_type="BLOB",
        entity_id=str(bid or ""),
        aspect="control_point.world",
        source="blender_control",
        current=current,
        incoming=(incoming.x, incoming.y, incoming.z),
        payload={"control": "blob"},
    )
    try:
        new_loc = Vector((float(resolved[0]), float(resolved[1]), float(resolved[2])))
    except Exception:
        new_loc = incoming
    if not sync._vec_changed(b.control_point_world, new_loc):
        return None
    b.control_point_world = (new_loc.x, new_loc.y, new_loc.z)
    return bid


def _safe_get(obj, key, default=None):
    try:
        return obj.get(key, default)
    except ReferenceError:
        return default


def on_depsgraph_update(sync, scene, depsgraph):
    if sync._syncing:
        return

    root = get_af_root(scene)
    if root is None or not hasattr(root, "af_vcp_system"):
        return

    changed_blob_ids = set()
    blobs_by_id = {b.id: b for b in root.af_vcp_system.blobs}

    sync._syncing = True
    try:
        for upd in depsgraph.updates:
            obj = upd.id
            if not isinstance(obj, bpy.types.Object):
                continue

            _mark_changed_by_target(root, obj, changed_blob_ids)
            _mark_changed_by_proxy(root, obj, changed_blob_ids)
            _mark_changed_by_ctrl(sync, root, obj, blobs_by_id, changed_blob_ids)
    finally:
        sync._syncing = False

    if changed_blob_ids:
        from .sync_runner import sync_from_dirty_hints

        sync_from_dirty_hints(
            root=root,
            scene=scene,
            dirty_hints=dirty_hints_for("BLOB", changed_blob_ids),
            source="depsgraph",
            event_type="TRANSFORM",
        )
