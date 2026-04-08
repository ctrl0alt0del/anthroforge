import bpy

from ..registry import SCPRegistry
from ..utils import get_af_root
from ..attachment_codec import encode_fiber_mesh_anchor, encode_fiber_shape_param


def sync_handles(sync, root, scene, vis_col, runtime_registry):
    live_endpoint_keys = set()
    live_touch_keys = set()

    for fiber in root.af_vcp_system.fibers:
        for endpoint, pid, raw in (
            ("A", fiber.a_parent_id, fiber.a_attach_param),
            ("B", fiber.b_parent_id, fiber.b_attach_param),
        ):
            live_endpoint_keys.add((fiber.id, endpoint))
            h = sync._find_endpoint_handle(vis_col, root.name, fiber.id, endpoint)
            if h is None:
                h = sync._create_endpoint_handle(vis_col, root, fiber.id, endpoint)
            w = sync._endpoint_world(root, scene, runtime_registry, pid, raw)
            if w is not None:
                h.location = w
                sync._set_helper_screen_size(h, px=14.0)

        for i, tp in enumerate(fiber.mid_touches):
            live_touch_keys.add((fiber.id, i))
            h = sync._find_touch_handle(vis_col, root.name, fiber.id, i)
            if h is None:
                h = sync._create_touch_handle(vis_col, root, fiber.id, i)
            w = sync._endpoint_world(root, scene, runtime_registry, tp.parent_id, tp.attach_param)
            if w is not None:
                h.location = w
                sync._set_helper_screen_size(h, px=12.0)

    for obj in list(vis_col.objects):
        if obj.get("af_fiber_endpoint_handle") and obj.get("af_root_name") == root.name:
            key = (obj.get("af_fiber_id"), obj.get("af_fiber_endpoint"))
            if key not in live_endpoint_keys:
                bpy.data.objects.remove(obj, do_unlink=True)

        if obj.get("af_fiber_touch_handle") and obj.get("af_root_name") == root.name:
            key = (obj.get("af_fiber_id"), int(obj.get("af_fiber_touch_index", -1)))
            if key not in live_touch_keys:
                bpy.data.objects.remove(obj, do_unlink=True)


def apply_selection_highlight(sync, root, scene):
    active_id = root.af_vcp_system.active_vcp_id
    active_type = root.af_vcp_system.active_vcp_type
    for obj in scene.objects:
        if not obj.get("af_fiber_proxy"):
            continue
        if obj.get("af_root_name") != root.name:
            continue
        base = tuple(obj.get("af_fiber_base_color", sync.default_fiber_color))
        sync._set_fiber_color(
            obj,
            sync.selected_fiber_color if active_type == "FIBER" and obj.get("af_fiber_id") == active_id else base,
        )


def sync_root_to_scene(sync, root=None, scene=None, bake=False, target_fiber_ids=None):
    if sync._syncing:
        return
    scene = scene or bpy.context.scene
    root = root or get_af_root(scene)
    if root is None or not hasattr(root, "af_vcp_system"):
        return

    sync._syncing = True
    try:
        vis_col = sync._get_vis_collection(scene)
        depsgraph = bpy.context.evaluated_depsgraph_get()
        runtime = SCPRegistry(root)
        runtime.build()

        if target_fiber_ids is None:
            fibers_to_sync = list(root.af_vcp_system.fibers)
        else:
            target_set = set(target_fiber_ids)
            fibers_to_sync = [f for f in root.af_vcp_system.fibers if f.id in target_set]

        live_ids = set()
        for fiber in fibers_to_sync:
            live_ids.add(fiber.id)
            obj = sync._find_fiber_proxy(vis_col, root.name, fiber.id)
            if obj is None:
                obj = sync._create_fiber_proxy(vis_col, root, fiber.id)

            use_bake = bool(bake or sync._fiber_prefer_bake(fiber))
            points = sync._solver.solve_points(
                root=root, fiber_prop=fiber, scene=scene, depsgraph=depsgraph, bake=use_bake
            )
            if len(points) >= 2:
                sync._update_curve_points(obj, points, fiber.thickness, bake=use_bake)

        if target_fiber_ids is None:
            for obj in list(vis_col.objects):
                if (
                    obj.get("af_fiber_proxy")
                    and obj.get("af_root_name") == root.name
                    and obj.get("af_fiber_id") not in live_ids
                ):
                    bpy.data.objects.remove(obj, do_unlink=True)

        sync._sync_handles(root, scene, vis_col, runtime.registry)
        sync._apply_selection_highlight(root, scene)
    finally:
        sync._syncing = False


