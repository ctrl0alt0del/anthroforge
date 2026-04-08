import bpy
from mathutils import Vector

from ..deps.dirty_hints import dirty_hints_for
from ..utils import get_af_root
from .blob_sync_helpers import target_object_for_blob


def _resolve_root_scene(root, scene):
    scene = scene or bpy.context.scene
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


def _sync_blob_geometry(sync, scene, root, bp, obj, ctrl):
    runtime = sync._runtime_from_proxy_transform(bp, obj)
    runtime.control_point_world = ctrl.location.copy()
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
    bp.last_solve_converged = bool(result.converged)
    bp.last_solve_max_disp = float(result.max_disp)
    bp.last_solve_iterations = int(result.iterations_used)
    active = (vcp.active_vcp_type == "BLOB" and vcp.active_vcp_id == bp.id)
    sync._ensure_blob_material(obj, active=active)


def _cleanup_stale_blob_objects(sync, vis_col, root_name, all_blob_ids):
    for o in list(vis_col.objects):
        if o.get("af_root_name") != root_name:
            continue
        if o.get("af_blob_proxy") and o.get("af_blob_id") not in all_blob_ids:
            sync._remove_proxy(o)
        if o.get("af_blob_control_gizmo") and o.get("af_blob_id") not in all_blob_ids:
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

        all_blob_ids, blob_ids_to_sync = _blob_ids_to_sync(vcp, target_blob_ids)

        for bp in vcp.blobs:
            if bp.id not in blob_ids_to_sync:
                continue

            obj = _ensure_blob_proxy(sync, vis_col, root, bp)
            ctrl = _ensure_blob_ctrl(sync, vis_col, root, bp, obj)
            result = _sync_blob_geometry(sync, scene, root, bp, obj, ctrl)
            _update_blob_meta(sync, root, vcp, bp, obj, result)

        if target_blob_ids is None:
            _cleanup_stale_blob_objects(sync, vis_col, root.name, all_blob_ids)
    finally:
        sync._syncing = False


def _mark_changed_by_target(root, obj, changed_blob_ids):
    for b in root.af_vcp_system.blobs:
        if b.attach_target_type == "OBJECT" and b.attach_target_object_name == obj.name:
            changed_blob_ids.add(b.id)


def _mark_changed_by_proxy(root, obj, changed_blob_ids):
    if obj.get("af_blob_proxy") and obj.get("af_root_name") == root.name and obj.get("af_blob_id"):
        changed_blob_ids.add(obj.get("af_blob_id"))


def _mark_changed_by_ctrl(sync, root, obj, blobs_by_id, changed_blob_ids):
    if not obj.get("af_blob_control_gizmo") or obj.get("af_root_name") != root.name or not obj.get("af_blob_id"):
        return
    bid = obj.get("af_blob_id")
    b = blobs_by_id.get(bid)
    if b is None:
        return
    new_loc = obj.location.copy()
    if not sync._vec_changed(b.control_point_world, new_loc):
        return
    b.control_point_world = (new_loc.x, new_loc.y, new_loc.z)
    changed_blob_ids.add(bid)


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
