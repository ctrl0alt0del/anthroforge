import bpy
from mathutils import Vector

from ..utils import get_af_root
from .blob_sync_helpers import target_object_for_blob


def sync_root_to_scene(sync, root=None, scene=None, target_blob_ids=None):
    if sync._syncing:
        return

    scene = scene or bpy.context.scene
    root = root or get_af_root(scene)
    if root is None or not hasattr(root, "af_vcp_system"):
        return

    sync._syncing = True
    try:
        vis_col = sync._get_vis_collection(scene)
        vcp = root.af_vcp_system

        all_blob_ids = {b.id for b in vcp.blobs}
        blob_ids_to_sync = all_blob_ids if target_blob_ids is None else (set(target_blob_ids) & all_blob_ids)

        for bp in vcp.blobs:
            if bp.id not in blob_ids_to_sync:
                continue

            obj = sync._find_blob_proxy(vis_col, root.name, bp.id)
            created = False
            if obj is None:
                obj = sync._create_blob_proxy(vis_col, root, bp.id)
                created = True
            if created:
                sync._apply_initial_transform_from_prop(obj, bp)

            ctrl = sync._find_blob_control(vis_col, root.name, bp.id)
            if ctrl is None:
                ctrl = sync._create_blob_control(vis_col, root, bp.id)

            ctrl_loc = Vector((bp.control_point_world[0], bp.control_point_world[1], bp.control_point_world[2]))
            if ctrl_loc.length_squared == 0.0:
                ctrl_loc = obj.matrix_world.to_translation().copy()
            ctrl.location = ctrl_loc

            runtime = sync._runtime_from_proxy_transform(bp, obj)
            runtime.control_point_world = ctrl.location.copy()
            target_obj = target_object_for_blob(scene, root, bp)

            unit_local, faces = sync._unit_local_mesh(runtime)
            rest_world = [obj.matrix_world @ v for v in unit_local]

            result = sync._solver.solve(
                blob=runtime,
                target_obj=target_obj,
                rest_world_verts=rest_world,
                face_indices=faces,
            )
            sync._update_mesh_from_world(obj, result.points, faces)

            obj["af_blob_proxy"] = True
            obj["af_root_name"] = root.name
            obj["af_blob_id"] = bp.id

            bp.last_solve_converged = bool(result.converged)
            bp.last_solve_max_disp = float(result.max_disp)
            bp.last_solve_iterations = int(result.iterations_used)

            active = (vcp.active_vcp_type == "BLOB" and vcp.active_vcp_id == bp.id)
            sync._ensure_blob_material(obj, active=active)

        if target_blob_ids is None:
            for o in list(vis_col.objects):
                if o.get("af_root_name") != root.name:
                    continue
                if o.get("af_blob_proxy") and o.get("af_blob_id") not in all_blob_ids:
                    sync._remove_proxy(o)
                if o.get("af_blob_control_gizmo") and o.get("af_blob_id") not in all_blob_ids:
                    sync._remove_ctrl(o)
    finally:
        sync._syncing = False


def on_depsgraph_update(sync, scene, depsgraph):
    if sync._syncing:
        return

    root = get_af_root(scene)
    if root is None or not hasattr(root, "af_vcp_system"):
        return

    changed_blob_ids = set()
    blobs_by_id = {b.id for b in root.af_vcp_system.blobs}

    sync._syncing = True
    try:
        for upd in depsgraph.updates:
            obj = upd.id
            if not isinstance(obj, bpy.types.Object):
                continue

            for b in root.af_vcp_system.blobs:
                if b.attach_target_type == "OBJECT" and b.attach_target_object_name == obj.name:
                    changed_blob_ids.add(b.id)

            if obj.get("af_blob_proxy") and obj.get("af_root_name") == root.name and obj.get("af_blob_id"):
                changed_blob_ids.add(obj.get("af_blob_id"))

            if obj.get("af_blob_control_gizmo") and obj.get("af_root_name") == root.name and obj.get("af_blob_id"):
                bid = obj.get("af_blob_id")
                b = blobs_by_id.get(bid)
                if b is not None:
                    new_loc = obj.location.copy()
                    if sync._vec_changed(b.control_point_world, new_loc):
                        b.control_point_world = (new_loc.x, new_loc.y, new_loc.z)
                        changed_blob_ids.add(bid)
    finally:
        sync._syncing = False

    if changed_blob_ids:
        from .sync_runner import sync_from_blob_ids

        sync_from_blob_ids(root=root, scene=scene, blob_ids=changed_blob_ids)