def on_depsgraph_update(sync, scene, depsgraph):
    if sync._syncing:
        return
    root = get_af_root(scene)
    if root is None or not hasattr(root, "af_vcp_system"):
        return

    vis_col = bpy.data.collections.get(sync.collection_name)
    if vis_col is None:
        return

    runtime = SCPRegistry(root)
    runtime.build()

    changed = False
    changed_fiber_ids = set()

    sync._syncing = True
    try:
        for upd in depsgraph.updates:
            obj = upd.id
            if not isinstance(obj, bpy.types.Object):
                continue
            if obj.get("af_root_name") != root.name:
                continue
            if vis_col.objects.get(obj.name) is None:
                continue

            if obj.get("af_fiber_endpoint_handle"):
                fiber_id = obj.get("af_fiber_id")
                endpoint = obj.get("af_fiber_endpoint")
                fiber = next((f for f in root.af_vcp_system.fibers if f.id == fiber_id), None)
                if fiber is None:
                    continue

                parent_id = fiber.a_parent_id if endpoint == "A" else fiber.b_parent_id
                parent_scp = runtime.registry.get(parent_id)
                parent_proxy = sync._get_scp_proxy(scene, root.name, parent_id)
                if parent_scp is None or parent_proxy is None:
                    continue

                if getattr(parent_scp.shape, "type_id", "") == "MESH_ASSET":
                    local_pt = sync._nearest_parent_mesh_vertex_local_point(parent_proxy, obj.location.copy())
                    if local_pt is None:
                        continue
                    raw = encode_fiber_mesh_anchor(local_pt)
                else:
                    param = sync._nearest_param(parent_scp, parent_proxy, obj.location.copy())
                    raw = encode_fiber_shape_param(param)

                if endpoint == "A":
                    if fiber.a_attach_param != raw:
                        fiber.a_attach_param = raw
                        sync._set_fiber_prefer_bake(fiber, False)
                        changed = True
                        changed_fiber_ids.add(fiber.id)
                else:
                    if fiber.b_attach_param != raw:
                        fiber.b_attach_param = raw
                        sync._set_fiber_prefer_bake(fiber, False)
                        changed = True
                        changed_fiber_ids.add(fiber.id)

            elif obj.get("af_fiber_touch_handle"):
                fiber_id = obj.get("af_fiber_id")
                touch_index = int(obj.get("af_fiber_touch_index", -1))
                fiber = next((f for f in root.af_vcp_system.fibers if f.id == fiber_id), None)
                if fiber is None:
                    continue
                if touch_index < 0 or touch_index >= len(fiber.mid_touches):
                    continue

                tp = fiber.mid_touches[touch_index]
                parent_id = tp.parent_id
                parent_scp = runtime.registry.get(parent_id)
                parent_proxy = sync._get_scp_proxy(scene, root.name, parent_id)
                if parent_scp is None or parent_proxy is None:
                    continue

                if getattr(parent_scp.shape, "type_id", "") == "MESH_ASSET":
                    local_pt = sync._nearest_parent_mesh_vertex_local_point(parent_proxy, obj.location.copy())
                    if local_pt is None:
                        continue
                    raw = encode_fiber_mesh_anchor(local_pt)
                else:
                    param = sync._nearest_param(parent_scp, parent_proxy, obj.location.copy())
                    raw = encode_fiber_shape_param(param)

                if tp.attach_param != raw:
                    tp.attach_param = raw
                    sync._set_fiber_prefer_bake(fiber, False)
                    changed = True
                    changed_fiber_ids.add(fiber.id)
    finally:
        sync._syncing = False

    if changed:
        from .sync_runner import sync_from_fiber_ids

        sync_from_fiber_ids(root=root, scene=scene, fiber_ids=changed_fiber_ids)
